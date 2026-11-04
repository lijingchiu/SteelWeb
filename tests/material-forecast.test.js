'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { baseline } = require('../assets/material-forecast.js');
const item = { period: '2026-04', value: 106, history: [['2026-01',100], ['2026-02',101], ['2026-03',103], ['2026-04',106]] };
test('uses median of recent changes and identifies a short history', () => {
  const result = baseline(item);
  assert.equal(result.estimate, 108);
  assert.equal(result.direction, 'up');
  assert.equal(result.short, true);
});
test('refuses stale, insufficient, or inconsistent data', () => {
  assert.equal(baseline({ ...item, stale: true }).available, false);
  assert.equal(baseline({ ...item, history: item.history.slice(2) }).available, false);
  assert.equal(baseline({ ...item, period: '2026-05' }).available, false);
  assert.equal(baseline({ ...item, value: 110 }).available, false);
});
test('all current materials can be assessed and have traceable history', () => {
  const materials = require('../data/materials.json');
  for (const material of materials.items) {
    const result = baseline(material);
    assert.ok(result.available || result.reason, material.id);
    assert.ok(material.source && material.source_url, material.id);
    assert.ok(material.history.length >= 2, material.id);
  }
});
