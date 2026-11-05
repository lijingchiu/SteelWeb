// A small implicit-TLS SMTP client; never log credentials or server responses.
export async function sendYahoo(connect, password, to, date, reason) {
  const from = to;
  if (!/^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(to)) throw new Error('Invalid destination address');
  const socket = connect({ hostname: 'smtp.mail.yahoo.com', port: 465 }, { secureTransport: 'on' });
  const reader = socket.readable.getReader(), writer = socket.writable.getWriter();
  const decoder = new TextDecoder(), encoder = new TextEncoder();
  let pending = '';
  async function reply() {
    for (;;) {
      let pos;
      while ((pos = pending.indexOf('\r\n')) >= 0) {
        const line = pending.slice(0, pos); pending = pending.slice(pos + 2);
        if (/^\d{3} /.test(line)) {
          const code = Number(line.slice(0, 3));
          if (code >= 400) throw new Error(`SMTP failed (${code})`);
          return code;
        }
      }
      const part = await reader.read();
      if (part.done) throw new Error('SMTP connection closed');
      pending += decoder.decode(part.value, {stream:true});
      if (pending.length > 16384) throw new Error('SMTP response too long');
    }
  }
  async function command(text, expected) {
    await writer.write(encoder.encode(text + '\r\n'));
    const code = await reply();
    if (!expected.includes(code)) throw new Error(`Unexpected SMTP response (${code})`);
  }
  try {
    if (await reply() !== 220) throw new Error('SMTP unavailable');
    await command('EHLO steel-watchdog', [250]);
    await command('AUTH PLAIN ' + btoa('\0' + from + '\0' + password), [235]);
    await command(`MAIL FROM:<${from}>`, [250]);
    await command(`RCPT TO:<${to}>`, [250,251]);
    await command('DATA', [354]);
    const body = `每日研究備援檢查發現：${reason}。\n請查看 https://github.com/lijingchiu/SteelWeb/actions/workflows/daily-analysis.yml`;
    const subject = `鋼市每日研究尚未完成：${date}`;
    const base64 = text => btoa(String.fromCharCode(...encoder.encode(text)));
    const message = [`From: <${from}>`, `To: <${to}>`, `Subject: =?UTF-8?B?${base64(subject)}?=`, 'MIME-Version: 1.0', 'Content-Type: text/plain; charset=UTF-8', 'Content-Transfer-Encoding: base64', '', base64(body).replace(/.{1,76}/g, '$&\r\n'), '.'].join('\r\n');
    await command(message, [250]);
    await command('QUIT', [221]).catch(() => {});
  } finally { reader.releaseLock(); writer.releaseLock(); await socket.close(); }
}
