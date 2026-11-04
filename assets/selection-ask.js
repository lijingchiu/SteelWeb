// Stage selected site content for the assistant; never send it automatically.
(() => {
  const form = document.getElementById('selection-ask');
  if (!form) return;
  const quote = document.getElementById('selection-ask-quote');
  const input = document.getElementById('selection-ask-input');
  const status = document.getElementById('selection-ask-status');
  const submit = document.getElementById('selection-ask-send');
  let current = null, timer, hold, start, anchor;
  const excluded = node => {
    const el = node?.nodeType === 1 ? node : node?.parentElement;
    return !el || !!el.closest('#selection-ask, #chat-panel, input, textarea, [contenteditable="true"], button');
  };
  const hide = () => { form.hidden = true; current = null; status.textContent = ''; };
  function position() {
    if (form.hidden || !anchor) return;
    const vv = window.visualViewport;
    const left = vv?.offsetLeft || 0, top = vv?.offsetTop || 0;
    const width = Math.min(360, (vv?.width || window.innerWidth) - 24);
    const height = vv?.height || window.innerHeight;
    form.style.left = `${Math.max(left + 12, Math.min(anchor.left, left + (vv?.width || window.innerWidth) - width - 12))}px`;
    form.style.top = `${Math.max(top + 12, Math.min(anchor.bottom + 10, top + height - form.offsetHeight - 12))}px`;
  }
  function show(item, rect) {
    if (!item || !rect) return;
    current = item; anchor = rect;
    quote.textContent = item.text || item.label || '網站圖片或圖表';
    input.value = ''; status.textContent = ''; form.hidden = false;
    position();
  }
  window.visualViewport?.addEventListener('resize', position);
  window.visualViewport?.addEventListener('scroll', position);
  function inspectSelection() {
    if (!form.hidden && form.contains(document.activeElement)) return;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount || excluded(sel.anchorNode) || excluded(sel.focusNode)) return;
    const text = String(sel).trim();
    if (!text) return;
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    show({text}, rect);
  }
  document.addEventListener('selectionchange', () => { clearTimeout(timer); timer = setTimeout(inspectSelection, 220); });
  document.addEventListener('pointerup', () => { clearTimeout(hold); clearTimeout(timer); timer = setTimeout(inspectSelection, 100); });
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
    if (!form.hidden && !form.contains(e.target)) hide();
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
    if (current.text && current.text.length > 1800) { status.textContent = '選取文字請勿超過 1800 字。'; return; }
    submit.disabled = true; status.textContent = current.element ? '正在擷取圖片…' : '';
    try {
      const detail = {text:current.text || '', label:current.label || '', question:input.value.trim()};
      if (current.element) detail.file = await imageFile(current.element);
      document.dispatchEvent(new CustomEvent('steel:ask-selection', {detail}));
      if (!detail.accepted) { status.textContent = detail.error || '無法加入，請稍後再試。'; return; }
      hide();
      window.getSelection()?.removeAllRanges();
    } catch (_) { status.textContent = '無法擷取這張圖片，請改用截圖上傳。'; }
    finally { submit.disabled = false; }
  });
})();
