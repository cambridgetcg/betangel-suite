// The one-click grid: row texts, and DOM patching by key against a small fake document.
import test from 'node:test';
import assert from 'node:assert/strict';

import { LEVELS, createGrid, rowCells } from '../grid.js';

class FakeElement {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.attributes = {};
    this.className = '';
    this.listeners = {};
    this.ownText = '';
    this.textWrites = 0;
  }

  set textContent(value) {
    this.ownText = String(value);
    this.textWrites += 1;
  }

  get textContent() {
    return this.ownText + this.children.map((child) => child.textContent).join('');
  }

  get classList() {
    const element = this;
    const names = () => element.className.split(' ').filter(Boolean);
    return {
      contains: (name) => names().includes(name),
      toggle: (name, on) => {
        const rest = names().filter((n) => n !== name);
        element.className = (on ? [...rest, name] : rest).join(' ');
      },
    };
  }

  detach(child) {
    if (child.parentNode !== null) {
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

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  addEventListener(type, listener) {
    (this.listeners[type] = this.listeners[type] || []).push(listener);
  }
}

const doc = { createElement: (tag) => new FakeElement(tag) };

function runner(n, fields = {}) {
  return { id: 90000000 + n, name: 'Synthetic ' + n, status: 'ACTIVE', ltp_h: null, tv_p: 0, back: [], lay: [], ...fields };
}

function ids(tbody) {
  return tbody.children.map((tr) => Number(tr.dataset.id));
}

function allWrites(node) {
  return node.textWrites + node.children.reduce((sum, child) => sum + allWrites(child), 0);
}

test('row cells: backs run worst to best, lays best to worst, texts from integers', () => {
  const cells = rowCells(runner(1, {
    ltp_h: 250, tv_p: 1234550, back: [[248, 1234], [246, 500]], lay: [[250, 40], [252, 0], [254, 100000000]],
  }));
  assert.equal(cells.name, 'Synthetic 1');
  assert.equal(cells.status, '');
  assert.equal(cells.ltp, '2.5');
  assert.equal(cells.tv, '£12,346');
  assert.deepEqual(cells.back, [{ price: '', size: '' }, { price: '2.46', size: '5' }, { price: '2.48', size: '12' }]);
  assert.deepEqual(cells.lay, [{ price: '2.5', size: '<1' }, { price: '2.52', size: '0' }, { price: '2.54', size: '1000k' }]);
  assert.equal(LEVELS, 3);
  const removed = rowCells(runner(2, { status: 'REMOVED' }));
  assert.equal(removed.status, 'REMOVED');
  assert.equal(removed.removed, true);
  assert.equal(removed.ltp, '');
});

test('an unknown traded volume shows blank, never £0, and a known one is not carried into it', () => {
  assert.equal(rowCells(runner(1, { tv_p: null })).tv, '');
  assert.equal(rowCells(runner(1, { tv_p: 0 })).tv, '£0');
  const tbody = new FakeElement('tbody');
  const grid = createGrid(tbody, doc);
  grid.update([runner(1, { tv_p: 123400 })], null);
  assert.ok(tbody.children[0].textContent.includes('£1,234'));
  grid.update([runner(1, { tv_p: null })], null);
  assert.ok(!tbody.children[0].textContent.includes('£'));
});

test('rows are created once per runner and patched in place', () => {
  const tbody = new FakeElement('tbody');
  const grid = createGrid(tbody, doc);
  const runners = [runner(1, { ltp_h: 250 }), runner(2, { ltp_h: 400 }), runner(3)];
  grid.update(runners, 90000001);
  assert.deepEqual(ids(tbody), [90000001, 90000002, 90000003]);
  assert.equal(grid.stats.created, 3);
  const firstRow = tbody.children[0];
  assert.ok(firstRow.classList.contains('selected'));
  assert.equal(firstRow.attributes['aria-selected'], 'true');
  assert.ok(firstRow.textContent.includes('Synthetic 1'));

  const writes = allWrites(tbody);
  grid.update(runners, 90000001);
  assert.equal(allWrites(tbody), writes, 'an identical frame writes nothing');

  grid.update([runner(1, { ltp_h: 252 }), runner(2, { ltp_h: 400 }), runner(3)], 90000001);
  assert.equal(allWrites(tbody), writes + 1, 'one changed value, one write');
  assert.equal(tbody.children[0], firstRow, 'the same row element is kept');
  assert.equal(grid.stats.created, 3);
});

test('rows move with the frame order, and leave with their runner', () => {
  const tbody = new FakeElement('tbody');
  const grid = createGrid(tbody, doc);
  grid.update([runner(1), runner(2), runner(3)], null);
  const rowOf = (id) => tbody.children.find((tr) => Number(tr.dataset.id) === id);
  const third = rowOf(90000003);
  grid.update([runner(3), runner(1), runner(2)], null);
  assert.deepEqual(ids(tbody), [90000003, 90000001, 90000002]);
  assert.equal(rowOf(90000003), third);
  grid.update([runner(3), runner(2)], 90000002);
  assert.deepEqual(ids(tbody), [90000003, 90000002]);
  assert.equal(grid.size(), 2);
  assert.equal(grid.stats.removed, 1);
  assert.ok(rowOf(90000002).classList.contains('selected'));
  assert.equal(rowOf(90000003).classList.contains('selected'), false);
  grid.update([runner(3), runner(2, { status: 'REMOVED' })], 90000002);
  assert.ok(rowOf(90000002).classList.contains('removed'));
  grid.update([], null);
  assert.equal(tbody.children.length, 0);
});

test('clicking anywhere in a row selects that runner', () => {
  const tbody = new FakeElement('tbody');
  const selected = [];
  const grid = createGrid(tbody, doc, { onSelect: (id) => selected.push(id) });
  grid.update([runner(1), runner(2)], null);
  const span = tbody.children[1].children[2].children[0];
  tbody.listeners.click.forEach((listener) => listener({ target: span }));
  assert.deepEqual(selected, [90000002]);
  tbody.listeners.click.forEach((listener) => listener({ target: tbody }));
  assert.deepEqual(selected, [90000002]);
});
