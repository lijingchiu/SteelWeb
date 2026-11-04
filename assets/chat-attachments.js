// Prepare locally selected media for the Responses API; never store the originals.
(function (global) {
  const MAX_FILES = 3, MAX_FILE = 10 * 1024 * 1024, MAX_VIDEO = 100 * 1024 * 1024;
  const IMAGE = /\.(png|jpe?g|webp|gif|heic|heif)$/i;
  const VIDEO = /\.(mp4|mov|m4v|webm)$/i;
  const DOC = /\.(pdf|doc|docx|ppt|pptx|xls|xlsx|csv|tsv|txt)$/i;
  function kind(file) {
    const name = String(file.name || '');
    if (VIDEO.test(name)) return 'video';
    if (IMAGE.test(name)) return 'image';
    if (DOC.test(name)) return 'document';
    return '';
  }
  function validate(files) {
    if (files.length > MAX_FILES) return '一次最多選擇 3 個檔案。';
    for (const file of files) {
      const k = kind(file);
      if (!k) return `不支援「${file.name}」的格式。請使用圖片、影片、Word、Excel、PPT、PDF 或文字檔。`;
      if (!file.size || file.size > (k === 'video' ? MAX_VIDEO : MAX_FILE))
        return `「${file.name}」為空或超過大小限制（影片 100 MB，其他檔案 10 MB）。`;
    }
    return '';
  }
  function readData(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error(`無法讀取「${file.name}」，請重新選擇。`));
      reader.onload = () => resolve(String(reader.result).replace(/^data:;/, 'data:application/octet-stream;'));
      reader.readAsDataURL(file);
    });
  }
  async function imageData(file) {
    if (!/\.(heic|heif|gif)$/i.test(file.name)) return readData(file);
    const url = URL.createObjectURL(file), img = new Image();
    try {
      const ready = event(img, 'load'); img.src = url; await ready;
      const canvas = document.createElement('canvas');
      const scale = Math.min(1, 2048 / Math.max(img.naturalWidth, img.naturalHeight));
      canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('目前瀏覽器無法讀取圖片。');
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/jpeg', 0.9);
    } catch (_) { throw new Error(`無法讀取「${file.name}」，請轉存 JPG 或 PNG 再試。`); }
    finally { URL.revokeObjectURL(url); }
  }
  function event(target, success, failures = ['error'], ms = 15000) {
    return new Promise((resolve, reject) => {
      let timer;
      const clean = () => { clearTimeout(timer); target.removeEventListener(success, ok); failures.forEach(x => target.removeEventListener(x, fail)); };
      const ok = () => { clean(); resolve(); };
      const fail = () => { clean(); reject(new Error('無法讀取影片，請換用瀏覽器支援的 MP4 或 MOV。')); };
      target.addEventListener(success, ok, { once: true });
      failures.forEach(x => target.addEventListener(x, fail, { once: true }));
      timer = setTimeout(fail, ms);
    });
  }
  async function videoFrames(file) {
    const url = URL.createObjectURL(file), video = document.createElement('video');
    video.preload = 'metadata'; video.muted = true; video.playsInline = true;
    try {
      const ready = event(video, 'loadedmetadata'); video.src = url; await ready;
      if (!Number.isFinite(video.duration) || video.duration <= 0 || !video.videoWidth || !video.videoHeight)
        throw new Error('無法讀取影片長度或畫面，請換一個檔案。');
      const count = Math.min(8, Math.max(1, Math.ceil(video.duration / 3)));
      const canvas = document.createElement('canvas'), scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale)); canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('目前瀏覽器無法擷取影片畫面。');
      const frames = [];
      for (let i = 0; i < count; i++) {
        const seconds = Math.max(0, Math.min(video.duration - 0.05, video.duration * (i + 0.5) / count));
        const seek = event(video, 'seeked'); video.currentTime = seconds; await seek;
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        frames.push({ seconds: Math.round(seconds * 10) / 10, data: canvas.toDataURL('image/jpeg', 0.8) });
      }
      return { duration: Math.round(video.duration * 10) / 10, frames };
    } finally { video.removeAttribute('src'); video.load(); URL.revokeObjectURL(url); }
  }
  async function prepare(files) {
    const problem = validate(files);
    if (problem) throw new Error(problem);
    const parts = [];
    for (const file of files) {
      const k = kind(file), name = String(file.name).slice(0, 150);
      if (k === 'video') {
        const v = await videoFrames(file);
        parts.push({ type: 'input_text', text: `影片「${name}」長 ${v.duration} 秒，以下是等間隔擷取的 ${v.frames.length} 張畫面；未讀取聲音、字幕軌及其他畫面，不可假稱看完整段影片。` });
        for (const frame of v.frames) {
          parts.push({ type: 'input_text', text: `影片畫面：第 ${frame.seconds} 秒` });
          parts.push({ type: 'input_image', image_url: frame.data, detail: 'high' });
        }
      } else if (k === 'image') {
        parts.push({ type: 'input_text', text: `圖片「${name}」` });
        parts.push({ type: 'input_image', image_url: await imageData(file), detail: 'high' });
      } else {
        parts.push({ type: 'input_text', text: `文件「${name}」` });
        parts.push({ type: 'input_file', filename: name, file_data: await readData(file) });
        if (/\.(docx|xlsx|pptx)$/i.test(name)) {
          const visuals = global.SteelOfficeVisuals
            ? await global.SteelOfficeVisuals.extract(file)
            : {parts: [], warnings: ['Office 內嵌圖片與圖表解析工具無法載入。']};
          parts.push({type:'input_text', text:`附件「${name}」內嵌內容擷取狀態：${visuals.parts.length ? `已擷取 ${visuals.parts.length} 個圖片或圖表資料項。` : '沒有擷取到圖片或圖表。'}${visuals.warnings.length ? `限制：${visuals.warnings.join('；')}` : ''}僅能依照實際提供的圖片及圖表資料回答，不得假稱讀取未提供的內容。`});
          parts.push(...visuals.parts);
        } else if (/\.(doc|xls|ppt)$/i.test(name)) {
          parts.push({type:'input_text', text:`附件「${name}」為舊版 Office 格式，目前無法自動擷取其中圖片及圖表；請說明此限制，不可假稱已看到。`});
        }
      }
    }
    return parts;
  }
  global.SteelAttachments = { kind, validate, prepare };
})(typeof window === 'undefined' ? globalThis : window);
