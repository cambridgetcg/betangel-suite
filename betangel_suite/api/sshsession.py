"""bin/suite ssh-session: the viewer's terminal side of pause-unless-watched (DESIGN.md 8.6 item 2, I-19).

ssh-session runs only as the viewer key's forced command: bin/suite refuses it outside SSH and with a requested
command, and cli.py refuses it unless bin/suite passed SUITE_VIA_SSH=1. It writes to its own stdout only (the
SSH channel), never to a log, and nothing else ever prints a code:

    http://127.0.0.1:<port>/#c=<code>     once at the start, and again for every Enter on stdin (a fresh code)
    heartbeat <h:mm:ss>                   every HEARTBEAT_S (15 s), the time since this viewer attached
    ended reason=<code>                   when the viewer's part ends: superseded, engine_gone, or the engine's
                                          own end reason (stopped, abandoned, max_session, ...)

Two ways to run, both driven by Viewer:

- **The engine here.** With no engine running, server.run starts the synthetic engine on the config port in
  this process and Viewer talks to it directly (LocalLink). The process lives as long as the engine does.
- **Attached.** With an engine running (lock held), Viewer takes it over through the control socket
  (ControlLink: attach_viewer, viewer_code, viewer_heartbeat, viewer_away) and this process exits as soon as its
  viewer is away, superseded or the engine has gone; the engine keeps the session itself (api/lifetime.py).

Either way: each takeover pauses the clock, invalidates every earlier code and token and issues a fresh code.
stdin EOF, SIGHUP or a failed stdout write makes the viewer away: the engine pauses and keeps the session for
watch_grace_s; a new ssh-session or open within it takes over; after it, with no tab connected, the engine
ends the session as abandoned. Enter presses are coalesced (one code per poll however many arrive), and
input is read in bounded pieces and never echoed or kept.

stdin, stdout, the clock, the sleep and the heartbeat period are injectable, so tests drive all of this in
process (Viewer and Terminal with fake links and clocks) and in engine-mode children with tiny values, never
through bin/suite against the real HOME. Standard library only.
"""

import os
import signal
import sys
import threading
import time

from .. import guard
from ..errors import SuiteError
from . import auth as auth_module
from . import control

HEARTBEAT_S = 15.0
POLL_S = 0.25
MAX_INPUT_BYTES = 1024
ACTIVE, AWAY, SUPERSEDED, GONE = "active", "away", "superseded", "engine_gone"
EXIT_OK = 0


def url_line(port, code):
    return "http://127.0.0.1:%d/#c=%s\n" % (port, code)


def heartbeat_line(elapsed_s):
    seconds = max(0, int(elapsed_s))
    return "heartbeat %d:%02d:%02d\n" % (seconds // 3600, seconds // 60 % 60, seconds % 60)


def end_line(reason):
    return "ended reason=%s\n" % SuiteError(reason).code


class Terminal:
    """The viewer's stdin (Enter presses and EOF, read on a daemon thread) and stdout (lines; a failure is kept).

    stdin is a binary or text stream with readline(limit); None counts as EOF at once. stdout is a text stream.
    """

    def __init__(self, stdin, stdout, *, on_fail=None):
        self._stdin = stdin
        self._out = stdout
        self._on_fail = on_fail
        self._lock = threading.Lock()
        self._presses = 0
        self._eof = stdin is None
        self._thread = None
        self.failed = False
        self.hangup = False                     # SIGHUP: as stdin EOF

    def start(self):
        if self._thread is None and self._stdin is not None:
            self._thread = threading.Thread(target=self._read, name="suite-viewer-stdin", daemon=True)
            self._thread.start()

    def _read(self):
        while True:
            try:
                data = self._stdin.readline(MAX_INPUT_BYTES)
            except (OSError, ValueError):
                data = b""
            if not data:
                break
            if data.endswith(b"\n" if isinstance(data, bytes) else "\n"):
                with self._lock:
                    self._presses += 1
        with self._lock:
            self._eof = True

    def take(self):
        """(Enter presses since the last call, whether the viewer has gone: stdin EOF or a hangup)."""
        with self._lock:
            presses, self._presses = self._presses, 0
            return presses, self._eof or self.hangup

    def write(self, text):
        """Write one line and flush; False (and failed from then on) when the write fails."""
        if self.failed:
            return False
        try:
            self._out.write(text)
            self._out.flush()
            return True
        except (OSError, ValueError):
            self.failed = True
            if self._on_fail is not None:
                self._on_fail()
            return False


class Viewer:
    """One ssh-session viewer: the start URL, a fresh URL per Enter, heartbeats, and going away."""

    def __init__(self, link, terminal, *, clock=time.monotonic, heartbeat_s=HEARTBEAT_S):
        self._link = link
        self._terminal = terminal
        self._clock = clock
        self._heartbeat_s = heartbeat_s
        self.state = ACTIVE
        self.generation = None
        self._started = self._next = None

    def attach(self):
        """Take the session over and print its URL; SuiteError when the engine refuses or cannot be reached."""
        port, code, self.generation = self._link.attach()
        self._started = self._clock()
        self._next = self._started + self._heartbeat_s
        if not self._terminal.write(url_line(port, code)):
            self._go_away()
        return self.state

    def step(self):
        """One poll: Enter presses, EOF or hangup, a write failure, the heartbeat. Returns the state."""
        if self.state != ACTIVE:
            return self.state
        presses, gone = self._terminal.take()
        if gone or self._terminal.failed:
            return self._go_away()
        if presses:
            reply = self._link.code(self.generation)
            if not self._answer(reply):
                return self.state
            if not self._terminal.write(url_line(*reply)):
                return self._go_away()
        now = self._clock()
        if now >= self._next:
            self._next = now + self._heartbeat_s
            if not self._terminal.write(heartbeat_line(now - self._started)):
                return self._go_away()
            self._answer(self._link.heartbeat(self.generation))
        return self.state

    def _answer(self, reply):
        """False (and the state changed, its end line written) when reply says superseded or the engine is gone."""
        if reply == SUPERSEDED or reply is None:
            self.state = SUPERSEDED if reply == SUPERSEDED else GONE
            self._terminal.write(end_line(self.state))
            return False
        return True

    def _go_away(self):
        self.state = AWAY
        if self.generation is not None:
            self._link.away(self.generation)     # superseded or gone: nothing more to do either way
        return self.state


class LocalLink:
    """The engine in this process (server.run started it for ssh-session)."""

    def __init__(self, app):
        self._app = app

    def attach(self):
        return self._app.takeover(terminal=True)

    def code(self, generation):
        if self._app.stopping.is_set():
            return None
        code = self._app.viewer_code(generation)
        return SUPERSEDED if code is None else (self._app.port, code)

    def heartbeat(self, generation):
        if self._app.stopping.is_set():
            return None
        return True if self._app.viewer_heartbeat(generation) else SUPERSEDED

    def away(self, generation):
        return True if self._app.viewer_away(generation) else SUPERSEDED


class ControlLink:
    """A running engine, reached through its control socket (same uid; api/control.py)."""

    def __init__(self, home_dir=None):
        self._home = home_dir

    def attach(self):
        reply = control.request("attach_viewer", self._home)
        if reply is None:
            raise SuiteError("control_unavailable")
        port, code, viewer = reply.get("port"), reply.get("code"), reply.get("viewer")
        if not reply.get("ok") or not _port_ok(port) or not _code_ok(code) or not _viewer_ok(viewer):
            raise SuiteError("control_failed")
        return port, code, viewer

    def code(self, generation):
        reply = self._ask("viewer_code", generation)
        if reply is None or reply == SUPERSEDED:
            return reply
        port, code = reply.get("port"), reply.get("code")
        return (port, code) if _port_ok(port) and _code_ok(code) else None

    def heartbeat(self, generation):
        reply = self._ask("viewer_heartbeat", generation)
        return True if isinstance(reply, dict) else reply

    def away(self, generation):
        reply = self._ask("viewer_away", generation)
        return True if isinstance(reply, dict) else reply

    def _ask(self, command, generation):
        """The ok reply dict, SUPERSEDED, or None when the engine has gone (or answers nonsense)."""
        try:
            reply = control.request(command, self._home, args={"viewer": generation})
        except SuiteError as exc:
            if exc.code not in ("control_unavailable", "control_failed"):
                raise
            return None
        if reply is None:
            return None
        if reply.get("ok") is True:
            return reply
        return SUPERSEDED if reply.get("code") == "superseded" else None


def _port_ok(port):
    return type(port) is int and 0 < port <= 65535


def _code_ok(code):
    return isinstance(code, str) and bool(auth_module.CODE_RE.fullmatch(code))


def _viewer_ok(viewer):
    return type(viewer) is int and viewer > 0


class Session:
    """What server.run needs for ssh-session: the viewer in the engine's own process, or attached to another."""

    def __init__(self, stdin, stdout, *, clock=time.monotonic, sleep=time.sleep, heartbeat_s=HEARTBEAT_S,
                 poll_s=POLL_S, home_dir=None, on_fail=None):
        self.terminal = Terminal(stdin, stdout, on_fail=on_fail)
        self._clock = clock
        self._sleep = sleep
        self._heartbeat_s = heartbeat_s
        self.poll_s = poll_s
        self._home = home_dir
        self.viewer = None

    # --- the engine in this process (server.run calls these) ----------------------------------------

    def start_local(self, app):
        """After seal(): take the new engine's session over and print the first URL."""
        self.viewer = Viewer(LocalLink(app), self.terminal, clock=self._clock, heartbeat_s=self._heartbeat_s)
        self.viewer.attach()
        self.terminal.start()

    def step(self):
        if self.viewer is not None:
            self.viewer.step()

    def hangup(self):
        self.terminal.hangup = True

    def finish(self, reason):
        """The engine ended: tell the viewer why, if it is still here or only away (stdin EOF: Yu may still see the
        SSH window, which then shows that the session ended, abandoned say). A superseded viewer has had its own end
        line, and a terminal whose write failed takes no more (Terminal.write)."""
        if self.viewer is not None and self.viewer.state in (ACTIVE, AWAY):
            self.terminal.write(end_line(reason))

    # --- attached to an engine in another process ---------------------------------------------------

    def run_attached(self):
        """Take a running engine over through the control socket, then serve the viewer until it is done."""
        self.viewer = Viewer(ControlLink(self._home), self.terminal, clock=self._clock, heartbeat_s=self._heartbeat_s)
        self.viewer.attach()                    # the control connect is permitted here, before the seal
        guard.seal()
        self._install_signal_handlers()
        self.terminal.start()
        while self.viewer.step() == ACTIVE:
            self._sleep(self.poll_s)
        return EXIT_OK

    def _install_signal_handlers(self):
        if threading.current_thread() is not threading.main_thread():
            return

        def handler(signum, frame):
            self.hangup()                       # the viewer leaves; the engine keeps the session for the grace

        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(signum, handler)


def main(cfg, *, port=None, stdin=None, stdout=None, home_dir=None, **options):
    """bin/suite ssh-session: the engine here, or attached to the running one. Returns the exit status.

    options go to Session (clock, sleep, heartbeat_s, poll_s) or to server.run (the test seams).
    """
    from . import server            # here, not at the top: server.run takes a Session, it never imports this module
    session_keys = ("clock", "sleep", "heartbeat_s", "poll_s")
    session = Session(_stdin() if stdin is None else stdin, sys.stdout if stdout is None else stdout,
                      home_dir=home_dir, on_fail=_silence_stdout if stdout is None else None,
                      **{key: options.pop(key) for key in session_keys if key in options})
    return server.run(cfg, command="ssh-session", port=cfg["port"] if port is None else port, session=session,
                      home_dir=home_dir, **options)


class FdReader:
    """readline(limit) on a file descriptor through os.read alone. sys.stdin's buffered reader would hold its lock
    in the reader thread's blocked read, and interpreter shutdown would then abort on that lock."""

    def __init__(self, fd):
        self._fd = fd
        self._buffer = b""

    def readline(self, limit):
        while b"\n" not in self._buffer and len(self._buffer) < limit:
            data = os.read(self._fd, limit)
            if not data:
                break
            self._buffer += data
        end = self._buffer.find(b"\n")
        cut = limit if end < 0 or end >= limit else end + 1
        line, self._buffer = self._buffer[:cut], self._buffer[cut:]
        return line


def _stdin():
    return None if sys.stdin is None else FdReader(0)


def _silence_stdout():
    """After a failed write to the real stdout (the SSH channel has gone): point fd 1 at /dev/null, so what is still
    buffered there is discarded at exit instead of raising again (no "Exception ignored" lines on stderr)."""
    try:
        fd = os.open(os.devnull, os.O_WRONLY | os.O_CLOEXEC)
    except OSError:
        return
    try:
        os.dup2(fd, sys.stdout.fileno(), inheritable=False)
    except (OSError, ValueError, AttributeError):
        pass
    finally:
        os.close(fd)
