// betangel-suite UI, Phase 0b: one synthetic market's best prices (DESIGN.md 8.2, 8.5, 8.6 item 1).
//
// Start-up: read the single-use code from the #c= fragment, strip the fragment at once with
// history.replaceState, exchange the code for a session token (POST /api/v1/bootstrap) and keep the
// token in the module variable below only: never in storage, a cookie or the URL. Then stream frames
// and render them. A 401 anywhere ends the session: "session ended, run suite open again".
//
// One controller tab (DESIGN.md 9.2 item 8): the session query says whether this tab controls the replay. A
// read-only tab shows the READ-ONLY chip and a "Take control" button (claim_control), keeps every command
// control disabled and sends no command key, but still selects runners and moves its own ladder. The role is
// asked after bootstrap, on every stream connection and every ROLE_POLL_MS, and a not_controller answer to
// any command makes the tab read-only at once.
//
// The page title is the static "betangel-suite" from index.html; nothing here ever sets it. There are
// no credential fields. In Node (the tests) this module only exports its pure parts and does not boot.

import {
  SESSION_ENDED, applyMessage, createApi, createStreamClient, createViewState, liveMsToOff, readFragmentCode,
  resetSequence,
} from './stream.js';
import { createGrid } from './grid.js';
import { createLadder, makeTickMap } from './ladder.js';
import {
  formatClockUtc, formatCountdown, formatSpeed, invalidReasonText, isSyntheticMarketId, safeCode,
} from './format.js';

// The replay speeds of DESIGN.md 6.1 (0.25x to 60x), exactly as the engine accepts them (engine.SPEEDS_X100);
// the + and - keys step through all of them, and the buttons offer 1x, 2x, 5x and 10x.
export const SPEEDS_X100 = Object.freeze([25, 50, 100, 200, 500, 1000, 3000, 6000]);

export const ACTIONS = Object.freeze([
  'toggle_play', 'speed_up', 'speed_down', 'select_prev', 'select_next', 'centre_ltp', 'stop', 'toggle_help',
]);

// The actions that send a command: a read-only tab (DESIGN.md 9.2 item 8) never sends them.
export const COMMAND_ACTIONS = Object.freeze(['toggle_play', 'speed_up', 'speed_down', 'stop']);

// How often a tab asks whether it is still the controller (another tab may have claimed control).
export const ROLE_POLL_MS = 2000;

// Whether a key's action runs: help always; nothing else once the session ended; no command while read-only.
export function actionAllowed(action, state) {
  if (action === 'toggle_help') {
    return true;
  }
  if (state.ended) {
    return false;
  }
  return !(state.readOnly && COMMAND_ACTIONS.includes(action));
}

// DESIGN.md 8.3, the Phase 0b subset. Keys are KeyboardEvent.key values; a key maps to one action.
export const KEYMAP = Object.freeze([
  Object.freeze({ key: ' ', action: 'toggle_play', label: 'Space', help: 'play or pause' }),
  Object.freeze({ key: '+', action: 'speed_up', label: '+', help: 'faster' }),
  Object.freeze({ key: '=', action: 'speed_up', label: '=', help: 'faster (unshifted +)' }),
  Object.freeze({ key: '-', action: 'speed_down', label: '-', help: 'slower' }),
  Object.freeze({ key: 'ArrowUp', action: 'select_prev', label: 'Up', help: 'previous runner' }),
  Object.freeze({ key: 'ArrowDown', action: 'select_next', label: 'Down', help: 'next runner' }),
  Object.freeze({ key: 'l', action: 'centre_ltp', label: 'L', help: 'centre the ladder on the LTP' }),
  Object.freeze({ key: 'L', action: 'centre_ltp', label: 'Shift+L', help: 'centre the ladder on the LTP' }),
  Object.freeze({ key: 'q', action: 'stop', label: 'Q', help: 'STOP (paper)' }),
  Object.freeze({ key: 'Q', action: 'stop', label: 'Shift+Q', help: 'STOP (paper)' }),
  Object.freeze({ key: '?', action: 'toggle_help', label: '?', help: 'show or hide this list' }),
]);

const KEY_INDEX = new Map(KEYMAP.map((entry) => [entry.key, entry.action]));

// The action for a keydown, or null. Keys with Ctrl, Cmd or Alt belong to the browser.
export function keyAction(event) {
  if (event.ctrlKey || event.metaKey || event.altKey) {
    return null;
  }
  const action = KEY_INDEX.get(event.key);
  return action === undefined ? null : action;
}

// The next listed speed above the current one (direction > 0) or below it (direction < 0); the current speed
// itself at either end, so a step never goes the wrong way, whatever speed the engine reports.
export function nextSpeed(current, direction) {
  let found = current;
  if (direction > 0) {
    for (let i = SPEEDS_X100.length - 1; i >= 0; i -= 1) {
      if (SPEEDS_X100[i] > current) {
        found = SPEEDS_X100[i];
      }
    }
  } else {
    for (let i = 0; i < SPEEDS_X100.length; i += 1) {
      if (SPEEDS_X100[i] < current) {
        found = SPEEDS_X100[i];
      }
    }
  }
  return found;
}

// A seed typed in the box: 1 to 9 digits, or null.
export function parseSeed(text) {
  if (typeof text !== 'string') {
    return null;
  }
  const trimmed = text.trim();
  return /^[0-9]{1,9}$/.test(trimmed) ? Number(trimmed) : null;
}

// The runner to select after a frame: the current one if still there, else the first active one.
export function chooseRunner(runners, currentId) {
  if (runners.some((runner) => runner.id === currentId)) {
    return currentId;
  }
  const active = runners.find((runner) => runner.status === 'ACTIVE');
  if (active !== undefined) {
    return active.id;
  }
  return runners.length > 0 ? runners[0].id : null;
}

// The runner step positions away from currentId, in grid order, clamped at the ends.
export function stepRunner(runners, currentId, step) {
  if (runners.length === 0) {
    return null;
  }
  const at = runners.findIndex((runner) => runner.id === currentId);
  if (at === -1) {
    return runners[0].id;
  }
  const next = at + step;
  return runners[next < 0 ? 0 : next >= runners.length ? runners.length - 1 : next].id;
}

// One handler per ACTIONS entry; ctx supplies the operations (app state in the browser, stubs in tests).
export function makeHandlers(ctx) {
  return {
    toggle_play: () => ctx.togglePlay(),
    speed_up: () => ctx.setSpeed(nextSpeed(ctx.currentSpeed(), 1)),
    speed_down: () => ctx.setSpeed(nextSpeed(ctx.currentSpeed(), -1)),
    select_prev: () => ctx.selectStep(-1),
    select_next: () => ctx.selectStep(1),
    centre_ltp: () => ctx.centreLadder(),
    stop: () => ctx.stop(),
    toggle_help: () => ctx.toggleHelp(),
  };
}

// The stream's connection state as shown. Never the word "live": LIVE is reserved as a data-source label
// (DESIGN.md 8.4), and this page only ever replays.
export const CONNECTION_TEXT = Object.freeze({
  connecting: 'connecting',
  connected: 'connected',
  reconnecting: 'reconnecting',
  session_ended: SESSION_ENDED,
});

// --- the browser application -------------------------------------------------------------------------

let sessionToken = null;            // the session token: JS memory only (DESIGN.md 9.2 item 1)

function boot() {
  const code = readFragmentCode(window.location.hash);
  if (window.location.hash !== '') {
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
  }

  const $ = (id) => document.getElementById(id);
  const ui = {
    syntheticBadge: $('badge-synthetic'), marketName: $('market-name'), marketStatus: $('market-status'),
    inplay: $('badge-inplay'), invalid: $('invalid'), countdown: $('countdown'), clock: $('clock'),
    pausedReason: $('paused-reason'), play: $('play'), seed: $('seed'), open: $('open'), stop: $('stop'),
    helpToggle: $('help-toggle'), help: $('help'), helpList: $('help-list'), conn: $('conn'), note: $('note'),
    role: $('role'), claim: $('claim'),
    gridBody: $('grid-body'), ladderRunner: $('ladder-runner'), ladderCanvas: $('ladder'),
    speeds: Array.from(document.querySelectorAll('button.speed')),
  };
  const controls = [ui.play, ui.seed, ui.open, ui.stop, ...ui.speeds];

  const view = createViewState();
  let selectedId = null;
  let marketId = null;
  let drawnRev = -1;
  let ladder = null;
  let renderQueued = false;
  let countdownText = '';
  let countdownLevel = '';
  let stream = null;
  let ended = false;
  let controller = null;            // null until the engine says; then whether this tab controls the replay
  let roleAsked = false;

  const setText = (node, text) => {
    if (node.textContent !== text) {
      node.textContent = text;
    }
  };
  const setNote = (text) => setText(ui.note, text);
  const setEnabled = (on) => controls.forEach((node) => {
    node.disabled = !on;
  });

  // The controller role (DESIGN.md 9.2 item 8): command controls only for the controller tab.
  function applyRole(isController) {
    controller = isController;
    const readOnly = !ended && controller === false;
    ui.role.hidden = !readOnly;
    ui.claim.hidden = !readOnly;
    ui.claim.disabled = !readOnly;
    setEnabled(!ended && sessionToken !== null && !readOnly);
  }

  function endSession() {
    ended = true;
    sessionToken = null;
    if (stream !== null) {
      stream.stop();
    }
    applyRole(controller);
    setText(ui.conn, SESSION_ENDED);
    ui.conn.classList.add('ended');
  }

  const api = createApi({
    fetchImpl: (url, init) => window.fetch(url, init),
    getToken: () => sessionToken,
    onUnauthorized: endSession,
    fillRandom: (bytes) => window.crypto.getRandomValues(bytes),
  });

  async function send(name, args) {
    if (ended) {
      return;
    }
    const result = await api.command(name, args);
    if (!ended) {
      if (!result.ok && result.code === 'not_controller') {
        applyRole(false);                       // another tab claimed control
      }
      setNote(result.ok ? name + ': ok' : name + ': ' + safeCode(result.code));
    }
  }

  // Ask the engine whether this tab is the controller (one query at a time).
  async function refreshRole() {
    if (ended || sessionToken === null || roleAsked) {
      return;
    }
    roleAsked = true;
    try {
      const result = await api.query('session');
      if (!ended && result.ok && typeof result.reply.controller === 'boolean') {
        applyRole(result.reply.controller);
      }
    } finally {
      roleAsked = false;
    }
  }

  async function claimControl() {
    if (ended || controller !== false) {
      return;
    }
    ui.claim.disabled = true;
    const result = await api.command('claim_control', {});
    if (ended) {
      return;
    }
    setNote(result.ok ? 'claim_control: ok' : 'claim_control: ' + safeCode(result.code));
    applyRole(result.ok ? true : controller);
    refreshRole();
  }

  const grid = createGrid(ui.gridBody, document, {
    onSelect: (id) => {
      selectedId = id;
      if (ladder !== null) {
        ladder.show(selectedRunner(), { recentre: true });
      }
      drawnRev = -1;
      scheduleRender();
    },
  });

  function runners() {
    return view.frame === null ? [] : view.frame.runners;
  }

  function selectedRunner() {
    return runners().find((runner) => runner.id === selectedId) || null;
  }

  function currentSpeed() {
    return view.frame === null ? 100 : view.frame.clock.speed_x100;
  }

  const handlers = makeHandlers({
    togglePlay: () => send(view.paused ? 'play' : 'pause', {}),
    currentSpeed: currentSpeed,
    setSpeed: (speed) => send('set_speed', { speed_x100: speed }),
    selectStep: (step) => {
      selectedId = stepRunner(runners(), selectedId, step);
      if (ladder !== null) {
        ladder.show(selectedRunner(), { recentre: true });
      }
      drawnRev = -1;
      scheduleRender();
    },
    centreLadder: () => {
      if (ladder !== null) {
        ladder.centreOnLtp();
        scheduleRender();
      }
    },
    stop: () => send('stop', {}),
    toggleHelp: () => {
      ui.help.hidden = !ui.help.hidden;
      ui.helpToggle.setAttribute('aria-expanded', ui.help.hidden ? 'false' : 'true');
    },
  });

  function renderHeader(frame) {
    const synthetic = frame === null || isSyntheticMarketId(frame.market.id);
    setText(ui.syntheticBadge, synthetic ? 'SYNTHETIC DATA' : 'DATA NOT SYNTHETIC');
    ui.syntheticBadge.classList.toggle('warn', !synthetic);
    setText(ui.marketName, frame === null ? 'No market open: enter a seed and open a synthetic market' : frame.market.name);
    ui.marketStatus.hidden = frame === null;
    if (frame !== null) {
      setText(ui.marketStatus, frame.market.status);
      ui.marketStatus.dataset.status = frame.market.status;
    }
    ui.inplay.hidden = frame === null || !frame.market.inplay;
    const invalid = frame === null ? '' : invalidReasonText(frame.market.invalid_reason);
    ui.invalid.hidden = invalid === '';
    setText(ui.invalid, invalid);
    setText(ui.play, view.paused ? 'Play' : 'Pause');
    ui.play.setAttribute('aria-pressed', view.paused ? 'false' : 'true');
    const speed = frame === null ? null : frame.clock.speed_x100;
    ui.speeds.forEach((button) => {
      button.setAttribute('aria-pressed', Number(button.dataset.speed) === speed ? 'true' : 'false');
    });
    setText(ui.clock, frame === null ? 'replay --:--:-- UTC'
      : 'replay ' + formatClockUtc(frame.clock.pt) + ' UTC, ' + formatSpeed(frame.clock.speed_x100));
    const reason = frame === null || !view.paused || frame.clock.pause_reason === null
      ? '' : 'paused: ' + safeCode(frame.clock.pause_reason);
    ui.pausedReason.hidden = reason === '';
    setText(ui.pausedReason, reason);
    if (view.ended !== null) {
      setNote('stream ended: ' + safeCode(view.ended));
    }
  }

  function renderCountdown() {
    const frame = view.frame;
    const shown = formatCountdown(liveMsToOff(view, window.performance.now()), frame !== null && frame.market.inplay);
    if (shown.text !== countdownText) {
      countdownText = shown.text;
      ui.countdown.textContent = shown.text;
    }
    if (shown.level !== countdownLevel) {
      ui.countdown.classList.remove('level-' + countdownLevel);
      ui.countdown.classList.add('level-' + shown.level);
      countdownLevel = shown.level;
    }
  }

  function render() {
    renderQueued = false;
    if (drawnRev !== view.rev) {
      drawnRev = view.rev;
      const frame = view.frame;
      const newMarket = frame !== null && frame.market.id !== marketId;
      if (newMarket) {
        marketId = frame.market.id;
        selectedId = null;
      }
      selectedId = chooseRunner(runners(), selectedId);
      renderHeader(frame);
      grid.update(runners(), selectedId);
      const runner = selectedRunner();
      setText(ui.ladderRunner, runner === null ? 'No runner selected' : runner.name);
      if (ladder !== null) {
        ladder.show(runner, { recentre: newMarket });      // runner ids may repeat across markets
      }
      renderCountdown();
    }
    if (ladder !== null) {
      ladder.draw();
    }
  }

  function scheduleRender() {
    if (!renderQueued) {
      renderQueued = true;
      window.requestAnimationFrame(render);
    }
  }

  // Controls.
  ui.play.addEventListener('click', () => handlers.toggle_play());
  ui.speeds.forEach((button) => button.addEventListener('click', () => {
    const speed = Number(button.dataset.speed);
    if (SPEEDS_X100.includes(speed)) {
      send('set_speed', { speed_x100: speed });
    }
  }));
  ui.open.addEventListener('click', () => {
    const seed = parseSeed(ui.seed.value);
    if (seed === null) {
      setNote('the seed must be a whole number of up to 9 digits');
      return;
    }
    send('open_market', { seed: seed });
  });
  ui.stop.addEventListener('click', () => handlers.stop());
  ui.claim.addEventListener('click', () => claimControl());
  ui.helpToggle.addEventListener('click', () => handlers.toggle_help());
  ui.helpList.replaceChildren(...KEYMAP.map((entry) => {
    const item = document.createElement('li');
    const key = document.createElement('kbd');
    key.textContent = entry.label;
    item.append(key, ' ' + entry.help);
    return item;
  }));

  document.addEventListener('keydown', (event) => {
    const target = event.target;
    const tag = target && target.tagName ? target.tagName : '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (target && target.isContentEditable)) {
      return;                                   // typing in the seed box
    }
    if (tag === 'BUTTON' && (event.key === ' ' || event.key === 'Enter')) {
      return;                                   // a focused button handles its own activation
    }
    const action = keyAction(event);
    if (action === null || !actionAllowed(action, { ended: ended, readOnly: controller === false })) {
      return;
    }
    event.preventDefault();
    handlers[action]();
  });

  ui.ladderCanvas.addEventListener('wheel', (event) => {
    if (ladder !== null && event.deltaY !== 0) {
      event.preventDefault();
      ladder.scroll(event.deltaY < 0 ? 1 : -1);
      scheduleRender();
    }
  }, { passive: false });

  // Pause unless watched (DESIGN.md 8.6, I-19): while the page is hidden, a running clock asks the engine to
  // pause, on hiding and again on any later message that shows it running (a Play accepted just before the
  // page was hidden, or a pause that did not get through). One request at a time; a tab answered
  // not_controller turns read-only (DESIGN.md 9.2 item 8) and stops asking until it is shown again, and a
  // read-only tab never asks. Called from onMessage, not render: a hidden page gets no animation frames.
  let hiddenPause = 'idle';                     // idle, sending or refused
  function pauseIfHidden() {
    if (document.visibilityState !== 'hidden') {
      hiddenPause = 'idle';
      return;
    }
    if (hiddenPause !== 'idle' || ended || sessionToken === null || view.frame === null || view.paused
        || controller === false) {
      return;
    }
    hiddenPause = 'sending';
    api.command('pause', {}).then((result) => {
      hiddenPause = !result.ok && result.code === 'not_controller' && document.visibilityState === 'hidden'
        ? 'refused' : 'idle';
      if (!ended) {
        if (!result.ok && result.code === 'not_controller') {
          applyRole(false);                     // another tab claimed control
        }
        setNote(result.ok ? 'pause: ok' : 'pause: ' + safeCode(result.code));
      }
    });
  }
  document.addEventListener('visibilitychange', pauseIfHidden);

  window.setInterval(renderCountdown, 100);
  setEnabled(false);
  renderHeader(null);
  renderCountdown();

  // The tick ladder (a static file listed in the manifest; no token needed).
  window.fetch('/ticks.json', { cache: 'no-store', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer' })
    .then((response) => (response.ok ? response.json() : Promise.reject(new Error('ticks'))))
    .then((doc) => {
      const css = window.getComputedStyle(document.documentElement);
      const read = (name) => css.getPropertyValue(name).trim();
      const readPalette = () => {
        const palette = {};
        for (const [key, name] of [['background', '--ladder-bg'], ['grid', '--ladder-grid'], ['text', '--text'],
          ['muted', '--muted'], ['back', '--back'], ['backBest', '--back-best'], ['lay', '--lay'],
          ['layBest', '--lay-best'], ['ltp', '--ltp']]) {
          const value = read(name);
          if (value !== '') {
            palette[key] = value;
          }
        }
        return palette;
      };
      const ratio = Math.round(window.devicePixelRatio || 1);
      ladder = createLadder(ui.ladderCanvas, makeTickMap(doc), { readPalette: readPalette, dpr: ratio < 1 ? 1 : ratio });
      ladder.show(selectedRunner(), { recentre: true });
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        ladder.invalidate();
        scheduleRender();
      });
      scheduleRender();
    })
    .catch(() => setNote('ladder unavailable: ticks_unavailable'));

  if (code === null) {
    ended = true;
    setText(ui.conn, 'no session code, run suite open again');
    ui.conn.classList.add('ended');
    return;
  }
  setText(ui.conn, 'starting session');
  api.bootstrap(code).then((result) => {
    if (!result.ok) {
      endSession();
      return;
    }
    sessionToken = result.token;
    applyRole(controller);
    refreshRole();
    window.setInterval(refreshRole, ROLE_POLL_MS);
    stream = createStreamClient({
      fetchImpl: (url, init) => window.fetch(url, init),
      getToken: () => sessionToken,
      onConnect: () => {
        resetSequence(view);
        refreshRole();
      },
      onMessage: (msg) => {
        if (applyMessage(view, msg, window.performance.now())) {
          scheduleRender();
        }
        pauseIfHidden();                        // every message, a heartbeat included
      },
      onStatus: (status) => {
        if (!ended) {
          setText(ui.conn, CONNECTION_TEXT[status] || 'stream error ' + safeCode(status));
        }
      },
      onUnauthorized: endSession,
    });
    stream.start();
  });
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  boot();
}
