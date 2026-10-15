// uisnap: PNG snapshots of the betangel-suite UI in an offscreen WKWebView (DESIGN.md 11, test group 7).
//
// Built and run only by `bin/suite uisnap` (betangel_suite/uisnap.py), against the synthetic-only engine that
// command starts on an ephemeral 127.0.0.1 port. Build (the one argv the uisnap guard mode allows):
//   swiftc -swift-version 5 -O -target arm64-apple-macos14.0 -sdk <CLT SDK> -module-cache-path <dir> -o uisnap uisnap.swift
// Apple SDK frameworks only (AppKit, CoreGraphics, Foundation, WebKit).
//
// Input: one JSON object on stdin, {"url": "http://127.0.0.1:<port>/#c=<code>", "seed": n, "timeout_s": n}. The
// URL holds a single-use bootstrap code, so it never appears in argv, on stdout or stderr, or in a record.
// Output: JSON lines on the original stdout. fd 1 itself is pointed at /dev/null first, so nothing a framework
// prints can mix in. One {"t": "png", "name", "width", "height", "png": <base64>} per step, then one
// {"t": "report", ...} holding codes, counts and booleans only. Exit status 0, or one of Exit below.
//
// Never visible, never focused:
//   - activation policy .prohibited (no Dock icon, no menu bar, never activates, never takes focus);
//   - one borderless window that is never ordered in (no orderFront, makeKey or activate call exists here); it
//     answers WebKit's visibility questions as an unoccluded window would (OffscreenWindow), because WebKit
//     suspends requestAnimationFrame, and so the page's rendering, for a hidden page;
//   - CGWindowListCopyWindowInfo(.optionOnScreenOnly) is checked for this pid before the load, every 100 ms, at
//     every snapshot and at the end: any window of ours on screen ends the run with window_onscreen (16);
//   - no panels: the UI delegate answers alerts, confirms and prompts itself and opens no window.
// Never off the loopback:
//   - the navigation delegate allows only main-frame http://127.0.0.1:<port>/... (any other navigation ends the
//     run with navigation_refused), refuses every authentication challenge, and must be wired (checked);
//   - every subresource and fetch is limited to 'self' by the page's own CSP (unchanged);
//   - WKWebsiteDataStore.nonPersistent(), no safe-browsing lookups, no HTTPS upgrade of known hosts.
//
// Steps (the helper script runs in the isolated .defaultClient world; it reads the DOM and dispatches clicks and
// key events, which the page handles exactly as user input): initial (status line "connected"), market (open a
// synthetic market by seed), ladder (play at 10x, select a runner, press L), help (press ?), inplay (? again,
// + twice to 60x, wait for IN-PLAY, Space to pause), closed (Space to play, wait for CLOSED). Each step is
// followed by a WKWebView.takeSnapshot of the whole 1470x830 viewport (the Air's Safari).
//
// Page errors: the helper listens for error, unhandledrejection and securitypolicyviolation events and posts
// only their kind to a WKScriptMessageHandler in its own world (no change to the server's CSP). A probe error
// thrown in the page world checks that the listener sees page errors; when the handler is unavailable the
// report says so and counts none.

import AppKit
import CoreGraphics
import Foundation
import WebKit

let viewport = NSRect(x: 0, y: 0, width: 1470, height: 830)
let stepNames = ["initial", "market", "ladder", "help", "inplay", "closed"]
let maxInputBytes = 4096
let handlerName = "uisnap"

enum Exit: Int32 {
    case ok = 0
    case badInput = 10
    case navigationRefused = 11
    case loadFailed = 12
    case notConnected = 13
    case stepFailed = 14
    case snapshotFailed = 15
    case windowOnscreen = 16
    case timeout = 17
    case pageErrors = 18
    case internalError = 19

    var code: String {
        switch self {
        case .ok: return "ok"
        case .badInput: return "bad_input"
        case .navigationRefused: return "navigation_refused"
        case .loadFailed: return "load_failed"
        case .notConnected: return "not_connected"
        case .stepFailed: return "step_failed"
        case .snapshotFailed: return "snapshot_failed"
        case .windowOnscreen: return "window_onscreen"
        case .timeout: return "timeout"
        case .pageErrors: return "page_errors"
        case .internalError: return "failed"
        }
    }
}

// MARK: - output records

// The records go to a duplicate of the original stdout; fd 1 then points at /dev/null.
let recordFD: Int32 = {
    let fd = dup(STDOUT_FILENO)
    let null = open("/dev/null", O_WRONLY)
    if fd < 0 || null < 0 || dup2(null, STDOUT_FILENO) < 0 {
        _exit(Exit.internalError.rawValue)
    }
    close(null)
    _ = fcntl(fd, F_SETFD, FD_CLOEXEC)
    return fd
}()

func writeAll(_ data: Data) -> Bool {
    return data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) -> Bool in
        guard var pointer = raw.baseAddress else { return true }
        var left = raw.count
        while left > 0 {
            let written = write(recordFD, pointer, left)
            if written < 0 {
                if errno == EINTR { continue }
                return false
            }
            pointer = pointer.advanced(by: written)
            left -= written
        }
        return true
    }
}

func emit(_ record: [String: Any]) -> Bool {
    guard JSONSerialization.isValidJSONObject(record),
          var data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]) else {
        return false
    }
    data.append(0x0A)
    return writeAll(data)
}

// MARK: - input

struct Input {
    let url: URL
    let port: Int
    let seed: Int
    let timeoutS: Int
}

func isPlainInt(_ value: Any?) -> Int? {
    guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
          CFNumberIsFloatType(number) == false else { return nil }
    return number.intValue
}

func readInput() -> Input? {
    var data = Data()
    var buffer = [UInt8](repeating: 0, count: 1024)
    while data.count <= maxInputBytes {
        let count = read(STDIN_FILENO, &buffer, buffer.count)
        if count < 0 {
            if errno == EINTR { continue }
            return nil
        }
        if count == 0 { break }
        data.append(buffer, count: count)
    }
    guard data.count <= maxInputBytes,
          let object = try? JSONSerialization.jsonObject(with: data, options: []),
          let fields = object as? [String: Any], Set(fields.keys) == ["url", "seed", "timeout_s"],
          let text = fields["url"] as? String,
          let seed = isPlainInt(fields["seed"]), (0...999_999_999).contains(seed),
          let timeoutS = isPlainInt(fields["timeout_s"]), (30...900).contains(timeoutS) else {
        return nil
    }
    let pattern = "^http://127\\.0\\.0\\.1:([1-9][0-9]{0,4})/#c=[A-Za-z0-9_-]{22}$"
    guard let regex = try? NSRegularExpression(pattern: pattern),
          let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
          let portRange = Range(match.range(at: 1), in: text), let port = Int(text[portRange]),
          port <= 65535, let url = URL(string: text) else {
        return nil
    }
    return Input(url: url, port: port, seed: seed, timeoutS: timeoutS)
}

// MARK: - the helper script (isolated world)

let helperScript = #"""
(() => {
  'use strict';
  const post = (kind) => {
    try {
      const handlers = window.webkit && window.webkit.messageHandlers;
      if (handlers && handlers.uisnap) {
        handlers.uisnap.postMessage(kind);
      }
    } catch (e) {
      // the handler is unavailable: the report then counts no page errors
    }
  };
  window.addEventListener('error', (event) => {
    const message = event && typeof event.message === 'string' ? event.message : '';
    post(message.indexOf('uisnap-probe') >= 0 ? 'probe' : 'error');
  }, true);
  window.addEventListener('unhandledrejection', () => post('rejection'));
  document.addEventListener('securitypolicyviolation', () => post('csp'));
  post('hello');

  const byId = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });
  const text = (id) => { const node = byId(id); return node === null ? null : node.textContent; };
  const shown = (id) => { const node = byId(id); return node !== null && !node.hidden; };
  const rows = () => document.querySelectorAll('#grid-body tr');
  const speedPressed = (speed) => {
    const node = document.querySelector('button.speed[data-speed="' + speed + '"]');
    return node !== null && node.getAttribute('aria-pressed') === 'true';
  };
  const clockSpeed = () => {
    const match = /, ([0-9.]+x)$/.exec(text('clock') || '');
    return match === null ? '' : match[1];
  };
  const fail = (code) => ({ ok: false, code: code });

  async function until(predicate, ms) {
    const end = performance.now() + ms;
    for (;;) {
      let ok = false;
      try {
        ok = Boolean(predicate());
      } catch (e) {
        ok = false;
      }
      if (ok) {
        return true;
      }
      if (performance.now() >= end) {
        return false;
      }
      await sleep(50);
    }
  }

  // True once count animation frames have run (the page renders on requestAnimationFrame), false after ms.
  function frames(count, ms) {
    return Promise.race([
      new Promise((resolve) => {
        let seen = 0;
        const tick = () => {
          seen += 1;
          if (seen >= count) {
            resolve(true);
          } else {
            requestAnimationFrame(tick);
          }
        };
        requestAnimationFrame(tick);
      }),
      sleep(ms).then(() => false),
    ]);
  }

  function key(name) {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true }));
  }

  // Distinct coarse colours on the ladder canvas: a blank canvas has one or two.
  function ladderColours() {
    const canvas = byId('ladder');
    if (canvas === null || canvas.width === 0 || canvas.height === 0) {
      return 0;
    }
    const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    const seen = new Set();
    for (let i = 0; i < data.length && seen.size < 64; i += 4 * 7) {
      seen.add(((data[i] >> 4) << 8) | ((data[i + 1] >> 4) << 4) | (data[i + 2] >> 4));
    }
    return seen.size;
  }

  const steps = {
    async initial() {
      if (!(await until(() => text('conn') === 'connected', 20000))) {
        return fail('not_connected');
      }
      const raf = await frames(2, 2000);
      return { ok: true, checks: {
        title_static: document.title === 'betangel-suite',
        badge_synthetic: text('badge-synthetic') === 'SYNTHETIC DATA',
        controls_enabled: !byId('open').disabled,
        visibility: document.visibilityState,
        raf: raf,
      } };
    },
    async market(seed) {
      byId('seed').value = String(seed);
      byId('open').click();
      if (!(await until(() => rows().length > 0 && shown('market-status')
          && text('ladder-runner') !== 'No runner selected', 20000))) {
        return fail('market_not_shown');
      }
      const raf = await frames(2, 2000);
      return { ok: true, checks: {
        runners: rows().length,
        status_open: text('market-status') === 'OPEN',
        badge_synthetic: text('badge-synthetic') === 'SYNTHETIC DATA',
        raf: raf,
      } };
    },
    async ladder() {
      const ten = document.querySelector('button.speed[data-speed="1000"]');
      if (ten === null) {
        return fail('no_speed_button');
      }
      ten.click();
      if (!(await until(() => speedPressed(1000), 10000))) {
        return fail('speed_not_set');
      }
      byId('play').click();
      if (!(await until(() => text('play') === 'Pause', 10000))) {
        return fail('not_playing');
      }
      const list = rows();
      const row = list.length > 1 ? list[1] : list[0];
      row.click();
      if (!(await until(() => row.classList.contains('selected'), 10000))) {
        return fail('runner_not_selected');
      }
      key('L');
      await sleep(400);
      const raf = await frames(3, 2000);
      return { ok: true, checks: {
        ladder_colours: ladderColours(),
        selected_row: Array.prototype.indexOf.call(rows(), row) + 1,
        speed_10x: clockSpeed() === '10x',
        raf: raf,
      } };
    },
    async help() {
      key('?');
      if (!(await until(() => shown('help'), 5000))) {
        return fail('help_not_shown');
      }
      const raf = await frames(2, 2000);
      return { ok: true, checks: { help_items: document.querySelectorAll('#help-list li').length, raf: raf } };
    },
    async inplay() {
      key('?');
      if (!(await until(() => !shown('help'), 5000))) {
        return fail('help_not_hidden');
      }
      key('+');
      if (!(await until(() => clockSpeed() === '30x', 10000))) {
        return fail('speed_up_failed');
      }
      key('+');
      if (!(await until(() => clockSpeed() === '60x', 10000))) {
        return fail('speed_up_failed');
      }
      if (!(await until(() => shown('badge-inplay'), 120000))) {
        return fail('inplay_not_shown');
      }
      key(' ');
      if (!(await until(() => text('play') === 'Play', 10000))) {
        return fail('not_paused');
      }
      const raf = await frames(2, 2000);
      return { ok: true, checks: {
        inplay_badge: shown('badge-inplay'),
        countdown_inplay: (text('countdown') || '').indexOf('IN-PLAY') === 0,
        ladder_colours: ladderColours(),
        raf: raf,
      } };
    },
    async closed() {
      key(' ');
      if (!(await until(() => text('play') === 'Pause' || text('market-status') === 'CLOSED', 10000))) {
        return fail('not_resumed');
      }
      if (!(await until(() => text('market-status') === 'CLOSED', 60000))) {
        return fail('not_closed');
      }
      const raf = await frames(2, 2000);
      return { ok: true, checks: { status_closed: true, raf: raf } };
    },
  };

  window.__uisnapRun = async (name, arg) => {
    const step = Object.prototype.hasOwnProperty.call(steps, name) ? steps[name] : null;
    if (step === null) {
      return JSON.stringify(fail('unknown_step'));
    }
    try {
      return JSON.stringify(await step(arg));
    } catch (e) {
      return JSON.stringify(fail('step_exception'));
    }
  };
})();
"""#

// MARK: - the window

/// A borderless window that is never ordered in. WebKit suspends requestAnimationFrame (and so the page's whole
/// rendering) for a view whose window is not visible, and the window server would show a visible one; this
/// window only answers WebKit's questions (isVisible, occlusionState) as an unoccluded on-screen window would, so
/// the page renders as it does in Safari, while the window server holds no on-screen window for this process
/// (checked with CGWindowListCopyWindowInfo throughout). It can never become key or main.
final class OffscreenWindow: NSWindow {
    override var isVisible: Bool { return true }
    override var occlusionState: NSWindow.OcclusionState { return .visible }
    override var canBecomeKey: Bool { return false }
    override var canBecomeMain: Bool { return false }
}

// MARK: - windows of this process on screen

/// The number of this process's windows on screen, or -1 when the window list cannot be read.
func onscreenWindows() -> Int {
    guard let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] else {
        return -1
    }
    let pid = Int(getpid())
    return list.filter { ($0[kCGWindowOwnerPID as String] as? NSNumber)?.intValue == pid }.count
}

// MARK: - the controller

@MainActor
final class Controller: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    let input: Input
    var window: NSWindow?
    var webView: WKWebView?
    var finished = false
    var loaded = false
    var loadWaiter: CheckedContinuation<Bool, Never>?
    var decidedActions = 0
    var refusedNavigations = 0
    var counts: [String: Int] = ["hello": 0, "probe": 0, "error": 0, "rejection": 0, "csp": 0]
    var steps: [[String: Any]] = []
    var checks: [String: Any] = [:]
    var maxOnscreen = 0
    var samples = 0
    var sampler: Timer?
    let started = Date()

    init(input: Input) {
        self.input = input
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        DispatchQueue.main.asyncAfter(deadline: .now() + .seconds(input.timeoutS)) { [weak self] in
            self?.finish(.timeout)
        }
        let selectors = ["webView:decidePolicyForNavigationAction:decisionHandler:",
                         "webView:decidePolicyForNavigationResponse:decisionHandler:",
                         "webView:didReceiveAuthenticationChallenge:completionHandler:"]
        for name in selectors where !responds(to: NSSelectorFromString(name)) {
            finish(.internalError)
            return
        }

        let preferences = WKPreferences()
        preferences.isFraudulentWebsiteWarningEnabled = false
        preferences.javaScriptCanOpenWindowsAutomatically = false
        preferences.isElementFullscreenEnabled = false
        preferences.inactiveSchedulingPolicy = .none
        let content = WKUserContentController()
        content.add(self, contentWorld: .defaultClient, name: handlerName)
        content.addUserScript(WKUserScript(source: helperScript, injectionTime: .atDocumentStart,
                                           forMainFrameOnly: true, in: .defaultClient))
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.preferences = preferences
        configuration.userContentController = content
        configuration.upgradeKnownHostsToHTTPS = false
        configuration.mediaTypesRequiringUserActionForPlayback = .all
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true

        let window = OffscreenWindow(contentRect: viewport, styleMask: [.borderless], backing: .buffered, defer: true)
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: .aqua)
        let webView = WKWebView(frame: viewport, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        webView.allowsMagnification = false
        webView.allowsLinkPreview = false
        webView.isInspectable = false
        window.contentView = webView
        self.window = window
        self.webView = webView
        if !checkOnscreen() {
            return
        }
        // Between the checkpoints too: sample the window list every 100 ms for the whole run.
        sampler = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self = self, !self.finished else { return }
                self.samples += 1
                _ = self.checkOnscreen()
            }
        }
        Task { @MainActor in
            await self.run()
        }
    }

    // MARK: steps

    func run() async {
        guard let webView = webView else {
            finish(.internalError)
            return
        }
        let request = URLRequest(url: input.url, cachePolicy: .reloadIgnoringLocalAndRemoteCacheData, timeoutInterval: 30)
        webView.load(request)
        let ok = await withCheckedContinuation { (continuation: CheckedContinuation<Bool, Never>) in
            if loaded {
                continuation.resume(returning: true)
            } else {
                loadWaiter = continuation
            }
        }
        if !ok || finished {
            finish(.loadFailed)
            return
        }
        if decidedActions == 0 {
            finish(.internalError)         // the navigation delegate was not consulted: never run unchecked
            return
        }
        await probeErrors()
        for name in stepNames {
            let begin = Date()
            let result = await callStep(name)
            let milliseconds = Int(Date().timeIntervalSince(begin) * 1000)
            let ok = result["ok"] as? Bool ?? false
            var entry: [String: Any] = ["name": name, "ok": ok, "ms": milliseconds]
            if let code = result["code"] as? String { entry["code"] = code }
            steps.append(entry)
            if let found = result["checks"] as? [String: Any] {
                for (key, value) in found { checks[name + "_" + key] = value }
            }
            if !ok {
                finish(name == "initial" ? .notConnected : .stepFailed)
                return
            }
            if !checkOnscreen() { return }
            guard let (png, width, height) = await snapshot() else {
                finish(.snapshotFailed)
                return
            }
            if !emit(["t": "png", "name": name, "width": width, "height": height,
                      "png": png.base64EncodedString()]) {
                finish(.internalError)
                return
            }
        }
        let errors = counts["hello", default: 0] > 0
            ? counts["error", default: 0] + counts["rejection", default: 0] + counts["csp", default: 0] : 0
        finish(errors > 0 ? .pageErrors : .ok)
    }

    func callStep(_ name: String) async -> [String: Any] {
        guard let webView = webView else { return ["ok": false, "code": "no_view"] }
        let arguments: [String: Any] = ["name": name, "arg": input.seed]
        let value: Any? = await withCheckedContinuation { continuation in
            webView.callAsyncJavaScript("return await window.__uisnapRun(name, arg);", arguments: arguments,
                                        in: nil, in: .defaultClient) { result in
                switch result {
                case .success(let value): continuation.resume(returning: value)
                case .failure: continuation.resume(returning: nil)
                }
            }
        }
        guard let text = value as? String, let data = text.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data, options: []),
              let result = object as? [String: Any] else {
            return ["ok": false, "code": "step_no_result"]
        }
        return result
    }

    /// Throw one error in the page's own world and wait up to 2 s for the helper to report it.
    func probeErrors() async {
        guard let webView = webView, counts["hello", default: 0] > 0 else { return }
        let script = "setTimeout(function () { throw new Error('uisnap-probe'); }, 0); true"
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            webView.evaluateJavaScript(script, in: nil, in: .page) { _ in continuation.resume() }
        }
        let deadline = Date().addingTimeInterval(2)
        while counts["probe", default: 0] == 0 && Date() < deadline {
            try? await Task.sleep(nanoseconds: 50_000_000)
        }
    }

    func snapshot() async -> (Data, Int, Int)? {
        guard let webView = webView else { return nil }
        let configuration = WKSnapshotConfiguration()
        configuration.rect = webView.bounds
        configuration.afterScreenUpdates = true
        return await withCheckedContinuation { continuation in
            webView.takeSnapshot(with: configuration) { image, _ in
                guard let image = image,
                      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
                    continuation.resume(returning: nil)
                    return
                }
                let rep = NSBitmapImageRep(cgImage: cgImage)
                guard let png = rep.representation(using: .png, properties: [:]) else {
                    continuation.resume(returning: nil)
                    return
                }
                continuation.resume(returning: (png, cgImage.width, cgImage.height))
            }
        }
    }

    /// False (after finishing with window_onscreen) when any window of this process is on screen.
    func checkOnscreen() -> Bool {
        let count = onscreenWindows()
        maxOnscreen = max(maxOnscreen, count < 0 ? 1 : count)
        if count != 0 {
            finish(.windowOnscreen)
            return false
        }
        return true
    }

    func finish(_ exit: Exit) {
        if finished { return }
        finished = true
        var final = exit
        let count = onscreenWindows()
        maxOnscreen = max(maxOnscreen, count < 0 ? 1 : count)
        if maxOnscreen != 0 {
            final = .windowOnscreen
        }
        let collecting = counts["hello", default: 0] > 0
        var report: [String: Any] = [
            "t": "report",
            "code": final.code,
            "steps": steps,
            "checks": checks,
            "error_collection": collecting ? (counts["probe", default: 0] > 0 ? "verified" : "unverified") : "unavailable",
            "page_errors": collecting ? counts["error", default: 0] : NSNull(),
            "rejections": collecting ? counts["rejection", default: 0] : NSNull(),
            "csp_violations": collecting ? counts["csp", default: 0] : NSNull(),
            "navigations_refused": refusedNavigations,
            "onscreen_windows": maxOnscreen,
            "onscreen_samples": samples,
            "viewport": [Int(viewport.width), Int(viewport.height)],
            "scale": Int(window?.backingScaleFactor ?? 0),
            "runtime_ms": Int(Date().timeIntervalSince(started) * 1000),
        ]
        if !emit(report) {
            report = [:]
            final = .internalError
        }
        if let waiter = loadWaiter {
            loadWaiter = nil
            waiter.resume(returning: false)
        }
        Darwin.exit(final.rawValue)
    }

    // MARK: navigation (loopback only)

    func allowed(_ url: URL?) -> Bool {
        guard let url = url else { return false }
        return url.scheme == "http" && url.host == "127.0.0.1" && url.port == input.port && url.user == nil
            && url.password == nil
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
        decidedActions += 1
        if allowed(navigationAction.request.url) && navigationAction.targetFrame?.isMainFrame == true {
            decisionHandler(.allow)
            return
        }
        refusedNavigations += 1
        decisionHandler(.cancel)
        finish(.navigationRefused)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping @MainActor @Sendable (WKNavigationResponsePolicy) -> Void) {
        if navigationResponse.isForMainFrame && allowed(navigationResponse.response.url)
            && navigationResponse.canShowMIMEType {
            decisionHandler(.allow)
            return
        }
        refusedNavigations += 1
        decisionHandler(.cancel)
        finish(.navigationRefused)
    }

    func webView(_ webView: WKWebView, didReceive challenge: URLAuthenticationChallenge,
                 completionHandler: @escaping @MainActor @Sendable (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        completionHandler(.cancelAuthenticationChallenge, nil)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loaded = true
        if let waiter = loadWaiter {
            loadWaiter = nil
            waiter.resume(returning: true)
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        finish(.loadFailed)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        finish(.loadFailed)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        finish(.loadFailed)
    }

    // MARK: no panels, no windows

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        refusedNavigations += 1
        return nil
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping @MainActor @Sendable () -> Void) {
        completionHandler()
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping @MainActor @Sendable (Bool) -> Void) {
        completionHandler(false)
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping @MainActor @Sendable (String?) -> Void) {
        completionHandler(nil)
    }

    // MARK: page errors (kinds only)

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == handlerName, let kind = message.body as? String, counts[kind] != nil else { return }
        counts[kind, default: 0] += 1
    }
}

// MARK: - main

guard let input = readInput() else {
    _ = recordFD
    exit(Exit.badInput.rawValue)
}
_ = recordFD

// A hard stop that does not depend on the main thread: the report may then be missing, never the exit.
Thread.detachNewThread {
    Thread.sleep(forTimeInterval: Double(input.timeoutS + 10))
    _exit(Exit.timeout.rawValue)
}

let application = NSApplication.shared
application.setActivationPolicy(.prohibited)
let controller = MainActor.assumeIsolated { Controller(input: input) }
application.delegate = controller
application.run()
