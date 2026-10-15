// The key map has no conflicts, every key maps to a handled action, and the pure helpers of app.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  ACTIONS, CONNECTION_TEXT, KEYMAP, SPEEDS_X100, chooseRunner, keyAction, makeHandlers, nextSpeed, parseSeed,
  stepRunner,
} from '../app.js';
import { SESSION_ENDED } from '../stream.js';

// Words the page never shows: LIVE is reserved as a data-source label (DESIGN.md 8.4) and this page only
// replays; the rest are the route and command names of DESIGN.md 9.1 that must never exist.
const BANNED_WORDS = /\b(?:live|account|funds|login|kill|upload|share)\b/i;

// Keys DESIGN.md 8.3 reserves for later phases (jump, step, races, stakes, paper orders, Tab, Escape).
const RESERVED = ['j', 'J', '[', ']', '.', 'r', 'R', 'n', 'N', 'Tab', '1', '2', '3', '4', '5', 'b', 'B', 'a', 'A',
  'Escape', 'z', 'Z', 'x', 'X', 'c', 'C', 'Enter'];

test('every key maps to exactly one action', () => {
  const seen = new Map();
  for (const entry of KEYMAP) {
    assert.equal(seen.has(entry.key), false, 'duplicate key ' + JSON.stringify(entry.key));
    seen.set(entry.key, entry.action);
  }
  // Keys that differ only by case must agree (Shift must not change what a letter does).
  for (const [key, action] of seen) {
    if (key.length === 1 && key.toLowerCase() !== key.toUpperCase()) {
      const other = key === key.toLowerCase() ? key.toUpperCase() : key.toLowerCase();
      if (seen.has(other)) {
        assert.equal(seen.get(other), action, key);
      }
    }
  }
});

test('the key map uses no key reserved for later phases', () => {
  for (const entry of KEYMAP) {
    assert.equal(RESERVED.includes(entry.key), false, entry.key);
  }
});

test('every key names a known action, and every action has a key and a handler', () => {
  const calls = [];
  const ctx = new Proxy({}, {
    get: (target, name) => (...args) => {
      calls.push(name);
      return name === 'currentSpeed' ? 100 : undefined;
    },
  });
  const handlers = makeHandlers(ctx);
  assert.deepEqual(Object.keys(handlers).sort(), [...ACTIONS].sort());
  for (const entry of KEYMAP) {
    assert.ok(ACTIONS.includes(entry.action), entry.action);
    assert.equal(typeof entry.label, 'string');
    assert.equal(typeof entry.help, 'string');
  }
  for (const action of ACTIONS) {
    assert.ok(KEYMAP.some((entry) => entry.action === action), 'no key for ' + action);
    const before = calls.length;
    handlers[action]();
    assert.ok(calls.length > before, action + ' calls into the app');
  }
});

test('modified keys belong to the browser', () => {
  assert.equal(keyAction({ key: ' ' }), 'toggle_play');
  assert.equal(keyAction({ key: 'q' }), 'stop');
  assert.equal(keyAction({ key: 'q', metaKey: true }), null);
  assert.equal(keyAction({ key: 'l', ctrlKey: true }), null);
  assert.equal(keyAction({ key: '+', altKey: true }), null);
  assert.equal(keyAction({ key: 'k' }), null);
});

test('speed steps follow the engine speeds, 0.25x to 60x, and never go the wrong way', () => {
  assert.deepEqual([...SPEEDS_X100], [25, 50, 100, 200, 500, 1000, 3000, 6000]);
  assert.equal(nextSpeed(100, 1), 200);
  assert.equal(nextSpeed(500, 1), 1000);
  assert.equal(nextSpeed(1000, 1), 3000);
  assert.equal(nextSpeed(6000, 1), 6000);
  assert.equal(nextSpeed(100, -1), 50);
  assert.equal(nextSpeed(25, -1), 25);
  assert.equal(nextSpeed(500, -1), 200);
  assert.equal(nextSpeed(6000, -1), 3000);
  assert.equal(nextSpeed(300, 1), 500);
  assert.equal(nextSpeed(300, -1), 200);
  assert.equal(nextSpeed(10, 1), 25);
  assert.equal(nextSpeed(9000, -1), 6000);
  for (const speed of SPEEDS_X100) {
    assert.ok(nextSpeed(speed, 1) >= speed && nextSpeed(speed, -1) <= speed, String(speed));
  }
});

test('a seed is 1 to 9 digits and nothing else', () => {
  assert.equal(parseSeed('42'), 42);
  assert.equal(parseSeed(' 7 '), 7);
  assert.equal(parseSeed('007'), 7);
  assert.equal(parseSeed('999999999'), 999999999);
  for (const bad of ['', ' ', '1.5', '-1', '+1', '1e3', '0x10', '1234567890', 'seven', null, 7]) {
    assert.equal(parseSeed(bad), null, String(bad));
  }
});

test('runner selection keeps the current runner, else the first active one', () => {
  const runners = [
    { id: 90000001, status: 'REMOVED' }, { id: 90000002, status: 'ACTIVE' }, { id: 90000003, status: 'ACTIVE' },
  ];
  assert.equal(chooseRunner(runners, 90000003), 90000003);
  assert.equal(chooseRunner(runners, 90000009), 90000002);
  assert.equal(chooseRunner(runners, null), 90000002);
  assert.equal(chooseRunner([{ id: 90000001, status: 'REMOVED' }], null), 90000001);
  assert.equal(chooseRunner([], 90000001), null);
  assert.equal(stepRunner(runners, 90000002, 1), 90000003);
  assert.equal(stepRunner(runners, 90000003, 1), 90000003);
  assert.equal(stepRunner(runners, 90000001, -1), 90000001);
  assert.equal(stepRunner(runners, 90000009, 1), 90000001);
  assert.equal(stepRunner([], null, 1), null);
});

test('the page shows no live or account wording: connection states, key help and the static page', () => {
  assert.deepEqual(Object.keys(CONNECTION_TEXT).sort(), ['connected', 'connecting', 'reconnecting', 'session_ended']);
  assert.equal(CONNECTION_TEXT.connected, 'connected');
  assert.equal(CONNECTION_TEXT.session_ended, SESSION_ENDED);
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const pageText = html.replace(/<[^>]*>/g, ' ');           // the visible text, without tags or attributes
  const shown = [...Object.values(CONNECTION_TEXT), ...KEYMAP.flatMap((entry) => [entry.label, entry.help]), pageText];
  for (const text of shown) {
    assert.equal(BANNED_WORDS.test(text), false, text);
  }
  assert.equal(BANNED_WORDS.test('stream: live'), true, 'the check catches the word');
});
