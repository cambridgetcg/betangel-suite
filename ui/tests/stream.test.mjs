// NDJSON parsing, backoff, message validation, frame application (seq idempotency), and the stream and
// API clients against a fake fetch. Synthetic namespace only: market 1.999xxxxxx, runners 9xxxxxxx.
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  BACKOFF, COMMANDS, NdjsonParser, ROUTES, SESSION_ENDED, applyMessage, backoffDelay, createApi, createStreamClient,
  createViewState, liveMsToOff, makeNonce, readFragmentCode, resetSequence, validateMessage,
} from '../stream.js';

const TOKEN = 'test-token-' + 'a'.repeat(20);

function frame(seq, changes = {}) {
  return {
    t: 'frame',
    seq: seq,
    clock: { pt: 1433166600000, speed_x100: 100, paused: false, pause_reason: null, ms_to_off: 600000,
      ...(changes.clock || {}) },
    market: { id: '1.999000001', name: 'Synthetic Park 14:00', status: 'OPEN', inplay: false, version: 1,
      invalid_reason: null, ...(changes.market || {}) },
    runners: changes.runners || [
      { id: 90000001, name: 'Synthetic 1', status: 'ACTIVE', ltp_h: 250, tv_p: 123400,
        back: [[248, 1000], [246, 500], [244, 250]], lay: [[250, 800], [252, 400], [254, 200]] },
      { id: 90000002, name: 'Synthetic 2', status: 'ACTIVE', ltp_h: null, tv_p: 0, back: [], lay: [[1000, 300]] },
    ],
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

// --- NDJSON ---------------------------------------------------------------------------------------

test('NDJSON: whole lines parse; blank lines and CR are tolerated', () => {
  const parser = new NdjsonParser();
  const out = parser.push('{"a":1}\r\n\n  \n{"b":2}\n');
  assert.deepEqual(out, [{ a: 1 }, { b: 2 }]);
  assert.equal(parser.badLines, 0);
});

test('NDJSON: a line split across chunks at every byte gives the same messages', () => {
  const text = JSON.stringify(frame(1)) + '\n' + JSON.stringify({ t: 'end', seq: 2, reason: 'closed £' }) + '\n';
  const bytes = new TextEncoder().encode(text);
  const whole = new NdjsonParser().push(bytes);
  assert.equal(whole.length, 2);
  for (let cut = 1; cut < bytes.length; cut += 1) {
    const parser = new NdjsonParser();
    const got = [...parser.push(bytes.slice(0, cut)), ...parser.push(bytes.slice(cut))];
    assert.deepEqual(got, whole, 'cut at ' + cut);
  }
});

test('NDJSON: a multi-byte character split between chunks is decoded once', () => {
  const bytes = new TextEncoder().encode('{"t":"end","seq":1,"reason":"£"}\n');
  const at = bytes.indexOf(0xc2);
  const parser = new NdjsonParser();
  assert.deepEqual(parser.push(bytes.slice(0, at + 1)), []);
  assert.deepEqual(parser.push(bytes.slice(at + 1)), [{ t: 'end', seq: 1, reason: '£' }]);
});

test('NDJSON: a partial line waits for its newline, and is dropped at end of stream', () => {
  const parser = new NdjsonParser();
  assert.deepEqual(parser.push('{"a":'), []);
  assert.deepEqual(parser.push('1}'), []);
  assert.deepEqual(parser.push('\n{"b":'), [{ a: 1 }]);
  parser.finish();
  assert.equal(parser.droppedPartial, 1);
  assert.deepEqual(parser.push('{"c":3}\n'), [{ c: 3 }], 'the parser is clean after finish');
});

test('NDJSON: a bad line is counted and skipped', () => {
  const parser = new NdjsonParser();
  assert.deepEqual(parser.push('{"a":1}\nnot json\n{"b":2}\n'), [{ a: 1 }, { b: 2 }]);
  assert.equal(parser.badLines, 1);
});

test('NDJSON: an overlong line is discarded up to its newline', () => {
  const parser = new NdjsonParser(32);
  const long = '{"x":"' + 'y'.repeat(60) + '"}';
  assert.deepEqual(parser.push(long.slice(0, 40)), []);
  assert.deepEqual(parser.push(long.slice(40) + '\n{"ok":1}\n'), [{ ok: 1 }]);
  assert.equal(parser.longLines, 1);
  assert.deepEqual(parser.push('{"z":"' + 'q'.repeat(40) + '"}\n{"ok":2}\n'), [{ ok: 2 }]);
  assert.equal(parser.longLines, 2);
});

// --- backoff --------------------------------------------------------------------------------------

test('backoff doubles from 250 ms and is capped at 8 s', () => {
  const delays = [0, 1, 2, 3, 4, 5, 6, 50].map((attempt) => backoffDelay(attempt));
  assert.deepEqual(delays, [250, 500, 1000, 2000, 4000, 8000, 8000, 8000]);
  assert.equal(BACKOFF.capMs, 8000);
  for (let attempt = 0; attempt < 40; attempt += 1) {
    assert.ok(Number.isSafeInteger(backoffDelay(attempt)));
    assert.ok(backoffDelay(attempt + 1) >= backoffDelay(attempt));
  }
  assert.throws(() => backoffDelay(-1), RangeError);
  assert.throws(() => backoffDelay(1.5), RangeError);
});

// --- validation -----------------------------------------------------------------------------------

test('well-formed frame, heartbeat and end messages validate', () => {
  assert.equal(validateMessage(frame(1)), null);
  assert.equal(validateMessage({ t: 'hb', seq: 2, paused: true }), null);
  assert.equal(validateMessage({ t: 'end', seq: 3, reason: 'closed' }), null);
  assert.equal(validateMessage({ t: 'later', seq: 4 }), 'unknown_type');
});

test('money and prices must be integers; every known field is present and typed', () => {
  const bad = [];
  const push = (mutate) => {
    const msg = clone(frame(1));
    mutate(msg);
    bad.push(msg);
  };
  push((m) => { m.runners[0].back[0][0] = 2.48; });
  push((m) => { m.runners[0].back[0][1] = 10.5; });
  push((m) => { m.runners[0].lay[0][0] = '250'; });
  push((m) => { m.runners[0].ltp_h = 2.5; });
  push((m) => { m.runners[0].tv_p = 1234.5; });
  push((m) => { m.runners[0].tv_p = -1; });
  push((m) => { m.runners[0].back.push([242, 1]); });
  push((m) => { m.runners[0].back[0] = [248]; });
  push((m) => { m.runners[0].back[0][1] = -1; });
  push((m) => { m.runners[0].back[0][0] = 0; });
  push((m) => { m.runners[1].id = 90000001; });
  push((m) => { delete m.runners[0].tv_p; });
  push((m) => { delete m.clock.ms_to_off; });
  push((m) => { delete m.market.invalid_reason; });
  push((m) => { m.clock.pt = 1.5; });
  push((m) => { m.clock.speed_x100 = 0; });
  push((m) => { m.clock.ms_to_off = 0.5; });
  push((m) => { m.clock.paused = 'no'; });
  push((m) => { m.market.inplay = 0; });
  push((m) => { m.market.version = 1.1; });
  push((m) => { m.market.id = 9; });
  push((m) => { m.seq = -1; });
  push((m) => { m.seq = 1.5; });
  push((m) => { m.runners = {}; });
  push((m) => { delete m.clock; });
  bad.forEach((msg, i) => assert.notEqual(validateMessage(msg), null, 'case ' + i));
  assert.equal(validateMessage(null), 'bad_message');
  assert.equal(validateMessage([]), 'bad_message');
  assert.equal(validateMessage({ t: 'hb', seq: 1, paused: 1 }), 'bad_heartbeat');
  assert.equal(validateMessage({ t: 'end', seq: 1 }), 'bad_end');
});

test('fields the UI does not know are ignored, so a later engine can add them', () => {
  const msg = clone(frame(1));
  msg.extra = true;
  msg.clock.effective_speed_x100 = 100;
  msg.market.bet_delay = 0;
  msg.runners[0].wom = 50;
  assert.equal(validateMessage(msg), null);
  assert.equal(validateMessage({ t: 'hb', seq: 1, paused: true, controller: true }), null);
});

// --- applying messages ----------------------------------------------------------------------------

test('a frame applies once; the same or an older seq changes nothing', () => {
  const state = createViewState();
  assert.equal(applyMessage(state, frame(5), 1000), true);
  assert.equal(state.seq, 5);
  assert.equal(state.rev, 1);
  const before = clone(state);
  assert.equal(applyMessage(state, frame(5, { market: { status: 'SUSPENDED' } }), 2000), false);
  assert.equal(applyMessage(state, frame(4, { market: { status: 'CLOSED' } }), 3000), false);
  assert.equal(applyMessage(state, frame(5), 4000), false);
  assert.deepEqual(clone(state), before, 'state is unchanged by replays');
  assert.equal(applyMessage(state, frame(6, { market: { status: 'SUSPENDED' } }), 5000), true);
  assert.equal(state.frame.market.status, 'SUSPENDED');
  assert.equal(state.rev, 2);
});

test('applying the same frames twice gives the same state (idempotent)', () => {
  const messages = [frame(1), { t: 'hb', seq: 2, paused: true }, frame(3, { clock: { paused: true } }), frame(4)];
  const once = createViewState();
  messages.forEach((msg) => applyMessage(once, msg, 0));
  const twice = createViewState();
  messages.concat(messages).forEach((msg) => applyMessage(twice, msg, 0));
  assert.deepEqual(clone(twice), clone(once));
});

test('invalid messages are counted and never applied; unknown types are ignored', () => {
  const state = createViewState();
  applyMessage(state, frame(1), 0);
  const bad = clone(frame(2));
  bad.runners[0].ltp_h = 2.5;
  assert.equal(applyMessage(state, bad, 0), false);
  assert.equal(state.rejected, 1);
  assert.equal(state.lastReject, 'bad_frame');
  assert.equal(state.seq, 1);
  assert.equal(state.frame.runners[0].ltp_h, 250);
  assert.equal(applyMessage(state, { t: 'later', seq: 9 }, 0), false);
  assert.equal(state.rejected, 1);
});

test('heartbeats and end carry the last frame\'s seq; only older ones are stale', () => {
  const state = createViewState();
  assert.equal(applyMessage(state, { t: 'hb', seq: 0, paused: true }, 0), false, 'idle start: already paused');
  applyMessage(state, frame(7), 0);
  assert.equal(state.paused, false);
  assert.equal(applyMessage(state, { t: 'hb', seq: 7, paused: true }, 0), true);
  assert.equal(state.paused, true);
  assert.equal(state.seq, 7, 'a heartbeat never moves the frame sequence');
  assert.equal(applyMessage(state, { t: 'hb', seq: 6, paused: false }, 0), false, 'about an older frame');
  assert.equal(state.paused, true);
  assert.equal(applyMessage(state, frame(7), 0), false, 'the frame itself is not applied again');
  assert.equal(applyMessage(state, { t: 'end', seq: 7, reason: 'stopped' }, 0), true);
  assert.equal(state.ended, 'stopped');
  assert.equal(applyMessage(state, { t: 'end', seq: 7, reason: 'stopped' }, 0), false);
  assert.equal(applyMessage(state, frame(9), 0), true, 'a slow reader may skip frames');
  assert.equal(state.ended, null);
});

test('the engine\'s message pattern applied twice gives the same state', () => {
  const messages = [{ t: 'hb', seq: 0, paused: true }, frame(3), { t: 'hb', seq: 3, paused: false },
    frame(4, { clock: { paused: true, pause_reason: 'user' } }), { t: 'hb', seq: 4, paused: true },
    { t: 'end', seq: 4, reason: 'stopped' }];
  const once = createViewState();
  messages.forEach((msg) => applyMessage(once, msg, 0));
  const twice = createViewState();
  messages.concat(messages).forEach((msg) => applyMessage(twice, msg, 0));
  assert.deepEqual(clone(twice), clone(once));
  assert.equal(once.ended, 'stopped');
  assert.equal(once.paused, true);
});

test('heartbeats carry the paused flag; end records the reason until the next frame', () => {
  const state = createViewState();
  applyMessage(state, frame(1), 0);
  assert.equal(state.paused, false);
  assert.equal(applyMessage(state, { t: 'hb', seq: 2, paused: true }, 0), true);
  assert.equal(state.paused, true);
  assert.equal(applyMessage(state, { t: 'hb', seq: 3, paused: true }, 0), false, 'no change, no redraw');
  assert.equal(applyMessage(state, { t: 'end', seq: 4, reason: 'closed' }, 0), true);
  assert.equal(state.ended, 'closed');
  applyMessage(state, frame(5), 0);
  assert.equal(state.ended, null);
});

test('a new connection restarts the sequence', () => {
  const state = createViewState();
  applyMessage(state, frame(40), 0);
  assert.equal(applyMessage(state, frame(1), 0), false);
  resetSequence(state);
  assert.equal(applyMessage(state, frame(1), 0), true);
});

test('the countdown runs on at replay speed between frames, and holds while paused', () => {
  const state = createViewState();
  applyMessage(state, frame(1, { clock: { speed_x100: 200, ms_to_off: 60000 } }), 1000);
  assert.equal(liveMsToOff(state, 1000), 60000);
  assert.equal(liveMsToOff(state, 1500.7), 59000);
  assert.equal(liveMsToOff(state, 9000), 56000, 'capped at 2 s of wall time');
  assert.equal(liveMsToOff(state, 500), 60000);
  applyMessage(state, { t: 'hb', seq: 2, paused: true }, 0);
  assert.equal(liveMsToOff(state, 9000), 60000);
  assert.equal(liveMsToOff(createViewState(), 0), null);
});

// --- requests -------------------------------------------------------------------------------------

function jsonResponse(status, body) {
  return { status: status, ok: status >= 200 && status < 300, json: async () => body };
}

function recordingFetch(responses) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url: url, init: init });
    const next = responses.shift();
    if (next instanceof Error) {
      throw next;
    }
    return typeof next === 'function' ? next() : next;
  };
  return { calls, fetchImpl };
}

let counter = 0;
const fillRandom = (bytes) => {
  for (let i = 0; i < bytes.length; i += 1) {
    counter += 1;
    bytes[i] = (counter * 37) % 256;
  }
};

test('the fragment code is read strictly', () => {
  assert.equal(readFragmentCode('#c=' + 'abc_DEF-123'), 'abc_DEF-123');
  assert.equal(readFragmentCode(''), null);
  assert.equal(readFragmentCode('#x=abc'), null);
  assert.equal(readFragmentCode('#c='), null);
  assert.equal(readFragmentCode('#c=' + 'a b'), null);
  assert.equal(readFragmentCode('#c=' + 'a'.repeat(129)), null);
});

test('bootstrap posts the code as JSON without a token and returns the token', async () => {
  const { calls, fetchImpl } = recordingFetch([jsonResponse(200, { ok: true, token: TOKEN })]);
  const api = createApi({ fetchImpl, getToken: () => null, onUnauthorized: () => {}, fillRandom });
  assert.deepEqual(await api.bootstrap('code-1'), { ok: true, token: TOKEN });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, ROUTES.bootstrap);
  assert.equal(calls[0].url, '/api/v1/bootstrap');
  const init = calls[0].init;
  assert.equal(init.method, 'POST');
  assert.equal(init.headers['Content-Type'], 'application/json');
  assert.equal('Authorization' in init.headers, false);
  assert.equal(init.credentials, 'omit');
  assert.equal(init.cache, 'no-store');
  assert.equal(init.redirect, 'error');
  assert.deepEqual(JSON.parse(init.body), { code: 'code-1' });
});

test('bootstrap failures are codes; a malformed token is refused', async () => {
  const replies = [jsonResponse(401, { ok: false, code: 'bad_code' }), jsonResponse(200, { ok: true, token: 'short' }),
    jsonResponse(403, { ok: false, code: 'origin_mismatch' }), new Error('offline')];
  const { calls, fetchImpl } = recordingFetch(replies);
  const api = createApi({ fetchImpl, getToken: () => null, onUnauthorized: () => {}, fillRandom });
  assert.deepEqual(await api.bootstrap('code-1'), { ok: false, code: 'unauthorized', status: 401 });
  assert.deepEqual(await api.bootstrap('code-1'), { ok: false, code: 'bad_reply' });
  assert.deepEqual(await api.bootstrap('code-1'), { ok: false, code: 'origin_mismatch', status: 403 });
  assert.deepEqual(await api.bootstrap('code-1'), { ok: false, code: 'network_error', status: 0 });
  assert.deepEqual(await api.bootstrap(''), { ok: false, code: 'no_code' });
  assert.equal(calls.length, 4);
});

test('commands carry a fresh nonce and the bearer token, and only enum names are sent', async () => {
  const { calls, fetchImpl } = recordingFetch([jsonResponse(200, { ok: true }), jsonResponse(200, { ok: true }),
    jsonResponse(200, { ok: false, code: 'not_implemented' })]);
  const api = createApi({ fetchImpl, getToken: () => TOKEN, onUnauthorized: () => {}, fillRandom });
  assert.equal((await api.command('open_market', { seed: 7 })).ok, true);
  assert.equal((await api.command('set_speed', { speed_x100: 200 })).ok, true);
  assert.deepEqual(await api.command('seek', { pt: 1 }), { ok: false, code: 'not_implemented', status: 200 });
  assert.deepEqual(await api.command('login', {}), { ok: false, code: 'unknown_command' });
  assert.equal(calls.length, 3);
  const bodies = calls.map((call) => JSON.parse(call.init.body));
  assert.deepEqual(Object.keys(bodies[0]).sort(), ['args', 'command', 'nonce']);
  assert.deepEqual(bodies[0].args, { seed: 7 });
  assert.equal(bodies[1].command, 'set_speed');
  bodies.forEach((body) => assert.match(body.nonce, /^[0-9a-f]{32}$/));
  assert.equal(new Set(bodies.map((body) => body.nonce)).size, 3);
  calls.forEach((call) => {
    assert.equal(call.url, '/api/v1/command');
    assert.equal(call.init.headers.Authorization, 'Bearer ' + TOKEN);
    assert.equal(call.init.headers['Content-Type'], 'application/json');
  });
});

test('a 401 on a command ends the session; no token means nothing is sent', async () => {
  let ended = 0;
  const { calls, fetchImpl } = recordingFetch([jsonResponse(401, { ok: false, code: 'unauthorized' })]);
  const api = createApi({ fetchImpl, getToken: () => TOKEN, onUnauthorized: () => { ended += 1; }, fillRandom });
  assert.equal((await api.command('play', {})).code, 'unauthorized');
  assert.equal(ended, 1);
  const none = createApi({ fetchImpl, getToken: () => null, onUnauthorized: () => {}, fillRandom });
  assert.deepEqual(await none.command('play', {}), { ok: false, code: 'no_session' });
  assert.equal(calls.length, 1);
});

test('the command enum is DESIGN 9.1 and holds no live or account names', () => {
  assert.equal(COMMANDS.length, 19);
  for (const name of ['open_market', 'play', 'pause', 'set_speed', 'stop']) {
    assert.ok(COMMANDS.includes(name), name);
  }
  for (const name of [...COMMANDS, ...Object.values(ROUTES)]) {
    for (const banned of ['live', 'account', 'funds', 'login', 'kill', 'upload', 'share']) {
      assert.equal(name.includes(banned), false, name);
    }
  }
});

test('nonces are 32 lowercase hex characters', () => {
  assert.equal(makeNonce((bytes) => bytes.fill(255)), 'f'.repeat(32));
  assert.equal(makeNonce((bytes) => bytes.fill(0)), '0'.repeat(32));
});

// --- the stream client ----------------------------------------------------------------------------

function streamResponse(chunks, status = 200) {
  const encoder = new TextEncoder();
  let i = 0;
  let cancelled = 0;
  const response = {
    status: status,
    ok: status >= 200 && status < 300,
    body: {
      getReader: () => ({
        read: async () => (i < chunks.length ? { done: false, value: encoder.encode(chunks[i++]) } : { done: true }),
        cancel: async () => { cancelled += 1; },
      }),
    },
    cancelled: () => cancelled,
  };
  return response;
}

function harness(responses, { stopAfterSleeps = 10, token = TOKEN, timers } = {}) {
  const { calls, fetchImpl } = recordingFetch(responses);
  const log = { messages: [], statuses: [], sleeps: [], connects: 0, unauthorized: 0 };
  let client = null;
  client = createStreamClient({
    fetchImpl,
    getToken: () => token,
    onMessage: (msg) => log.messages.push(msg),
    onStatus: (status) => log.statuses.push(status),
    onConnect: () => { log.connects += 1; },
    onUnauthorized: () => { log.unauthorized += 1; },
    sleep: async (ms) => {
      log.sleeps.push(ms);
      if (log.sleeps.length >= stopAfterSleeps) {
        client.stop();
      }
    },
    ...(timers ? { timers } : {}),
  });
  return { calls, log, client };
}

test('the stream sends the bearer token, delivers lines, reconnects, and stops for good on 401', async () => {
  const first = streamResponse([JSON.stringify(frame(1)) + '\n{"t":"hb",', '"seq":2,"paused":true}\n']);
  const { calls, log, client } = harness([first, streamResponse([], 401)]);
  await client.start();
  assert.equal(calls.length, 2);
  for (const call of calls) {
    assert.equal(call.url, '/api/v1/stream');
    assert.equal(call.init.method, 'GET');
    assert.equal(call.init.headers.Authorization, 'Bearer ' + TOKEN);
    assert.equal(call.init.credentials, 'omit');
    assert.equal(call.init.cache, 'no-store');
  }
  assert.deepEqual(log.messages.map((msg) => msg.t), ['frame', 'hb']);
  assert.equal(log.connects, 1);
  assert.deepEqual(log.sleeps, [250], 'a connection that delivered data resets the backoff');
  assert.deepEqual(log.statuses, ['connecting', 'connected', 'reconnecting', 'session_ended']);
  assert.equal(log.unauthorized, 1);
  assert.equal(SESSION_ENDED, 'session ended, run suite open again');
});

test('network errors back off with growing, capped delays until stopped', async () => {
  const failures = Array.from({ length: 8 }, () => new Error('offline'));
  const { calls, log, client } = harness(failures, { stopAfterSleeps: 7 });
  await client.start();
  assert.deepEqual(log.sleeps, [250, 500, 1000, 2000, 4000, 8000, 8000]);
  assert.equal(calls.length, 7);
  assert.equal(log.statuses[0], 'connecting');
  assert.ok(log.statuses.slice(1).every((status) => status === 'reconnecting'));
});

test('an HTTP error is reported as a code and retried', async () => {
  const { log, client } = harness([streamResponse([], 503), streamResponse([], 503)], { stopAfterSleeps: 2 });
  await client.start();
  assert.ok(log.statuses.includes('http_503'));
  assert.deepEqual(log.sleeps, [250, 500]);
});

test('no token: the stream is never requested', async () => {
  const { calls, log, client } = harness([], { token: null });
  await client.start();
  assert.equal(calls.length, 0);
  assert.deepEqual(log.statuses, ['session_ended']);
});

test('a stalled stream is abandoned and reconnected', async () => {
  let reads = 0;
  const stalled = {
    status: 200,
    ok: true,
    body: { getReader: () => ({ read: () => { reads += 1; return new Promise(() => {}); }, cancel: async () => {} }) },
  };
  const immediate = { set: (fn) => { queueMicrotask(fn); return 1; }, clear: () => {} };
  const { calls, log, client } = harness([stalled, stalled], { stopAfterSleeps: 2, timers: immediate });
  await client.start();
  assert.equal(calls.length, 2);
  assert.equal(reads, 2);
  assert.equal(log.connects, 2);
  assert.deepEqual(log.sleeps, [250, 500], 'a connection that never delivered does not reset the backoff');
});

test('stop() ends the loop and aborts the request', async () => {
  let aborted = 0;
  let client = null;
  client = createStreamClient({
    fetchImpl: async (url, init) => {
      init.signal.addEventListener('abort', () => { aborted += 1; });
      client.stop();
      return streamResponse([JSON.stringify(frame(1)) + '\n']);
    },
    getToken: () => TOKEN,
    onMessage: () => assert.fail('no message after stop'),
    onStatus: () => {},
    sleep: async () => assert.fail('no sleep after stop'),
  });
  await client.start();
  assert.equal(aborted, 1);
});
