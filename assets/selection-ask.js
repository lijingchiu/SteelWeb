// Stage selected site content for the assistant; never send it automatically.
(() => {
  const form = document.getElementById('selection-ask');
  if (!form) return;
  const trigger = document.getElementById('selection-ask-trigger');
  const quote = document.getElementById('selection-ask-quote');
  const input = document.getElementById('selection-ask-input');
  const status = document.getElementById('selection-ask-status');
  const submit = document.getElementById('selection-ask-send');
  let current = null, timer, hold, start, anchor;
  const marks = new Map();
  function positionMarks() {
    for (const mark of marks.values()) {
      try {
        const rect = mark.anchor.getBoundingClientRect();
        const visible = rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight;
        mark.button.hidden = !visible;
        if (visible) { const size = mark.button.offsetWidth || 36; mark.button.style.left = `${Math.max(6, Math.min(window.innerWidth - size - 6, rect.left))}px`; mark.button.style.top = `${Math.max(6, rect.top - size - 3)}px`; }
      } catch (_) { mark.button.hidden = true; }
    }
  }
  function addMark(id, target) {
    if (!target) return;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'selection-mark';
    button.addEventListener('click', () => document.dispatchEvent(new CustomEvent('steel:edit-selection', {detail:{id}})));
    document.body.appendChild(button);
    marks.set(id, {button, anchor:target});
    refreshMarks([...marks.keys()]);
  }
  function refreshMarks(ids) {
    const active = new Set(ids);
    for (const [id, mark] of marks) if (!active.has(id)) { mark.button.remove(); marks.delete(id); }
    ids.forEach((id, i) => { const mark = marks.get(id); if (mark) { mark.button.textContent = String(i + 1); mark.button.setAttribute('aria-label', `編輯第 ${i + 1} 段引用的問題`); } });
    positionMarks();
  }
  document.addEventListener('steel:selection-update', e => refreshMarks(e.detail.ids));
  window.addEventListener('scroll', positionMarks, {passive:true, capture:true});
  window.addEventListener('resize', positionMarks);
  const excluded = node => {
    const el = node?.nodeType === 1 ? node : node?.parentElement;
    return !el || !!el.closest('#selection-ask, #chat-panel, input, textarea, [contenteditable="true"], button');
  };
  const hide = (clearSelection = true) => {
    clearTimeout(timer); clearTimeout(hold);
    form.hidden = true; trigger.hidden = true; current = null; anchor = null; status.textContent = '';
    if (clearSelection) window.getSelection()?.removeAllRanges();
  };
  function position() {
    if (!anchor || (form.hidden && trigger.hidden)) return;
    const vv = window.visualViewport;
    const left = vv?.offsetLeft || 0, top = vv?.offsetTop || 0;
    const popup = form.hidden ? trigger : form;
    const width = form.hidden ? Math.min(trigger.offsetWidth || 110, (vv?.width || window.innerWidth) - 24) : Math.min(360, (vv?.width || window.innerWidth) - 24);
    const height = vv?.height || window.innerHeight;
    const viewWidth = vv?.width || window.innerWidth;
    const mobile = window.matchMedia?.('(hover: none) and (pointer: coarse)').matches || window.innerWidth <= 768;
    let x = Math.max(left + 12, Math.min(anchor.left, left + viewWidth - width - 12));
    let y = Math.max(top + 12, Math.min(anchor.bottom + 10, top + height - popup.offsetHeight - 12));
    if (form.hidden && mobile && current?.text) {
      // The system menu has no web-visible bounds. Reserve space above and
      // below the selection and place the button at a viewport edge instead.
      const gap = 64, upper = top + 12, lower = top + height - popup.offsetHeight - 12;
      if (lower >= anchor.bottom + gap) y = lower;
      else if (upper + popup.offsetHeight <= anchor.top - gap) y = upper;
      else if (anchor.left - left >= width + 24) { x = left + 12; y = Math.max(upper, Math.min(anchor.top, lower)); }
      else if (left + viewWidth - anchor.right >= width + 24) { x = left + viewWidth - width - 12; y = Math.max(upper, Math.min(anchor.top, lower)); }
      else y = (anchor.top - top > top + height - anchor.bottom) ? upper : lower;
    }
    popup.style.left = `${x}px`;
    popup.style.top = `${y}px`;
  }
  function show(item, rect) {
    if (!item || !rect) return;
    current = item; anchor = rect;
    const preview = item.text || item.label || '網站圖片或圖表';
    quote.textContent = preview.length > 100 ? preview.slice(0, 100) + '…' : preview;
    input.value = ''; status.textContent = ''; form.hidden = true; trigger.hidden = false;
    position();
  }
  function selectedText() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount || excluded(sel.anchorNode) || excluded(sel.focusNode)) return null;
    const text = String(sel).trim();
    if (!text) return null;
    const range = sel.getRangeAt(0).cloneRange();
    return {text, range};
  }
  trigger.addEventListener('pointerdown', () => {
    if (current?.text) current = selectedText() || current;
    clearTimeout(timer);
  });
  trigger.addEventListener('click', () => {
    if (!current) return;
    if (current.text) {
      current = selectedText() || current;
      anchor = current.range.getBoundingClientRect();
      quote.textContent = current.text.length > 100 ? current.text.slice(0, 100) + '…' : current.text;
    }
    clearTimeout(timer); trigger.hidden = true; form.hidden = false; position(); input.focus();
  });
  window.visualViewport?.addEventListener('resize', position);
  window.visualViewport?.addEventListener('scroll', position);
  function inspectSelection() {
    if (!form.hidden) return;
    const selected = selectedText();
    if (!selected) { if (current?.text) hide(false); return; }
    show(selected, selected.range.getBoundingClientRect());
  }
  document.addEventListener('selectionchange', () => { clearTimeout(timer); timer = setTimeout(inspectSelection, 220); });
  document.addEventListener('pointerup', e => {
    clearTimeout(hold); start = null;
    if (form.contains(e.target) || trigger.contains(e.target)) return;
    clearTimeout(timer); timer = setTimeout(inspectSelection, 100);
  });
  const imageTarget = target => {
    const el = target?.closest?.('img, canvas');
    return el && !excluded(el) && el.getBoundingClientRect().width >= 60 && el.getBoundingClientRect().height >= 40 ? el : null;
  };
  function selectImage(el) {
    const label = el.getAttribute('alt') || el.getAttribute('aria-label') || '網站圖片或圖表';
    show({element: el, label}, el.getBoundingClientRect());
  }
  document.addEventListener('contextmenu', e => {
    const el = imageTarget(e.target);
    if (!el) return;
    e.preventDefault(); selectImage(el);
  });
  document.addEventListener('pointerdown', e => {
    if ((!form.hidden || !trigger.hidden) && !form.contains(e.target) && !trigger.contains(e.target)) {
      // Native touch selection handles can send pointer events to the page.
      // Never clear the selection while the user might be adjusting them.
      const adjustingText = e.pointerType === 'touch' && form.hidden && !!current?.text;
      hide(!adjustingText);
    }
    clearTimeout(hold);
    const el = e.pointerType === 'touch' && imageTarget(e.target);
    if (el) { start = {x:e.clientX, y:e.clientY}; hold = setTimeout(() => selectImage(el), 650); }
  });
  document.addEventListener('pointermove', e => {
    if (start && (Math.abs(e.clientX - start.x) > 12 || Math.abs(e.clientY - start.y) > 12)) { clearTimeout(hold); start = null; }
  });
  document.addEventListener('pointercancel', () => { clearTimeout(hold); start = null; });
  document.getElementById('selection-ask-close').addEventListener('click', hide);
  form.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); hide(); } });
  async function imageFile(el) {
    let blob;
    if (el.tagName === 'CANVAS') {
      blob = await new Promise((resolve, reject) => {
        try { el.toBlob(resolve, 'image/png'); } catch (e) { reject(e); }
      });
    } else {
      const url = new URL(el.currentSrc || el.src, location.href);
      if (!['https:', 'http:', 'blob:', 'data:'].includes(url.protocol)) throw new Error('無法讀取這張圖片。');
      const res = await fetch(url.href, {credentials:'omit'});
      if (!res.ok) throw new Error('無法讀取這張圖片。');
      blob = await res.blob();
    }
    if (!blob || !/^image\/(png|jpeg|webp|gif)$/i.test(blob.type)) throw new Error('無法擷取這張圖片，請改用截圖上傳。');
    const ext = {'image/jpeg':'jpg','image/png':'png','image/webp':'webp','image/gif':'gif'}[blob.type.toLowerCase()];
    return new File([blob], `網站選取圖片-${Date.now()}.${ext}`, {type:blob.type});
  }
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (!current || submit.disabled) return;
    submit.disabled = true; status.textContent = current.element ? '正在擷取圖片…' : '';
    try {
      const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const detail = {id, text:current.text || '', label:current.label || '', question:input.value.trim()};
      if (current.element) detail.file = await imageFile(current.element);
      document.dispatchEvent(new CustomEvent('steel:ask-selection', {detail}));
      if (!detail.accepted) { status.textContent = detail.error || '無法加入，請稍後再試。'; return; }
      addMark(id, current.range || current.element);
      hide();
    } catch (_) { status.textContent = '無法擷取這張圖片，請改用截圖上傳。'; }
    finally { submit.disabled = false; }
  });
})();
