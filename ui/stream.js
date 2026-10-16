// The engine connection: bootstrap, commands, and the NDJSON frame stream (DESIGN.md 8.5, 9.1-9.2).
//
// - The session token lives only in the caller's memory (app.js keeps it in a module variable); it is
//   passed in through getToken() and never written to storage, cookies or the URL.
// - Every request is same-origin, carries no cookies, follows no redirect and sends no referrer.
// - The stream is read with fetch() and an NDJSON line parser, because server-sent events cannot send the
//   Authorization header. It reconnects with capped backoff while the token is valid; a 401 ends the
//   session for good.
// - Messages are validated before they reach the view: money and prices must be integers.

export const ROUTES = Object.freeze({
  bootstrap: '/api/v1/bootstrap',
  stream: '/api/v1/stream',
  query: '/api/v1/query',
  command: '/api/v1/command',
});

// DESIGN.md 9.1, the closed command enum (exploration mode's replace is not part of the MVP enum).
export const COMMANDS = Object.freeze([
  'open_market', 'play', 'pause', 'set_speed', 'seek', 'jump', 'step', 'subscribe', 'claim_control',
  'place', 'cancel', 'cancel_side', 'cancel_all', 'stop', 'resume', 'void_and_rewind', 'report_problem',
  'set_prefs', 'export_csv',
]);

// DESIGN.md 9.1, the read-only queries (only session is answered in Phase 0).
export const QUERIES = Object.freeze(['session', 'catalogue', 'journal', 'green_up_preview']);

export const SESSION_ENDED = 'session ended, run suite open again';

const TOKEN_RE = /^[A-Za-z0-9_-]{16,256}$/;
const CODE_RE = /^[A-Za-z0-9_-]{1,128}$/;
const REPLY_CODE_RE = /^[a-z][a-z0-9_]{0,63}$/;

// --- NDJSON -----------------------------------------------------------------------------------------

export const MAX_LINE_CHARS = 1 << 20;

// Splits a byte or text stream into JSON values, one per "\n"-terminated line. A chunk may end in the
// middle of a line or of a UTF-8 sequence; the remainder waits for the next chunk. Blank lines are
// skipped, a trailing "\r" is dropped, a line that is not JSON is counted and skipped, and a line
// longer than MAX_LINE_CHARS is discarded up to its newline. An unterminated line at the end of the
// stream is incomplete and is dropped, never parsed.
export class NdjsonParser {
  constructor(maxLineChars = MAX_LINE_CHARS) {
    this.maxLineChars = maxLineChars;
    this.decoder = new TextDecoder('utf-8');
    this.buffer = '';
    this.discarding = false;
    this.badLines = 0;
    this.longLines = 0;
    this.droppedPartial = 0;
  }

  push(chunk) {
    const text = typeof chunk === 'string' ? chunk : this.decoder.decode(chunk, { stream: true });
    const out = [];
    let start = 0;
    for (;;) {
      const newline = text.indexOf('\n', start);
      if (newline === -1) {
        break;
      }
      this.takeLine(this.buffer + text.slice(start, newline), out);
      this.buffer = '';
      start = newline + 1;
    }
    if (!this.discarding) {
      this.buffer += text.slice(start);
      if (this.buffer.length > this.maxLineChars) {
        this.buffer = '';
        this.discarding = true;
        this.longLines += 1;
      }
    }
    return out;
  }

  takeLine(line, out) {
    if (this.discarding) {
      this.discarding = false;
      return;
    }
    if (line.endsWith('\r')) {
      line = line.slice(0, -1);
    }
    if (line.length > this.maxLineChars) {
      this.longLines += 1;
      return;
    }
    if (line.trim() === '') {
      return;
    }
    try {
      out.push(JSON.parse(line));
    } catch (error) {
      this.badLines += 1;
    }
  }

  // End of stream: anything still buffered was never terminated.
  finish() {
    const rest = this.buffer + this.decoder.decode();
    if (rest.trim() !== '' || this.discarding) {
      this.droppedPartial += 1;
    }
    this.buffer = '';
    this.discarding = false;
  }
}

// --- backoff ----------------------------------------------------------------------------------------

export const BACKOFF = Object.freeze({ baseMs: 250, capMs: 8000 });

// The wait before reconnect attempt n (0-based): 250, 500, 1000, ... capped at 8 s. Integer ms.
export function backoffDelay(attempt, base = BACKOFF.baseMs, cap = BACKOFF.capMs) {
  if (!Number.isSafeInteger(attempt) || attempt < 0) {
    throw new RangeError('attempt must be a non-negative integer');
  }
  let delay = base;
  for (let i = 0; i < attempt && delay < cap; i += 1) {
    delay *= 2;
  }
  return delay < cap ? delay : cap;
}

// --- message validation -----------------------------------------------------------------------------

const isInt = Number.isSafeInteger;

function isIntOrNull(value) {
  return value === null || isInt(value);
}

function isText(value, max) {
  return typeof value === 'string' && value.length <= max;
}

function isTextOrNull(value, max) {
  return value === null || isText(value, max);
}

// Every listed key is present. Keys the UI does not know are ignored, so a later engine can add fields
// without blanking the screen; every known field is still type-checked.
function hasKeys(value, keys) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }
  return keys.every((key) => Object.prototype.hasOwnProperty.call(value, key));
}

function isLevels(levels) {
  return Array.isArray(levels) && levels.length <= 3 && levels.every((level) =>
    Array.isArray(level) && level.length === 2 && isInt(level[0]) && level[0] > 0 && isInt(level[1])
    && level[1] >= 0);
}

const FRAME_KEYS = ['t', 'seq', 'clock', 'market', 'runners'];
const CLOCK_KEYS = ['pt', 'speed_x100', 'paused', 'pause_reason', 'ms_to_off'];
const MARKET_KEYS = ['id', 'name', 'status', 'inplay', 'version', 'invalid_reason'];
const RUNNER_KEYS = ['id', 'name', 'status', 'ltp_h', 'tv_p', 'back', 'lay'];
export const MAX_RUNNERS = 400;

function clockOk(clock) {
  return hasKeys(clock, CLOCK_KEYS) && isInt(clock.pt) && clock.pt >= 0 && isInt(clock.speed_x100)
    && clock.speed_x100 > 0 && typeof clock.paused === 'boolean' && isTextOrNull(clock.pause_reason, 64)
    && isIntOrNull(clock.ms_to_off);
}

function marketOk(market) {
  return hasKeys(market, MARKET_KEYS) && isText(market.id, 32) && isText(market.name, 200)
    && isText(market.status, 32) && typeof market.inplay === 'boolean' && isInt(market.version)
    && isTextOrNull(market.invalid_reason, 64);
}

function runnerOk(runner) {
  return hasKeys(runner, RUNNER_KEYS) && isInt(runner.id) && isText(runner.name, 200)
    && isText(runner.status, 32) && isIntOrNull(runner.ltp_h) && (runner.ltp_h === null || runner.ltp_h > 0)
    && isInt(runner.tv_p) && runner.tv_p >= 0 && isLevels(runner.back) && isLevels(runner.lay);
}

// null when msg is a well-formed stream message, else a code. Unknown message types are "unknown_type"
// (ignored by the view, so a later engine can add types).
export function validateMessage(msg) {
  if (msg === null || typeof msg !== 'object' || Array.isArray(msg)) {
    return 'bad_message';
  }
  if (!isInt(msg.seq) || msg.seq < 0) {
    return 'bad_seq';
  }
  if (msg.t === 'frame') {
    if (!hasKeys(msg, FRAME_KEYS) || !clockOk(msg.clock) || !marketOk(msg.market)
        || !Array.isArray(msg.runners) || msg.runners.length > MAX_RUNNERS || !msg.runners.every(runnerOk)) {
      return 'bad_frame';
    }
    const ids = new Set(msg.runners.map((runner) => runner.id));
    return ids.size === msg.runners.length ? null : 'bad_frame';
  }
  if (msg.t === 'hb') {
    return hasKeys(msg, ['t', 'seq', 'paused']) && typeof msg.paused === 'boolean' ? null : 'bad_heartbeat';
  }
  if (msg.t === 'end') {
    return hasKeys(msg, ['t', 'seq', 'reason']) && isText(msg.reason, 64) ? null : 'bad_end';
  }
  return 'unknown_type';
}

// --- the view state ---------------------------------------------------------------------------------

// What the screen shows, built only from validated messages. rev counts changes, so the renderer
// redraws only when something new arrived.
export function createViewState() {
  return {
    seq: -1,
    rev: 0,
    frame: null,
    frameAtMs: 0,
    paused: true,
    ended: null,
    rejected: 0,
    lastReject: null,
  };
}

// A new stream connection starts its own sequence.
export function resetSequence(state) {
  state.seq = -1;
}

// Apply one stream message; returns true when the view changed. state.seq is the seq of the last
// frame applied. A frame whose seq is not above it is a no-op, so a replayed or duplicated frame
// changes nothing. Heartbeats and end lines carry the seq of the last frame sent before them (0 before
// the first), so they apply when their seq is not below it; both only set a value, so applying one
// twice changes nothing either. The whole function is idempotent.
export function applyMessage(state, msg, nowMs = 0) {
  const problem = validateMessage(msg);
  if (problem === 'unknown_type') {
    return false;
  }
  if (problem !== null) {
    state.rejected += 1;
    state.lastReject = problem;
    return false;
  }
  if (msg.t === 'frame') {
    if (msg.seq <= state.seq) {
      return false;
    }
    state.seq = msg.seq;
    state.frame = msg;
    state.frameAtMs = nowMs;
    state.paused = msg.clock.paused;
    state.ended = null;
  } else if (msg.seq < state.seq) {
    return false;                       // about an older frame than the one shown
  } else if (msg.t === 'hb') {
    if (state.paused === msg.paused) {
      return false;
    }
    state.paused = msg.paused;
  } else {
    if (state.ended === msg.reason) {
      return false;
    }
    state.ended = msg.reason;
  }
  state.rev += 1;
  return true;
}

// ms to the scheduled off at wall time nowMs: the frame's value, moved on by the replay speed while
// playing, at most maxWallMs past the frame (a stalled stream does not run the countdown away).
export function liveMsToOff(state, nowMs, maxWallMs = 2000) {
  const frame = state.frame;
  if (frame === null || frame.clock.ms_to_off === null) {
    return null;
  }
  if (state.paused) {
    return frame.clock.ms_to_off;
  }
  let wall = Math.floor(nowMs) - Math.floor(state.frameAtMs);
  if (wall < 0) {
    wall = 0;
  } else if (wall > maxWallMs) {
    wall = maxWallMs;
  }
  const moved = wall * frame.clock.speed_x100;
  return frame.clock.ms_to_off - (moved - (moved % 100)) / 100;
}

// --- requests ---------------------------------------------------------------------------------------

// Never set `mode`: fetch()'s default 'cors' mode is what sends the page's real Origin on a same-origin POST,
// which the server requires (DESIGN.md 9.2). With 'same-origin' or 'no-cors' and this no-referrer policy (also
// the page's own), the Fetch standard sends Origin: null instead, and the server refuses it (bad_origin).
const BASE_INIT = Object.freeze({ cache: 'no-store', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer' });

function hex(bytes) {
  let out = '';
  for (const byte of bytes) {
    out += (byte < 16 ? '0' : '') + byte.toString(16);
  }
  return out;
}

// 32 lowercase hex characters from 16 random bytes; fillRandom is crypto.getRandomValues.
export function makeNonce(fillRandom) {
  const bytes = new Uint8Array(16);
  fillRandom(bytes);
  return hex(bytes);
}

export function readFragmentCode(hash) {
  if (typeof hash !== 'string' || !hash.startsWith('#c=')) {
    return null;
  }
  const code = hash.slice(3);
  return CODE_RE.test(code) ? code : null;
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (error) {
    return null;
  }
}

function replyCode(body, fallback) {
  if (body !== null && typeof body === 'object' && typeof body.code === 'string' && REPLY_CODE_RE.test(body.code)) {
    return body.code;
  }
  return fallback;
}

// The request side of the API. getToken() returns the in-memory token or null; onUnauthorized() runs
// once a request is answered 401.
export function createApi({ fetchImpl, getToken, onUnauthorized, fillRandom }) {
  async function post(path, body, token) {
    const headers = { 'Content-Type': 'application/json' };
    if (token !== null) {
      headers.Authorization = 'Bearer ' + token;
    }
    let response;
    try {
      response = await fetchImpl(path, { ...BASE_INIT, method: 'POST', headers: headers, body: JSON.stringify(body) });
    } catch (error) {
      return { ok: false, code: 'network_error', status: 0 };
    }
    const reply = await readJson(response);
    if (response.status === 401) {
      return { ok: false, code: 'unauthorized', status: 401 };
    }
    if (!response.ok || reply === null || typeof reply !== 'object' || reply.ok === false) {
      return { ok: false, code: replyCode(reply, 'http_' + String(response.status)), status: response.status };
    }
    return { ok: true, reply: reply, status: response.status };
  }

  return {
    // Exchange the single-use code for the session token: {ok, token} or {ok:false, code}.
    async bootstrap(code) {
      if (typeof code !== 'string' || !CODE_RE.test(code)) {
        return { ok: false, code: 'no_code' };
      }
      const result = await post(ROUTES.bootstrap, { code: code }, null);
      if (!result.ok) {
        return result;
      }
      const token = result.reply.token;
      return typeof token === 'string' && TOKEN_RE.test(token) ? { ok: true, token: token } : { ok: false, code: 'bad_reply' };
    },

    // One read-only query (DESIGN.md 9.1): {ok, reply} or {ok:false, code}. The session query says whether
    // this tab is the controller (9.2 item 8).
    async query(name, args = {}) {
      if (!QUERIES.includes(name)) {
        return { ok: false, code: 'unknown_query' };
      }
      const token = getToken();
      if (token === null) {
        return { ok: false, code: 'no_session' };
      }
      const result = await post(ROUTES.query, { query: name, args: args }, token);
      if (result.status === 401) {
        onUnauthorized();
      }
      return result;
    },

    // One command from the closed enum, with a fresh nonce: {ok, reply} or {ok:false, code}.
    async command(name, args = {}) {
      if (!COMMANDS.includes(name)) {
        return { ok: false, code: 'unknown_command' };
      }
      const token = getToken();
      if (token === null) {
        return { ok: false, code: 'no_session' };
      }
      const result = await post(ROUTES.command, { nonce: makeNonce(fillRandom), command: name, args: args }, token);
      if (result.status === 401) {
        onUnauthorized();
      }
      return result;
    },
  };
}

// --- the stream -------------------------------------------------------------------------------------

const STALL_MS = 10000;     // heartbeats come every 1-2 s while paused or idle

async function readWithin(reader, ms, timers) {
  let timer = null;
  const expired = new Promise((resolve) => {
    timer = timers.set(() => resolve({ stalled: true }), ms);
  });
  try {
    return await Promise.race([reader.read(), expired]);
  } finally {
    timers.clear(timer);
  }
}

// Runs GET /api/v1/stream until stop() or a 401. Callbacks: onConnect() before the first chunk of
// each connection, onMessage(msg) per parsed line, onStatus(code) with connecting, connected,
// reconnecting, http_<n> or session_ended, and onUnauthorized() once on 401. sleep(ms) and timers
// are injectable for tests.
export function createStreamClient(options) {
  const {
    fetchImpl, getToken, onMessage, onStatus, onConnect = () => {}, onUnauthorized = () => {},
    sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    timers = { set: (fn, ms) => setTimeout(fn, ms), clear: (id) => clearTimeout(id) },
    stallMs = STALL_MS, makeAbort = () => new AbortController(),
  } = options;
  let stopped = false;
  let controller = null;
  let running = null;

  async function readStream(response) {
    const parser = new NdjsonParser();
    const reader = response.body.getReader();
    let received = false;
    try {
      for (;;) {
        const result = await readWithin(reader, stallMs, timers);
        if (stopped || result.stalled || result.done) {
          break;
        }
        received = true;
        for (const msg of parser.push(result.value)) {
          onMessage(msg);
        }
      }
    } catch (error) {
      // a reset connection: reconnect below
    } finally {
      parser.finish();
      try {
        const cancelled = reader.cancel();
        if (cancelled && typeof cancelled.catch === 'function') {
          cancelled.catch(() => {});
        }
      } catch (error) {
        // already closed
      }
    }
    return received;
  }

  async function loop() {
    let attempt = 0;
    while (!stopped) {
      const token = getToken();
      if (token === null) {
        onStatus('session_ended');
        return;
      }
      onStatus(attempt === 0 ? 'connecting' : 'reconnecting');
      controller = makeAbort();
      let response = null;
      try {
        response = await fetchImpl(ROUTES.stream, {
          ...BASE_INIT, method: 'GET', headers: { Authorization: 'Bearer ' + token }, signal: controller.signal,
        });
      } catch (error) {
        response = null;
      }
      if (stopped) {
        return;
      }
      if (response !== null && response.status === 401) {
        onStatus('session_ended');
        onUnauthorized();
        return;
      }
      if (response !== null && response.ok && response.body) {
        onConnect();
        onStatus('connected');
        if (await readStream(response)) {
          attempt = 0;
        }
      } else if (response !== null) {
        onStatus('http_' + String(response.status));
      }
      if (stopped) {
        return;
      }
      controller.abort();
      await sleep(backoffDelay(attempt));
      attempt += 1;
    }
  }

  return {
    start() {
      if (running === null) {
        stopped = false;
        running = loop().finally(() => {
          running = null;
        });
      }
      return running;
    },
    stop() {
      stopped = true;
      if (controller !== null) {
        controller.abort();
      }
    },
  };
}
