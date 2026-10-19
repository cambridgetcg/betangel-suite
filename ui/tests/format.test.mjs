// Formatters take integer pence, hundredths and milliseconds only, and never do float arithmetic.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  formatClockUtc, formatCountdown, formatMoney, formatPounds, formatPrice, formatSize, formatSpeed, idiv,
  invalidReasonText, isSyntheticMarketId, safeCode,
} from '../format.js';

const NOT_INTEGERS = [2.5, 0.1, NaN, Infinity, -Infinity, '250', null, undefined, true, 2 ** 53, [250], { v: 250 }];

test('every formatter refuses a value that is not a safe integer', () => {
  for (const format of [formatPrice, formatSize, formatMoney, formatPounds, formatSpeed, formatClockUtc]) {
    for (const value of NOT_INTEGERS) {
      assert.throws(() => format(value), TypeError, format.name + ' ' + String(value));
    }
  }
  for (const value of NOT_INTEGERS.filter((v) => v !== null && v !== undefined)) {
    assert.throws(() => formatCountdown(value, false), TypeError, String(value));
  }
});

test('idiv is exact floor division of non-negative integers', () => {
  assert.equal(idiv(345, 100), 3);
  assert.equal(idiv(300, 100), 3);
  assert.equal(idiv(99, 100), 0);
  assert.equal(idiv(2 ** 53 - 1, 100), 90071992547409);
  assert.throws(() => idiv(-1, 100), RangeError);
  assert.throws(() => idiv(1, 0), RangeError);
});

test('prices in hundredths read as Betfair shows them', () => {
  const cases = [[101, '1.01'], [110, '1.1'], [200, '2'], [250, '2.5'], [345, '3.45'], [1000, '10'], [1050, '10.5'],
    [2000, '20'], [100000, '1000']];
  for (const [priceH, text] of cases) {
    assert.equal(formatPrice(priceH), text);
  }
  assert.throws(() => formatPrice(0), RangeError);
  assert.throws(() => formatPrice(-250), RangeError);
});

test('sizes in pence show as whole pounds, half up', () => {
  const cases = [[0, '0'], [40, '<1'], [49, '<1'], [50, '1'], [149, '1'], [150, '2'], [1234, '12'], [9999949, '99999'],
    [9999950, '100k'], [12300000, '123k']];
  for (const [sizeP, text] of cases) {
    assert.equal(formatSize(sizeP), text, String(sizeP));
  }
  assert.throws(() => formatSize(-1), RangeError);
});

test('exact money keeps every penny, with grouping and sign', () => {
  assert.equal(formatMoney(0), '£0.00');
  assert.equal(formatMoney(5), '£0.05');
  assert.equal(formatMoney(120), '£1.20');
  assert.equal(formatMoney(123456), '£1,234.56');
  assert.equal(formatMoney(100000000), '£1,000,000.00');
  assert.equal(formatMoney(-5), '-£0.05');
  assert.equal(formatMoney(-123456), '-£1,234.56');
  assert.equal(formatPounds(1234550), '£12,346');
  assert.equal(formatPounds(49), '£0');
  assert.equal(formatPounds(0), '£0');
  assert.throws(() => formatPounds(-1), RangeError);
});

test('speeds in hundredths', () => {
  assert.equal(formatSpeed(100), '1x');
  assert.equal(formatSpeed(25), '0.25x');
  assert.equal(formatSpeed(50), '0.5x');
  assert.equal(formatSpeed(150), '1.5x');
  assert.equal(formatSpeed(1000), '10x');
  assert.equal(formatSpeed(6000), '60x');
  assert.throws(() => formatSpeed(0), RangeError);
});

test('the countdown rounds up before the off and marks the last minute', () => {
  assert.deepEqual(formatCountdown(598000, false), { text: 'T-09:58', level: 'normal' });
  assert.deepEqual(formatCountdown(60000, false), { text: 'T-01:00', level: 'normal' });
  assert.deepEqual(formatCountdown(59999, false), { text: 'T-01:00', level: 'soon' });
  assert.deepEqual(formatCountdown(30000, false), { text: 'T-00:30', level: 'soon' });
  assert.deepEqual(formatCountdown(29999, false), { text: 'T-00:30', level: 'imminent' });
  assert.deepEqual(formatCountdown(1, false), { text: 'T-00:01', level: 'imminent' });
  assert.deepEqual(formatCountdown(0, false), { text: 'T-00:00', level: 'imminent' });
  assert.deepEqual(formatCountdown(3723000, false), { text: 'T-1:02:03', level: 'normal' });
  assert.deepEqual(formatCountdown(-5000, false), { text: 'T+00:05', level: 'past' });
  assert.deepEqual(formatCountdown(-12500, true), { text: 'IN-PLAY +00:12', level: 'inplay' });
  assert.deepEqual(formatCountdown(5000, true), { text: 'IN-PLAY +00:00', level: 'inplay' });
  assert.deepEqual(formatCountdown(null, false), { text: 'T --:--', level: 'unknown' });
  assert.deepEqual(formatCountdown(null, true), { text: 'IN-PLAY', level: 'inplay' });
});

test('publisher time shows as a UTC time of day', () => {
  assert.equal(formatClockUtc(1433167200000), '14:00:00');
  assert.equal(formatClockUtc(1433167199999), '13:59:59');
  assert.equal(formatClockUtc(0), '00:00:00');
  assert.throws(() => formatClockUtc(-1), RangeError);
});

test('codes, the synthetic namespace and invalid reasons', () => {
  assert.equal(safeCode('not_implemented'), 'not_implemented');
  assert.equal(safeCode('Not A Code'), 'unlisted_code');
  assert.equal(safeCode(7), 'unlisted_code');
  assert.equal(isSyntheticMarketId('1.999000001'), true);
  assert.equal(isSyntheticMarketId('1.99900001'), false);
  assert.equal(isSyntheticMarketId('1.9990000011'), false);
  assert.equal(isSyntheticMarketId('2.999000001'), false);
  assert.equal(isSyntheticMarketId(1.999), false);
  assert.equal(invalidReasonText(null), '');
  assert.equal(invalidReasonText('non_finite_size'), 'book invalid: non-finite size');
  assert.equal(invalidReasonText('stream_unreliable'), '503: data possibly stale');
  assert.equal(invalidReasonText('crossed_book'), 'book invalid: crossed_book');
  assert.equal(invalidReasonText('<b>x</b>'), 'book invalid: unlisted_code');
});

test('format.js has no float parsing or rounding helpers', () => {
  const source = readFileSync(new URL('../format.js', import.meta.url), 'utf8');
  for (const banned of ['parseFloat', 'toFixed', 'toPrecision', 'Math.round', 'Math.floor', 'Math.ceil', 'Math.trunc',
    'Intl.NumberFormat', 'toLocaleString']) {
    assert.equal(source.includes(banned), false, banned);
  }
});
