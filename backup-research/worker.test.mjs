import { test } from 'node:test';
import assert from 'node:assert/strict';
import { targetAt, ready, check } from './worker.mjs';

test('targets weekdays in Taipei, including the evening before', () => {
  assert.deepEqual(targetAt(new Date('2026-11-08T15:53:00Z')), {date:'2026-11-09', hour:23, minute:53});
  assert.equal(targetAt(new Date('2026-11-06T15:53:00Z')), null);
  assert.equal(targetAt(new Date('2026-11-09T00:00:00Z')), null);
});
test('completion requires both notifications and every current report', () => {
  const date='2026-11-09', latest={date}, outlook={research_date:date,failed_batches:0,total_items:1,covered_items:1};
  const materials={items:[{}]}, report={date,file:'a',pdf_file:'b'}, notifications={push:{date},email:{date}};
  assert.equal(ready(date,latest,outlook,materials,report,notifications),true);
  assert.equal(ready(date,latest,outlook,materials,report,{push:{date}}),false);
  assert.equal(ready(date,latest,{...outlook,failed_batches:1},materials,report,notifications),false);
});
test('never runs on weekends or outside the check window', async () => {
  assert.equal(await check({},new Date('2026-11-07T02:00:00Z')),'outside-window');
});

test('backup dispatch does not force a second research and active work prevents dispatch', async () => {
  const current = new Date('2026-11-09T17:00:00Z'); // Tuesday 01:00 Taipei
  let active = false, calls = [];
  const original = globalThis.fetch;
  const db = { prepare(sql) { return { bind(...args) { return { async run() { return {meta:{changes:1}}; } }; } }; } };
  const files = {'latest.json':{},'material-outlooks.json':{},'materials.json':{items:[]},'report.json':{},'notify-state.json':{}};
  globalThis.fetch = async (url, opts={}) => {
    calls.push({url,opts});
    if (opts.method === 'POST') return new Response(null,{status:204});
    if (url.includes('/actions/workflows/')) return Response.json({workflow_runs:active ? [{status:'in_progress',created_at:current.toISOString()}] : []});
    const name = url.split('/').pop().split('?')[0];
    return Response.json({encoding:'base64',content:Buffer.from(JSON.stringify(files[name])).toString('base64')});
  };
  try {
    assert.equal(await check({DB:db,GITHUB_TOKEN:'test'},current),'dispatched');
    const post=calls.find(c=>c.opts.method==='POST');
    assert.deepEqual(JSON.parse(post.opts.body).inputs,{backup:true,force_run:'false'});
    calls=[]; active=true;
    assert.equal(await check({DB:db,GITHUB_TOKEN:'test'},current),'running-or-recent');
    assert.equal(calls.some(c=>c.opts.method==='POST'),false);
  } finally { globalThis.fetch=original; }
});

test('Yahoo reminder uses TLS and sends only to the configured address', async () => {
  const { sendYahoo } = await import('./smtp.mjs');
  const replies = ['220 ready\r\n','250-hello\r\n250 AUTH PLAIN\r\n','235 ok\r\n','250 ok\r\n','250 ok\r\n','354 send\r\n','250 queued\r\n','221 bye\r\n'];
  const writes=[]; let endpoint, options;
  const connect=(address,settings)=>{
    endpoint=address; options=settings;
    return {readable:new ReadableStream({start(controller){for(const s of replies)controller.enqueue(new TextEncoder().encode(s));controller.close();}}),writable:new WritableStream({write(chunk){writes.push(new TextDecoder().decode(chunk));}}),async close(){}};
  };
  await sendYahoo(connect,'private-app-password','test@example.com','2026-11-09','尚未完成');
  assert.deepEqual(endpoint,{hostname:'smtp.mail.yahoo.com',port:465});
  assert.equal(options.secureTransport,'on');
  assert.ok(writes.includes('RCPT TO:<test@example.com>\r\n'));
  assert.ok(writes.some(s=>s.includes('Content-Transfer-Encoding: base64')));
});
