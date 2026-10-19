// The price ladder for the selected runner, drawn on a canvas (DESIGN.md 8.2, 8.5).
//
// Rows are the engine's own CLASSIC ticks, loaded from ticks.json (exported from
// rx.ticks.LADDER_CLASSIC by tools/export_ticks.py), so the browser never computes a tick from a
// float. Fixed 18 px rows, 35 visible, higher prices at the top; columns are available to back, price
// and available to lay. Phase 0b shows the best three levels each side and marks the LTP; full depth,
// traded volume per price and our orders come in Phase 1a and 1b. The canvas is redrawn only when
// something new arrived (draw() returns false otherwise), from requestAnimationFrame in app.js.

import { formatPrice, formatSize } from './format.js';

export const ROW_PX = 18;
export const VISIBLE_ROWS = 35;
export const WIDTH_PX = 240;
export const HEIGHT_PX = ROW_PX * VISIBLE_ROWS;
export const COLUMNS = Object.freeze({ back: [0, 88], price: [88, 152], lay: [152, 240] });
export const RECENTRE_MARGIN = 4;
const DEFAULT_CENTRE_PRICE_H = 200;
const SCROLL_TICKS = 3;

// --- the tick map -----------------------------------------------------------------------------------

// The ticks.json document (or its ticks array) as a lookup: index of a price, price at an index, and
// explicit snapping. Refuses anything but strictly ascending positive integers.
export function makeTickMap(source) {
  const ticks = Array.isArray(source) ? source : source && source.ticks;
  if (!Array.isArray(source)) {
    if (source === null || typeof source !== 'object' || source.ladder !== 'CLASSIC' || source.unit !== 'hundredths'
        || source.count !== (Array.isArray(ticks) ? ticks.length : -1)) {
      throw new TypeError('ticks.json is not the CLASSIC ladder in hundredths');
    }
  }
  if (!Array.isArray(ticks) || ticks.length === 0) {
    throw new TypeError('ticks must be a non-empty array');
  }
  for (let i = 0; i < ticks.length; i += 1) {
    if (!Number.isSafeInteger(ticks[i]) || ticks[i] <= 0 || (i > 0 && ticks[i] <= ticks[i - 1])) {
      throw new TypeError('ticks must be strictly ascending positive integers');
    }
  }
  const list = Object.freeze(ticks.slice());
  const index = new Map(list.map((price, i) => [price, i]));

  // The index of the last tick at or below priceH ("down") or the first at or above it ("up"), or -1.
  function snapIndex(priceH, direction) {
    if (!Number.isSafeInteger(priceH)) {
      throw new TypeError('price must be integer hundredths');
    }
    let lo = 0;
    let hi = list.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (list[mid] < priceH) {
        lo = mid + 1;
      } else {
        hi = mid;
      }
    }
    if (direction === 'up') {
      return lo < list.length ? lo : -1;
    }
    if (direction === 'down') {
      return lo < list.length && list[lo] === priceH ? lo : lo - 1;
    }
    throw new RangeError('direction must be "up" or "down"');
  }

  return Object.freeze({
    ticks: list,
    count: list.length,
    indexOf(priceH) {
      const found = index.get(priceH);
      return found === undefined ? -1 : found;
    },
    priceAt(i) {
      if (!Number.isSafeInteger(i) || i < 0 || i >= list.length) {
        throw new RangeError('tick index out of range');
      }
      return list[i];
    },
    snapIndex: snapIndex,
    // The price n ticks above (n > 0) or below (n < 0) priceH, or null off the ladder.
    offset(priceH, n) {
      const at = index.get(priceH);
      if (at === undefined || !Number.isSafeInteger(n) || at + n < 0 || at + n >= list.length) {
        return null;
      }
      return list[at + n];
    },
  });
}

// --- geometry ---------------------------------------------------------------------------------------

// The visible window around a centre tick index: top is the highest index shown (row 0), bottom the
// lowest. Clamped to the ladder, so the window never shows rows past either end.
export function ladderWindow(count, centre, rows = VISIBLE_ROWS) {
  if (!Number.isSafeInteger(count) || count <= 0 || !Number.isSafeInteger(centre) || !Number.isSafeInteger(rows)
      || rows <= 0) {
    throw new RangeError('bad ladder window arguments');
  }
  const shown = rows < count ? rows : count;
  const half = (shown - (shown % 2)) / 2;
  let top = centre + half;
  if (top > count - 1) {
    top = count - 1;
  }
  let bottom = top - shown + 1;
  if (bottom < 0) {
    bottom = 0;
    top = shown - 1;
  }
  return { top: top, bottom: bottom, rows: shown };
}

export function rowOfIndex(win, index) {
  return index > win.top || index < win.bottom ? -1 : win.top - index;
}

export function indexOfRow(win, row) {
  return row < 0 || row >= win.rows ? -1 : win.top - row;
}

// The tick to centre on for a runner: its LTP, else its best back, else its best lay, else 2.0.
export function referenceIndex(map, runner) {
  const candidates = [];
  if (runner) {
    if (runner.ltp_h !== null) {
      candidates.push(runner.ltp_h);
    }
    if (runner.back.length > 0) {
      candidates.push(runner.back[0][0]);
    }
    if (runner.lay.length > 0) {
      candidates.push(runner.lay[0][0]);
    }
  }
  for (const priceH of candidates) {
    const exact = map.indexOf(priceH);
    if (exact !== -1) {
      return exact;
    }
    const near = map.snapIndex(priceH, 'down');
    if (near !== -1) {
      return near;
    }
  }
  const fallback = map.indexOf(DEFAULT_CENTRE_PRICE_H);
  return fallback !== -1 ? fallback : (map.count - (map.count % 2)) / 2;
}

// Keep the ladder still while the reference tick stays inside the window's inner band; move it only
// when the reference reaches the outer margin, so the rows do not jump on every frame.
export function nextCentre(current, win, refIndex, margin = RECENTRE_MARGIN) {
  if (current === null || win === null) {
    return refIndex;
  }
  if (refIndex <= win.top - margin && refIndex >= win.bottom + margin) {
    return current;
  }
  return refIndex;
}

// One model row per visible tick, top to bottom: price, back and lay sizes at that price (best three
// levels only), and whether it is the LTP or a best price.
export function ladderRows(map, win, runner) {
  const back = new Map();
  const lay = new Map();
  if (runner) {
    runner.back.forEach(([priceH, sizeP]) => back.set(priceH, sizeP));
    runner.lay.forEach(([priceH, sizeP]) => lay.set(priceH, sizeP));
  }
  const bestBack = runner && runner.back.length > 0 ? runner.back[0][0] : null;
  const bestLay = runner && runner.lay.length > 0 ? runner.lay[0][0] : null;
  const ltp = runner ? runner.ltp_h : null;
  const rows = [];
  for (let row = 0; row < win.rows; row += 1) {
    const priceH = map.priceAt(win.top - row);
    rows.push({
      priceH: priceH,
      back: back.has(priceH) ? back.get(priceH) : null,
      lay: lay.has(priceH) ? lay.get(priceH) : null,
      ltp: priceH === ltp,
      bestBack: priceH === bestBack,
      bestLay: priceH === bestLay,
    });
  }
  return rows;
}

// --- drawing ----------------------------------------------------------------------------------------

export const DEFAULT_PALETTE = Object.freeze({
  background: '#ffffff', grid: '#d9dde3', text: '#1b1f24', muted: '#8a94a3',
  back: '#cfe6ff', backBest: '#7fbfff', lay: '#ffd9e0', layBest: '#ff9fb2', ltp: '#ffe680',
});

// A ladder bound to one canvas. readPalette() returns colours (CSS custom properties, read by app.js);
// dpr is the integer device-pixel ratio for crisp lines.
export function createLadder(canvas, map, { readPalette = () => DEFAULT_PALETTE, dpr = 1 } = {}) {
  const scale = Number.isSafeInteger(dpr) && dpr > 0 ? dpr : 1;
  canvas.width = WIDTH_PX * scale;
  canvas.height = HEIGHT_PX * scale;
  const ctx = canvas.getContext('2d');
  let runner = null;
  let runnerId = null;
  let centre = null;
  let win = null;
  let dirty = true;
  let manual = false;             // scrolled by hand: stay put until L or another runner

  function place(recentre) {
    if (recentre) {
      manual = false;
    }
    if (manual && win !== null) {
      return;
    }
    const ref = referenceIndex(map, runner);
    centre = recentre ? ref : nextCentre(centre, win, ref);
    win = ladderWindow(map.count, centre);
  }

  function cell(x0, x1, y, fill, text, align, bold, palette) {
    if (fill !== null) {
      ctx.fillStyle = fill;
      ctx.fillRect(x0, y, x1 - x0, ROW_PX);
    }
    if (text !== '') {
      ctx.fillStyle = palette.text;
      ctx.font = (bold ? 'bold ' : '') + '12px ui-monospace, Menlo, monospace';
      ctx.textAlign = align;
      const x = align === 'right' ? x1 - 6 : align === 'left' ? x0 + 6 : (x0 + x1) / 2;
      ctx.fillText(text, x, y + ROW_PX / 2);
    }
  }

  return {
    // Show a runner (null for none). A different runner, or recentre, centres on its reference tick.
    show(next, { recentre = false } = {}) {
      const nextId = next ? next.id : null;
      const changed = nextId !== runnerId;
      runner = next;
      runnerId = nextId;
      place(recentre || changed);
      dirty = true;
    },
    centreOnLtp() {
      place(true);
      dirty = true;
    },
    // Scroll by whole ticks (positive: towards higher prices).
    scroll(steps) {
      if (win === null || !Number.isSafeInteger(steps) || steps === 0) {
        return;
      }
      const target = (centre === null ? referenceIndex(map, runner) : centre) + steps * SCROLL_TICKS;
      win = ladderWindow(map.count, target < 0 ? 0 : target > map.count - 1 ? map.count - 1 : target);
      centre = win.top - (win.rows - (win.rows % 2)) / 2;      // the window's real centre after clamping
      manual = true;
      dirty = true;
    },
    invalidate() {
      dirty = true;
    },
    window() {
      return win;
    },
    // Draw if something changed since the last draw; returns whether it drew.
    draw() {
      if (!dirty) {
        return false;
      }
      dirty = false;
      if (win === null) {
        place(true);
      }
      const palette = { ...DEFAULT_PALETTE, ...readPalette() };
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      ctx.fillStyle = palette.background;
      ctx.fillRect(0, 0, WIDTH_PX, HEIGHT_PX);
      ctx.textBaseline = 'middle';
      const rows = ladderRows(map, win, runner);
      rows.forEach((row, r) => {
        const y = r * ROW_PX;
        const backFill = row.back === null ? null : row.bestBack ? palette.backBest : palette.back;
        const layFill = row.lay === null ? null : row.bestLay ? palette.layBest : palette.lay;
        cell(COLUMNS.back[0], COLUMNS.back[1], y, backFill, row.back === null ? '' : formatSize(row.back), 'right',
          row.bestBack, palette);
        cell(COLUMNS.price[0], COLUMNS.price[1], y, row.ltp ? palette.ltp : null, formatPrice(row.priceH), 'center',
          row.ltp, palette);
        cell(COLUMNS.lay[0], COLUMNS.lay[1], y, layFill, row.lay === null ? '' : formatSize(row.lay), 'left',
          row.bestLay, palette);
        ctx.fillStyle = palette.grid;
        ctx.fillRect(0, y + ROW_PX - 1, WIDTH_PX, 1);
      });
      ctx.fillStyle = palette.grid;
      ctx.fillRect(COLUMNS.price[0], 0, 1, HEIGHT_PX);
      ctx.fillRect(COLUMNS.lay[0], 0, 1, HEIGHT_PX);
      if (runner === null) {
        ctx.fillStyle = palette.muted;
        ctx.font = '12px -apple-system, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('no runner selected', WIDTH_PX / 2, ROW_PX / 2);
      }
      return true;
    },
  };
}
