// The tick map against ticks.json (exported from rx.ticks.LADDER_CLASSIC), and the ladder's geometry.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  HEIGHT_PX, ROW_PX, VISIBLE_ROWS, WIDTH_PX, createLadder, indexOfRow, ladderRows, ladderWindow, makeTickMap,
  nextCentre, referenceIndex, rowOfIndex,
} from '../ladder.js';
import { formatPrice } from '../format.js';

const DOC = JSON.parse(readFileSync(new URL('../ticks.json', import.meta.url), 'utf8'));
const MAP = makeTickMap(DOC);

// The CLASSIC bands as documented by Betfair: [from, to) in hundredths and the step within each band.
const BANDS = [
  [101, 200, 1], [200, 300, 2], [300, 400, 5], [400, 600, 10], [600, 1000, 20], [1000, 2000, 50],
  [2000, 3000, 100], [3000, 5000, 200], [5000, 10000, 500], [10000, 100000, 1000],
];

function runner(fields) {
  return { id: 90000001, name: 'Synthetic 1', status: 'ACTIVE', ltp_h: null, tv_p: 0, back: [], lay: [], ...fields };
}

test('ticks.json is the 350-tick CLASSIC ladder in integer hundredths', () => {
  assert.equal(DOC.schema_version, 1);
  assert.equal(DOC.ladder, 'CLASSIC');
  assert.equal(DOC.unit, 'hundredths');
  assert.equal(DOC.count, 350);
  assert.equal(MAP.count, 350);
  assert.equal(MAP.priceAt(0), 101);
  assert.equal(MAP.priceAt(349), 100000);
  for (const tick of DOC.ticks) {
    assert.ok(Number.isSafeInteger(tick), 'every tick is an integer');
  }
});

test('the tick map equals the documented band expansion', () => {
  const expected = [];
  for (const [low, high, step] of BANDS) {
    for (let price = low; price < high; price += step) {
      expected.push(price);
    }
  }
  expected.push(100000);
  assert.deepEqual(Array.from(MAP.ticks), expected);
});

test('indexOf and priceAt are inverse, and off-ladder prices are not found', () => {
  MAP.ticks.forEach((price, i) => {
    assert.equal(MAP.indexOf(price), i);
    assert.equal(MAP.priceAt(i), price);
  });
  for (const off of [100, 201, 303, 1010, 100001, 0, -101]) {
    assert.equal(MAP.indexOf(off), -1, String(off));
  }
  assert.equal(MAP.indexOf(2.5), -1);
  assert.equal(MAP.indexOf('250'), -1);
  assert.throws(() => MAP.priceAt(-1), RangeError);
  assert.throws(() => MAP.priceAt(350), RangeError);
  assert.throws(() => MAP.priceAt(1.5), RangeError);
});

test('snapping is explicit and stays on the ladder', () => {
  assert.equal(MAP.priceAt(MAP.snapIndex(201, 'down')), 200);
  assert.equal(MAP.priceAt(MAP.snapIndex(201, 'up')), 202);
  assert.equal(MAP.priceAt(MAP.snapIndex(250, 'down')), 250);
  assert.equal(MAP.priceAt(MAP.snapIndex(250, 'up')), 250);
  assert.equal(MAP.snapIndex(100, 'down'), -1);
  assert.equal(MAP.priceAt(MAP.snapIndex(100, 'up')), 101);
  assert.equal(MAP.snapIndex(100001, 'up'), -1);
  assert.equal(MAP.priceAt(MAP.snapIndex(100001, 'down')), 100000);
  assert.throws(() => MAP.snapIndex(2.01, 'down'), TypeError);
  assert.throws(() => MAP.snapIndex(201, 'nearest'), RangeError);
});

test('offset moves whole ticks and refuses to leave the ladder', () => {
  assert.equal(MAP.offset(200, 1), 202);
  assert.equal(MAP.offset(200, -1), 199);
  assert.equal(MAP.offset(1000, 1), 1050);
  assert.equal(MAP.offset(101, -1), null);
  assert.equal(MAP.offset(100000, 1), null);
  assert.equal(MAP.offset(201, 1), null);
});

test('makeTickMap refuses anything but ascending integer ticks', () => {
  assert.throws(() => makeTickMap([101, 101.5]), TypeError);
  assert.throws(() => makeTickMap([102, 101]), TypeError);
  assert.throws(() => makeTickMap([101, 101]), TypeError);
  assert.throws(() => makeTickMap([]), TypeError);
  assert.throws(() => makeTickMap({ ...DOC, ladder: 'FINEST' }), TypeError);
  assert.throws(() => makeTickMap({ ...DOC, unit: 'decimal' }), TypeError);
  assert.throws(() => makeTickMap({ ...DOC, count: 349 }), TypeError);
  assert.throws(() => makeTickMap(null), TypeError);
});

test('every tick formats to text that reads back as the same integer', () => {
  for (const tick of MAP.ticks) {
    const [whole, frac = ''] = formatPrice(tick).split('.');
    assert.equal(Number(whole) * 100 + Number(frac.padEnd(2, '0')), tick, formatPrice(tick));
  }
});

test('the ladder window is 35 rows of 18 px, clamped at both ends', () => {
  assert.equal(ROW_PX, 18);
  assert.equal(VISIBLE_ROWS, 35);
  assert.equal(HEIGHT_PX, 630);
  assert.deepEqual(ladderWindow(350, 100), { top: 117, bottom: 83, rows: 35 });
  assert.deepEqual(ladderWindow(350, 0), { top: 34, bottom: 0, rows: 35 });
  assert.deepEqual(ladderWindow(350, 5), { top: 34, bottom: 0, rows: 35 });
  assert.deepEqual(ladderWindow(350, 349), { top: 349, bottom: 315, rows: 35 });
  assert.deepEqual(ladderWindow(350, 340), { top: 349, bottom: 315, rows: 35 });
  assert.deepEqual(ladderWindow(10, 4), { top: 9, bottom: 0, rows: 10 });
  assert.throws(() => ladderWindow(350, 1.5), RangeError);
  for (let centre = 0; centre < 350; centre += 7) {
    const win = ladderWindow(350, centre);
    assert.equal(win.top - win.bottom + 1, 35);
    assert.ok(win.bottom >= 0 && win.top <= 349);
  }
});

test('rows and tick indices convert both ways; higher prices are at the top', () => {
  const win = ladderWindow(350, 100);
  for (let row = 0; row < win.rows; row += 1) {
    assert.equal(rowOfIndex(win, indexOfRow(win, row)), row);
  }
  assert.equal(indexOfRow(win, 0), win.top);
  assert.equal(rowOfIndex(win, win.top + 1), -1);
  assert.equal(rowOfIndex(win, win.bottom - 1), -1);
  assert.equal(indexOfRow(win, 35), -1);
  assert.ok(MAP.priceAt(indexOfRow(win, 0)) > MAP.priceAt(indexOfRow(win, 34)));
});

test('the reference tick is the LTP, else the best back, else the best lay, else 2.0', () => {
  assert.equal(referenceIndex(MAP, runner({ ltp_h: 250, back: [[248, 100]], lay: [[252, 100]] })), MAP.indexOf(250));
  assert.equal(referenceIndex(MAP, runner({ back: [[248, 100]], lay: [[252, 100]] })), MAP.indexOf(248));
  assert.equal(referenceIndex(MAP, runner({ lay: [[252, 100]] })), MAP.indexOf(252));
  assert.equal(referenceIndex(MAP, runner({})), MAP.indexOf(200));
  assert.equal(referenceIndex(MAP, null), MAP.indexOf(200));
  assert.equal(referenceIndex(MAP, runner({ ltp_h: 201 })), MAP.indexOf(200));
});

test('the centre stays put inside the inner band and follows at the margin', () => {
  const win = ladderWindow(350, 100);
  assert.equal(nextCentre(null, null, 120), 120);
  assert.equal(nextCentre(100, win, 100), 100);
  assert.equal(nextCentre(100, win, win.top - 4), 100);
  assert.equal(nextCentre(100, win, win.bottom + 4), 100);
  assert.equal(nextCentre(100, win, win.top - 3), win.top - 3);
  assert.equal(nextCentre(100, win, win.bottom + 3), win.bottom + 3);
});

test('ladder rows place the best three levels and the LTP on their ticks', () => {
  const r = runner({ ltp_h: 250, back: [[248, 1234], [246, 500], [244, 40]], lay: [[250, 900], [252, 100], [254, 7]] });
  const win = ladderWindow(MAP.count, MAP.indexOf(250));
  const rows = ladderRows(MAP, win, r);
  assert.equal(rows.length, 35);
  assert.equal(rows[0].priceH, MAP.priceAt(win.top));
  const at = (priceH) => rows.find((row) => row.priceH === priceH);
  assert.equal(at(248).back, 1234);
  assert.equal(at(248).bestBack, true);
  assert.equal(at(244).back, 40);
  assert.equal(at(250).lay, 900);
  assert.equal(at(250).bestLay, true);
  assert.equal(at(250).ltp, true);
  assert.equal(at(252).ltp, false);
  assert.equal(at(242).back, null);
  assert.equal(rows.filter((row) => row.back !== null).length, 3);
  assert.equal(rows.filter((row) => row.lay !== null).length, 3);
});

function fakeCanvas() {
  const calls = [];
  const ctx = new Proxy({}, {
    get(target, name) {
      if (name in target) {
        return target[name];
      }
      return (...args) => calls.push([name, ...args]);
    },
    set(target, name, value) {
      target[name] = value;
      return true;
    },
  });
  return { calls, canvas: { width: 0, height: 0, getContext: () => ctx } };
}

test('the canvas is sized for the device ratio and redrawn only when something changed', () => {
  const { calls, canvas } = fakeCanvas();
  const ladder = createLadder(canvas, MAP, { dpr: 2 });
  assert.equal(canvas.width, WIDTH_PX * 2);
  assert.equal(canvas.height, HEIGHT_PX * 2);
  const r = runner({ ltp_h: 250, back: [[248, 1234]], lay: [[252, 100]] });
  ladder.show(r);
  assert.equal(ladder.draw(), true);
  assert.equal(ladder.draw(), false, 'no new frame: no redraw');
  const texts = calls.filter((call) => call[0] === 'fillText').map((call) => call[1]);
  assert.ok(texts.includes('2.5'));
  assert.ok(texts.includes('12'));
  assert.ok(texts.every((text) => !/\d\.\d{3,}/.test(text)), 'no float artefacts');
  ladder.show({ ...r, ltp_h: 248 });
  assert.equal(ladder.draw(), true);
});

test('the ladder keeps its place while the LTP moves inside the band, and L recentres', () => {
  const { canvas } = fakeCanvas();
  const ladder = createLadder(canvas, MAP);
  ladder.show(runner({ ltp_h: 250 }));
  const first = ladder.window();
  ladder.show(runner({ ltp_h: 252 }));
  assert.deepEqual(ladder.window(), first);
  ladder.scroll(5);
  const scrolled = ladder.window();
  assert.ok(scrolled.top > first.top);
  ladder.show(runner({ ltp_h: 252 }));
  assert.deepEqual(ladder.window(), scrolled, 'a manual scroll is kept until L');
  ladder.centreOnLtp();
  assert.equal(ladder.window().top, MAP.indexOf(252) + 17);
  ladder.show(runner({ id: 90000002, ltp_h: 1000 }));
  assert.equal(ladder.window().top, MAP.indexOf(1000) + 17, 'another runner recentres');
});
