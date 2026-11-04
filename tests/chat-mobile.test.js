const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
require('../assets/chat-web.js');

function simulate(mobile) {
  let keyReads = 0;
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      id, value: '', hidden: false, children: [], scrollHeight: 20, style: {}, dataset: {},
      classList: { add() {}, remove() {}, toggle() {} },
      handlers: {}, addEventListener(event, fn) { this.handlers[event] = fn; },
      querySelector() { return null; }, focus() {},
    });
    return elements.get(id);
  }
  const document = { readyState: 'complete', getElementById: element, addEventListener() {}, body: { classList: { add() {}, remove() {} } } };
  const win = { SteelChatWeb: global.SteelChatWeb, navigator: {}, matchMedia: () => ({ matches: mobile }) };
  const context = { window: win, document, navigator: win.navigator, location: { hash: '' },
    localStorage: { getItem() { keyReads++; return ''; } }, console, URL, AbortController, Date, setTimeout, clearTimeout };
  vm.runInNewContext(fs.readFileSync(require.resolve('../assets/chat.js'), 'utf8'), context);
  return { element, get reads() { return keyReads; } };
}
const mobile = simulate(true);
mobile.element('chat-input').value = '第一行';
let prevented = false;
mobile.element('chat-input').handlers.keydown({ key: 'Enter', shiftKey: false, isComposing: false, preventDefault() { prevented = true; } });
assert.equal(prevented, false, 'mobile Enter must keep native newline');
assert.equal(mobile.reads, 0, 'mobile Enter must not send');
mobile.element('chat-form').handlers.submit({ submitter: null, preventDefault() {} });
assert.equal(mobile.reads, 0, 'implicit form submission must not send on mobile');
mobile.element('chat-form').handlers.submit({ submitter: mobile.element('chat-send'), preventDefault() {} });
assert(mobile.reads > 0, 'send button must reach the send handler');
const desktop = simulate(false);
desktop.element('chat-input').value = '測試';
let desktopPrevented = false;
desktop.element('chat-input').handlers.keydown({ key: 'Enter', shiftKey: false, isComposing: false, preventDefault() { desktopPrevented = true; } });
assert(desktopPrevented && desktop.reads > 0, 'desktop Enter continues to send');
const before = mobile.reads;
mobile.element('chat-log').handlers.click({ target: { closest: selector => selector === '.chat-chip' ? { textContent: '建議問題' } : null } });
assert.equal(mobile.element('chat-input').value, '建議問題');
assert.equal(mobile.reads, before, 'mobile suggestions must wait for send');
console.log('Chat input: mobile newline, explicit send, suggestion and desktop Enter passed.');
