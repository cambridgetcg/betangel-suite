// One controller tab (DESIGN.md 9.2 item 8): app.js booted as a second tab against a fake same-origin server
// that says it is not the controller. The tab shows READ-ONLY and a "Take control" button, keeps every command
// control disabled, sends no command key and no pause on hiding, still moves its own selection, claims control
// with claim_control, and turns read-only again when a command is answered not_controller. Also the query
// client of stream.js. No browser and no network: everything here is in memory.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { QUERIES, createApi } from '../stream.js';
import { COMMAND_ACTIONS, ACTIONS, actionAllowed } from '../app.js';

const HTML = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const TICKS = JSON.parse(readFileSync(new URL('../ticks.json', import.meta.url), 'utf8'));
const CODE = 'test-code-2';
const TOKEN = 'test-token-' + 'c'.repeat(20);

class El {
  constructor(tag, attrs = {}) {
    this.tagName = tag.toUpperCase();
    this.attributes = { ...attrs };
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this.dataset = {};
    this.ownText = '';
    this.hidden = 'hidden' in attrs;
    this.disabled = 'disabled' in attrs;
    this.value = attrs.value || '';
    this.className = attrs.class || '';
    this.isContentEditable = false;
    this.width = 0;
    this.height = 0;
    for (const [name, value] of Object.entries(attrs)) {
      if (name.startsWith('data-')) {
        this.dataset[name.slice(5)] = value;
      }
    }
  }

  get textContent() {
    return this.ownText + this.children.map((child) => child.textContent).join('');
  }

  set textContent(value) {
    this.ownText = String(value);
    this.children = [];
  }

  get classList() {
    const names = () => this.className.split(' ').filter(Boolean);
    const set = (list) => { this.className = list.join(' '); };
    return {
      add: (name) => set([...names().filter((n) => n !== name), name]),
      remove: (name) => set(names().filter((n) => n !== name)),
      toggle: (name, on) => set(on ? [...names().filter((n) => n !== name), name] : names().filter((n) => n !== name)),
      contains: (name) => names().includes(name),
    };
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return name in this.attributes ? this.attributes[name] : null;
  }

  addEventListener(type, listener) {
    (this.listeners[type] = this.listeners[type] || []).push(listener);
  }

  fire(type, event = {}) {
    let prevented = false;
    const full = { target: this, currentTarget: this, preventDefault: () => { prevented = true; }, ...event };
    (this.listeners[type] || []).forEach((listener) => listener(full));
    return prevented;
  }

  appendChild(child) {
    if (child.parentNode) {
      const siblings = child.parentNode.children;
      siblings.splice(siblings.indexOf(child), 1);
    }
    this.children.push(child);
    child.parentNode = this;
    return child;
  }

  insertBefore(child, reference) {
    if (reference === null) {
      return this.appendChild(child);
    }
    if (child.parentNode) {
      const siblings = child.parentNode.children;
      siblings.splice(siblings.indexOf(child), 1);
    }
    this.children.splice(this.children.indexOf(reference), 0, child);
    child.parentNode = this;
    return child;
  }

  removeChild(child) {
    this.children.splice(this.children.indexOf(child), 1);
    child.parentNode = null;
    return child;
  }

  append(...nodes) {
    nodes.forEach((node) => this.appendChild(typeof node === 'string' ? textNode(node) : node));
  }

  replaceChildren(...nodes) {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    this.append(...nodes);
  }

  getContext() {
    return new Proxy({}, {
      get: (target, name) => (name in target ? target[name] : () => {}),
      set: (target, name, value) => { target[name] = value; return true; },
    });
  }
}

function textNode(text) {
  const node = new El('#text');
  node.ownText = text;
  return node;
}

function attributesOf(source) {
  const attrs = {};
  for (const match of source.matchAll(/([a-z][a-z0-9-]*)(?:="([^"]*)")?/g)) {
    attrs[match[1]] = match[2] === undefined ? '' : match[2];
  }
  return attrs;
}

function fakeDocument() {
  const byId = new Map();
  for (const match of HTML.matchAll(/<([a-z0-9]+)\b([^>]*)>/g)) {
    const attrs = attributesOf(match[2]);
    if (attrs.id) {
      byId.set(attrs.id, new El(match[1], attrs));
    }
  }
  const speeds = [...HTML.matchAll(/<button\b([^>]*class="speed"[^>]*)>/g)]
    .map((m) => new El('button', attributesOf(m[1])));
  const doc = new El('#document');
  Object.assign(doc, {
    visibilityState: 'visible',
    documentElement: new El('html'),
    body: new El('body'),
    getElementById: (id) => {
      if (!byId.has(id)) {
        throw new Error('app.js asked for an id index.html does not have: ' + id);
      }
      return byId.get(id);
    },
    querySelectorAll: () => speeds,
    createElement: (tag) => new El(tag),
  });
  return { doc, byId, speeds };
}

function encode(messages) {
  return new TextEncoder().encode(messages.map((msg) => JSON.stringify(msg) + '\n').join(''));
}

function frame(seq, paused) {
  return {
    t: 'frame', seq: seq,
    clock: { pt: 1433166600000, speed_x100: 100, paused: paused, pause_reason: paused ? 'ready' : null,
      ms_to_off: 600000 },
    market: { id: '1.999000002', name: 'Synthetic Park 14:30', status: 'OPEN', inplay: false, version: 1,
      invalid_reason: null },
    runners: [
      { id: 90000001, name: 'Synthetic 1', status: 'ACTIVE', ltp_h: 250, tv_p: 100, back: [[248, 1000]],
        lay: [[250, 800]] },
      { id: 90000002, name: 'Synthetic 2', status: 'ACTIVE', ltp_h: 400, tv_p: 100, back: [[390, 100]],
        lay: [[410, 100]] },
    ],
  };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

async function until(condition, what) {
  for (let i = 0; i < 400; i += 1) {
    if (condition()) {
      return;
    }
    await tick();
    if (i > 50) {
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
  }
  assert.fail('timed out waiting for ' + what);
}

test('actionAllowed: a read-only tab sends no command key; help always works', () => {
  assert.deepEqual([...COMMAND_ACTIONS].sort(), ['speed_down', 'speed_up', 'stop', 'toggle_play']);
  for (const action of ACTIONS) {
    assert.equal(actionAllowed(action, { ended: false, readOnly: false }), true, action);
    assert.equal(actionAllowed(action, { ended: false, readOnly: true }), !COMMAND_ACTIONS.includes(action), action);
    assert.equal(actionAllowed(action, { ended: true, readOnly: false }), action === 'toggle_help', action);
  }
});

test('query: enum names only, the bearer token, and a 401 ends the session', async () => {
  const sent = [];
  let unauthorized = 0;
  let status = 200;
  const api = createApi({
    fetchImpl: async (url, init) => {
      sent.push({ url, init });
      const body = status === 200 ? { ok: true, controller: false } : {};
      return { status: status, ok: status < 300, json: async () => body };
    },
    getToken: () => TOKEN,
    onUnauthorized: () => { unauthorized += 1; },
    fillRandom: (bytes) => bytes.fill(1),
  });
  assert.deepEqual(QUERIES, ['session', 'catalogue', 'journal', 'green_up_preview']);
  assert.deepEqual(await api.query('accounts'), { ok: false, code: 'unknown_query' });
  assert.equal(sent.length, 0);
  const result = await api.query('session');
  assert.equal(result.ok, true);
  assert.equal(result.reply.controller, false);
  assert.equal(sent[0].url, '/api/v1/query');
  assert.equal(sent[0].init.method, 'POST');
  assert.equal(sent[0].init.credentials, 'omit');
  assert.equal(sent[0].init.headers.Authorization, 'Bearer ' + TOKEN);
  assert.deepEqual(JSON.parse(sent[0].init.body), { query: 'session', args: {} });
  status = 401;
  assert.equal((await api.query('session')).code, 'unauthorized');
  assert.equal(unauthorized, 1);
});

test('a second tab is read-only until it claims control', async () => {
  const { doc, byId } = fakeDocument();
  const requests = [];
  const animation = [];
  let controller = false;
  let shutdown = false;
  let released = false;
  let wake = null;
  let streams = 0;
  const chunks = [encode([frame(1, false)])];
  const awaken = () => {
    if (wake !== null) {
      const resolve = wake;
      wake = null;
      resolve();
    }
  };
  const location = { hash: '#c=' + CODE, pathname: '/', search: '' };
  const commandReplies = [];      // queued replies for the next commands: [status, body]

  const fetchImpl = async (url, init = {}) => {
    requests.push({ url, init });
    const json = (status, body) => ({ status, ok: status < 300, json: async () => body });
    if (url === '/ticks.json') {
      return json(200, TICKS);
    }
    if (url === '/api/v1/bootstrap') {
      return json(200, { ok: true, token: TOKEN });
    }
    if (url === '/api/v1/query') {
      return json(200, { ok: true, controller: controller, market: null });
    }
    if (url === '/api/v1/command') {
      const body = JSON.parse(init.body);
      if (body.command === 'claim_control') {
        controller = true;
        return json(200, { ok: true });
      }
      if (commandReplies.length > 0) {
        const [status, reply] = commandReplies.shift();
        return json(status, reply);
      }
      return controller ? json(200, { ok: true }) : json(409, { ok: false, code: 'not_controller' });
    }
    if (url === '/api/v1/stream') {
      streams += 1;
      if (streams > 1 || shutdown) {
        return { status: 401, ok: false, body: null };
      }
      const read = async () => {
        while (chunks.length === 0 && !released) {
          await new Promise((resolve) => { wake = resolve; });
        }
        return chunks.length ? { done: false, value: chunks.shift() } : { done: true };
      };
      return { status: 200, ok: true, body: { getReader: () => ({ read: read, cancel: async () => {} }) } };
    }
    throw new Error('unexpected request ' + url);
  };

  globalThis.document = doc;
  globalThis.window = {
    location: location,
    history: { replaceState: () => { location.hash = ''; } },
    fetch: fetchImpl,
    crypto: { getRandomValues: (bytes) => bytes.fill(9) },
    performance: { now: () => 1000 },
    requestAnimationFrame: (fn) => animation.push(fn),
    setInterval: () => 1,
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    matchMedia: () => ({ addEventListener: () => {} }),
    devicePixelRatio: 1,
  };
  const commands = () => requests.filter((r) => r.url === '/api/v1/command')
    .map((r) => JSON.parse(r.init.body).command);
  const render = () => {
    while (animation.length) {
      animation.shift()();
    }
  };
  try {
    await import('../app.js?tab=second');            // a fresh instance: the import above did not boot
    await until(() => byId.get('role').hidden === false, 'the read-only chip');
    await until(() => animation.length > 0, 'the first frame');
    render();
    assert.equal(byId.get('claim').hidden, false);
    assert.equal(byId.get('claim').disabled, false);
    for (const id of ['play', 'seed', 'open', 'stop']) {
      assert.equal(byId.get(id).disabled, true, id + ' is disabled while read-only');
    }

    // Command keys send nothing; runner selection still works; hiding the page sends no pause.
    for (const key of [' ', '+', '-', 'q']) {
      assert.equal(doc.fire('keydown', { key: key, target: doc.body }), false, key);
    }
    assert.equal(doc.fire('keydown', { key: 'ArrowDown', target: doc.body }), true);
    render();
    assert.equal(byId.get('ladder-runner').textContent, 'Synthetic 2');
    doc.visibilityState = 'hidden';
    doc.fire('visibilitychange');
    for (let i = 0; i < 20; i += 1) {
      await tick();
    }
    doc.visibilityState = 'visible';
    assert.deepEqual(commands(), [], 'a read-only tab sent no command');

    // Take control: claim_control, then the controls work.
    byId.get('claim').fire('click');
    await until(() => byId.get('role').hidden === true, 'control claimed');
    assert.deepEqual(commands(), ['claim_control']);
    const claim = JSON.parse(requests.find((r) => r.url === '/api/v1/command').init.body);
    assert.deepEqual(claim.args, {});
    assert.match(claim.nonce, /^[0-9a-f]{32}$/);
    assert.equal(byId.get('claim').hidden, true);
    assert.equal(byId.get('play').disabled, false);
    assert.equal(byId.get('note').textContent, 'claim_control: ok');

    // Another tab claims it back: the next command is answered not_controller, and this tab is read-only again.
    commandReplies.push([409, { ok: false, code: 'not_controller' }]);
    controller = false;
    byId.get('play').fire('click');
    await until(() => byId.get('role').hidden === false, 'read-only again');
    assert.equal(byId.get('play').disabled, true);
    assert.equal(byId.get('note').textContent, 'pause: not_controller');

    const shown = [...byId.values()].map((el) => el.textContent + JSON.stringify(el.attributes)).join(' ');
    assert.equal(shown.includes(TOKEN), false, 'the token is never put in the page');
    assert.equal(shown.includes(CODE), false, 'nor is the bootstrap code');
  } finally {
    shutdown = true;
    released = true;
    awaken();
  }
  await until(() => byId.get('conn').textContent === 'session ended, run suite open again', 'the end');
  assert.equal(byId.get('role').hidden, true, 'an ended session shows no role');
  assert.equal(byId.get('claim').hidden, true);
});
