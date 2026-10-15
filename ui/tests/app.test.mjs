// Boots app.js against a fake DOM built from index.html and a fake same-origin server: the fragment
// is stripped before anything is sent, the code is exchanged for a token that only travels in the
// Authorization header, frames render into the header, grid and ladder, controls and keys send
// commands, hiding the page while the clock runs sends one pause (DESIGN.md 8.6, I-19), and a 401 ends
// the session. No browser and no network: everything here is in memory.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const HTML = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const TICKS = JSON.parse(readFileSync(new URL('../ticks.json', import.meta.url), 'utf8'));
const CODE = 'test-code-1';
const TOKEN = 'test-token-' + 'b'.repeat(20);

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
    this.drawCalls = 0;
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

  detach(child) {
    if (child.parentNode) {
      const siblings = child.parentNode.children;
      siblings.splice(siblings.indexOf(child), 1);
      child.parentNode = null;
    }
  }

  appendChild(child) {
    this.detach(child);
    this.children.push(child);
    child.parentNode = this;
    return child;
  }

  insertBefore(child, reference) {
    if (reference === null) {
      return this.appendChild(child);
    }
    this.detach(child);
    this.children.splice(this.children.indexOf(reference), 0, child);
    child.parentNode = this;
    return child;
  }

  removeChild(child) {
    this.detach(child);
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
    const element = this;
    return new Proxy({}, {
      get: (target, name) => (name in target ? target[name] : () => { element.drawCalls += 1; }),
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

// Every element of index.html that has an id, plus the speed buttons, as fake elements.
function fakeDocument() {
  const byId = new Map();
  for (const match of HTML.matchAll(/<([a-z0-9]+)\b([^>]*)>/g)) {
    const attrs = attributesOf(match[2]);
    if (attrs.id) {
      byId.set(attrs.id, new El(match[1], attrs));
    }
  }
  const speeds = [...HTML.matchAll(/<button\b([^>]*class="speed"[^>]*)>/g)].map((m) => new El('button', attributesOf(m[1])));
  const body = new El('body');
  const doc = new El('#document');
  Object.assign(doc, {
    visibilityState: 'visible',
    documentElement: new El('html'),
    body: body,
    getElementById: (id) => {
      if (!byId.has(id)) {
        throw new Error('app.js asked for an id index.html does not have: ' + id);
      }
      return byId.get(id);
    },
    querySelectorAll: (selector) => {
      assert.equal(selector, 'button.speed');
      return speeds;
    },
    createElement: (tag) => new El(tag),
  });
  return { doc, byId, speeds, body };
}

function encode(messages) {
  return new TextEncoder().encode(messages.map((msg) => JSON.stringify(msg) + '\n').join(''));
}

function frame(seq, paused) {
  return {
    t: 'frame', seq: seq,
    clock: { pt: 1433166600000, speed_x100: 100, paused: paused, pause_reason: paused ? 'not_started' : null,
      ms_to_off: 600000 },
    market: { id: '1.999000001', name: 'Synthetic Park 14:00', status: 'OPEN', inplay: false, version: 1,
      invalid_reason: null },
    runners: [
      { id: 90000001, name: 'Synthetic 1', status: 'ACTIVE', ltp_h: 250, tv_p: 123400,
        back: [[248, 1000], [246, 500], [244, 250]], lay: [[250, 800], [252, 400], [254, 200]] },
      { id: 90000002, name: 'Synthetic 2', status: 'ACTIVE', ltp_h: 1000, tv_p: 5000, back: [[990, 100]], lay: [] },
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

test('boot: strip the fragment, bootstrap, stream, render, command, and end on 401', async () => {
  const { doc, byId, speeds } = fakeDocument();
  const events = [];
  const requests = [];
  const animation = [];
  let streams = 0;
  let shutdown = false;
  let refused = 0;
  let delivered = false;
  let released = false;
  let wake = null;
  const chunks = [encode([frame(1, true)]), encode([{ t: 'hb', seq: 2, paused: true }])];
  const awaken = () => {
    if (wake !== null) {
      const resolve = wake;
      wake = null;
      resolve();
    }
  };
  const push = (messages) => { chunks.push(encode(messages)); awaken(); };      // more of the open stream
  const release = () => { released = true; awaken(); };                        // the stream ends
  const location = { hash: '#c=' + CODE, pathname: '/', search: '' };

  const fetchImpl = async (url, init = {}) => {
    requests.push({ url, init });
    events.push('fetch ' + url);
    const json = (status, body) => ({ status, ok: status < 300, json: async () => body });
    if (url === '/ticks.json') {
      return json(200, TICKS);
    }
    if (url === '/api/v1/bootstrap') {
      assert.deepEqual(JSON.parse(init.body), { code: CODE });
      return json(200, { ok: true, token: TOKEN });
    }
    if (url === '/api/v1/command') {
      return json(200, { ok: true });
    }
    if (url === '/api/v1/stream') {
      streams += 1;
      if (streams > 1 || shutdown) {
        refused += 1;
        return { status: 401, ok: false, body: null };
      }
      const read = async () => {
        while (chunks.length === 0 && !released) {
          delivered = true;
          await new Promise((resolve) => { wake = resolve; });     // open until the test pushes or releases
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
    history: { replaceState: (state, title, url) => { events.push('replaceState ' + url); location.hash = ''; } },
    fetch: fetchImpl,
    crypto: { getRandomValues: (bytes) => bytes.fill(7) },
    performance: { now: () => 1000 },
    requestAnimationFrame: (fn) => animation.push(fn),
    setInterval: () => 1,
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    matchMedia: () => ({ addEventListener: () => {} }),
    devicePixelRatio: 2,
  };
  try {
    await import('../app.js');
    assert.equal(events[0], 'replaceState /', 'the fragment is stripped before any request');
    assert.equal(location.hash, '');

    await until(() => requests.some((r) => r.url === '/api/v1/stream'), 'the stream request');
    const boot = requests.find((r) => r.url === '/api/v1/bootstrap');
    assert.equal(boot.init.method, 'POST');
    assert.equal(boot.init.headers['Content-Type'], 'application/json');
    const stream = requests.find((r) => r.url === '/api/v1/stream');
    assert.equal(stream.init.headers.Authorization, 'Bearer ' + TOKEN);

    await until(() => delivered && animation.length > 0 && byId.get('ladder').width === 480, 'a frame and the ladder');
    while (animation.length) {
      animation.shift()();
    }
    assert.equal(byId.get('market-name').textContent, 'Synthetic Park 14:00');
    assert.equal(byId.get('market-status').textContent, 'OPEN');
    assert.equal(byId.get('market-status').hidden, false);
    assert.equal(byId.get('badge-inplay').hidden, true);
    assert.equal(byId.get('badge-synthetic').textContent, 'SYNTHETIC DATA');
    assert.equal(byId.get('countdown').textContent, 'T-10:00');
    assert.equal(byId.get('play').textContent, 'Play');
    assert.equal(byId.get('paused-reason').textContent, 'paused: not_started');
    assert.equal(byId.get('clock').textContent, 'replay 13:50:00 UTC, 1x');
    assert.equal(speeds[0].getAttribute('aria-pressed'), 'true');
    const rows = byId.get('grid-body').children;
    assert.equal(rows.length, 2);
    assert.ok(rows[0].textContent.includes('Synthetic 1'));
    assert.ok(rows[0].classList.contains('selected'));
    assert.equal(byId.get('ladder-runner').textContent, 'Synthetic 1');
    assert.ok(byId.get('ladder').drawCalls > 0, 'the ladder was drawn');
    assert.ok(byId.get('help-list').children.length > 0);
    assert.equal(byId.get('play').disabled, false);
    assert.equal(byId.get('conn').textContent, 'connected');
    const visible = () => [...byId.values()].map((el) => el.textContent).join(' ');
    assert.equal(/\blive\b/i.test(visible()), false, 'the page never says live (DESIGN.md 8.4)');

    byId.get('play').fire('click');
    byId.get('seed').value = '42';
    byId.get('open').fire('click');
    speeds[2].fire('click');
    const prevented = doc.fire('keydown', { key: 'q', target: doc.body });
    assert.equal(prevented, true);
    assert.equal(doc.fire('keydown', { key: 'q', target: byId.get('seed') }), false, 'typing is not a key command');
    byId.get('grid-body').fire('click', { target: rows[1].children[0] });
    await until(() => requests.filter((r) => r.url === '/api/v1/command').length === 4, 'four commands');
    const commands = requests.filter((r) => r.url === '/api/v1/command').map((r) => JSON.parse(r.init.body));
    assert.deepEqual(commands.map((c) => [c.command, c.args]), [
      ['play', {}], ['open_market', { seed: 42 }], ['set_speed', { speed_x100: 500 }], ['stop', {}],
    ]);
    commands.forEach((c) => assert.match(c.nonce, /^[0-9a-f]{32}$/));
    while (animation.length) {
      animation.shift()();
    }
    assert.equal(byId.get('ladder-runner').textContent, 'Synthetic 2', 'a row click selects its ladder');

    // Pause unless watched (DESIGN.md 8.6, I-19): hiding the page sends one pause, only while the clock runs.
    const commandCount = () => requests.filter((r) => r.url === '/api/v1/command').length;
    const hide = async () => {
      doc.visibilityState = 'hidden';
      doc.fire('visibilitychange');
      for (let i = 0; i < 20; i += 1) {
        await tick();
      }
      doc.visibilityState = 'visible';
      doc.fire('visibilitychange');
    };
    await hide();
    assert.equal(commandCount(), 4, 'already paused: hiding sends nothing');
    push([frame(3, false)]);
    await until(() => animation.length > 0, 'the playing frame');
    while (animation.length) {
      animation.shift()();
    }
    assert.equal(byId.get('play').textContent, 'Pause', 'the clock runs');
    await hide();
    await until(() => commandCount() === 5, 'the pause sent on hiding');
    const sent = JSON.parse(requests.filter((r) => r.url === '/api/v1/command')[4].init.body);
    assert.deepEqual([sent.command, sent.args], ['pause', {}]);
    assert.match(sent.nonce, /^[0-9a-f]{32}$/);
    for (let i = 0; i < 20; i += 1) {
      await tick();
    }
    assert.equal(commandCount(), 5, 'exactly one pause per hiding');

    release();                            // the stream ends; the reconnect is answered 401
    await until(() => byId.get('conn').textContent === 'session ended, run suite open again', 'the 401');
    assert.equal(byId.get('play').disabled, true);
    assert.equal(byId.get('seed').disabled, true);
    await hide();
    assert.equal(commandCount(), 5, 'after the session ended, hiding sends nothing');
    assert.equal(/\blive\b/i.test(visible()), false);

    const shown = [...byId.values()].map((el) => el.textContent + JSON.stringify(el.attributes)).join(' ');
    assert.equal(shown.includes(TOKEN), false, 'the token is never put in the page');
    assert.equal(shown.includes(CODE), false, 'nor is the bootstrap code');
    assert.equal(location.hash, '');
  } finally {
    // Even after a failed assertion: end the held stream and answer every later stream request 401, so
    // the app's client stops for good and this process (it runs only this file) can exit. The fake
    // globals stay: removing them would turn the client's next request into a retried network error.
    shutdown = true;
    release();
  }
  assert.ok(refused >= 1);
});
