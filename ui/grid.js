// The one-click grid (DESIGN.md 8.2): one row per runner with the best three back and lay prices and
// sizes, the LTP and the traded volume. Rows are keyed by selection id and patched in place: a cell's
// text is written only when it changed, rows move only when the order changed, and rows of runners no
// longer in the frame are removed. Clicking a row selects that runner's ladder. Phase 0b has no paper
// orders, so clicking a price does nothing yet.

import { formatPounds, formatPrice, formatSize } from './format.js';

export const LEVELS = 3;

function level(levels, i) {
  return i < levels.length ? levels[i] : null;
}

function priceText(entry) {
  return entry === null ? '' : formatPrice(entry[0]);
}

function sizeText(entry) {
  return entry === null ? '' : formatSize(entry[1]);
}

// The texts one grid row shows. Back cells run worst to best (back3 back2 back1), so both best prices
// meet in the middle; lay cells run best to worst.
export function rowCells(runner) {
  const back = [];
  const lay = [];
  for (let i = 0; i < LEVELS; i += 1) {
    const b = level(runner.back, LEVELS - 1 - i);
    const l = level(runner.lay, i);
    back.push({ price: priceText(b), size: sizeText(b) });
    lay.push({ price: priceText(l), size: sizeText(l) });
  }
  return {
    name: runner.name,
    status: runner.status === 'ACTIVE' ? '' : runner.status,
    ltp: runner.ltp_h === null ? '' : formatPrice(runner.ltp_h),
    tv: formatPounds(runner.tv_p),
    back: back,
    lay: lay,
    removed: runner.status === 'REMOVED',
  };
}

// A grid bound to a <tbody>. doc is the document (injected so tests can use a small fake).
export function createGrid(tbody, doc, { onSelect = () => {} } = {}) {
  const rows = new Map();
  const stats = { writes: 0, created: 0, removed: 0, moved: 0 };

  function element(tag, className, parent) {
    const node = doc.createElement(tag);
    if (className) {
      node.className = className;
    }
    parent.appendChild(node);
    return node;
  }

  function slot(node) {
    return { node: node, text: '' };
  }

  function setText(target, text) {
    if (target.text !== text) {
      target.node.textContent = text;
      target.text = text;
      stats.writes += 1;
    }
  }

  function priceCell(tr, side) {
    const td = element('td', 'px ' + side, tr);
    return { price: slot(element('span', 'p', td)), size: slot(element('span', 's', td)) };
  }

  function createRow(id) {
    const tr = doc.createElement('tr');
    tr.dataset.id = String(id);
    const nameCell = element('td', 'name', tr);
    const view = {
      tr: tr,
      name: slot(element('span', 'n', nameCell)),
      status: slot(element('span', 'st', nameCell)),
      back: [],
      lay: [],
      ltp: null,
      tv: null,
      selected: null,
      removed: null,
    };
    for (let i = 0; i < LEVELS; i += 1) {
      view.back.push(priceCell(tr, 'back' + (i === LEVELS - 1 ? ' best' : '')));
    }
    for (let i = 0; i < LEVELS; i += 1) {
      view.lay.push(priceCell(tr, 'lay' + (i === 0 ? ' best' : '')));
    }
    view.ltp = slot(element('td', 'ltp', tr));
    view.tv = slot(element('td', 'tv', tr));
    stats.created += 1;
    return view;
  }

  function patch(view, cells, selected) {
    setText(view.name, cells.name);
    setText(view.status, cells.status);
    for (let i = 0; i < LEVELS; i += 1) {
      setText(view.back[i].price, cells.back[i].price);
      setText(view.back[i].size, cells.back[i].size);
      setText(view.lay[i].price, cells.lay[i].price);
      setText(view.lay[i].size, cells.lay[i].size);
    }
    setText(view.ltp, cells.ltp);
    setText(view.tv, cells.tv);
    if (view.selected !== selected) {
      view.tr.classList.toggle('selected', selected);
      view.tr.setAttribute('aria-selected', selected ? 'true' : 'false');
      view.selected = selected;
    }
    if (view.removed !== cells.removed) {
      view.tr.classList.toggle('removed', cells.removed);
      view.removed = cells.removed;
    }
  }

  tbody.addEventListener('click', (event) => {
    let node = event.target;
    while (node && node !== tbody) {
      if (node.dataset && node.dataset.id !== undefined) {
        const id = Number(node.dataset.id);
        if (Number.isSafeInteger(id)) {
          onSelect(id);
        }
        return;
      }
      node = node.parentNode;
    }
  });

  return {
    stats: stats,
    // Patch the table to show these runners (a frame's runners array) in this order.
    update(runners, selectedId) {
      const seen = new Set();
      runners.forEach((runner, i) => {
        seen.add(runner.id);
        let view = rows.get(runner.id);
        if (view === undefined) {
          view = createRow(runner.id);
          rows.set(runner.id, view);
        }
        patch(view, rowCells(runner), runner.id === selectedId);
        const at = tbody.children[i];
        if (at !== view.tr) {
          tbody.insertBefore(view.tr, at === undefined ? null : at);
          stats.moved += 1;
        }
      });
      for (const [id, view] of rows) {
        if (!seen.has(id)) {
          tbody.removeChild(view.tr);
          rows.delete(id);
          stats.removed += 1;
        }
      }
    },
    size() {
      return rows.size;
    },
  };
}
