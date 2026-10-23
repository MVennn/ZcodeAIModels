#!/usr/bin/env node
/**
 * 探测各模型"关思考"参数：哪个字段能被接受、关掉后是否真的不再输出 reasoning。
 * 结果直接打印成表。
 */
'use strict';
const https = require('https');

// OpenCode-Go API key 不写在源码里：从环境变量读取（见 docs/SECRETS.md）
const KEY = process.env.OPENCODE_GO_KEY || '';
if (!KEY) {
  console.error('缺少环境变量 OPENCODE_GO_KEY（OpenCode-Go API key，见 docs/SECRETS.md）');
  process.exit(1);
}
const URL_ = 'https://opencode.ai/zen/go/v1/chat/completions';

const MODELS = [
  'longcat-2.5-preview-free',
  'longcat-2.0',
  'minimax-m3.1-flash-free',
  'minimax-m3',
  'deepseek-v4.1-flash',
  'glm-5.3-flash',
];

const CANDIDATES = [
  ['baseline(不发思考参数)', {}],
  ['thinking:{type:"disabled"}', { thinking: { type: 'disabled' } }],
  ['enable_thinking:false', { enable_thinking: false }],
  ['reasoning_effort:"none"', { reasoning_effort: 'none' }],
];

function probe(model, label, extra, timeoutMs) {
  return new Promise((resolve) => {
    const body = {
      model,
      messages: [{ role: 'user', content: '用一句话回答：1+1 等于几？' }],
      max_tokens: 96,
      stream: true,
      ...extra,
    };
    const data = JSON.stringify(body);
    const t0 = Date.now();
    let status = 0, firstReasoning = null, firstContent = null;
    let reasoningChars = 0, contentChars = 0, errMsg = '', buf = '', done = false;

    const finish = (note) => {
      if (done) return;
      done = true;
      resolve({ model, label, status, total: Date.now() - t0, firstReasoning, firstContent, reasoningChars, contentChars, note: note || errMsg });
    };

    const req = https.request(URL_, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + KEY,
        'x-opencode-session': 'thinkoff-probe-' + Date.now(),
        'Content-Length': Buffer.byteLength(data),
      },
      timeout: timeoutMs,
    }, (res) => {
      status = res.statusCode;
      res.on('data', (d) => {
        buf += d.toString('utf8');
        let idx;
        while ((idx = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 1);
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload || payload === '[DONE]') continue;
          try {
            const j = JSON.parse(payload);
            if (j.error) { errMsg = (j.error.message || '').slice(0, 150); continue; }
            const delta = (j.choices && j.choices[0] && j.choices[0].delta) || {};
            if (delta.reasoning_content) {
              if (firstReasoning === null) firstReasoning = Date.now() - t0;
              reasoningChars += delta.reasoning_content.length;
            }
            if (delta.content) {
              if (firstContent === null) firstContent = Date.now() - t0;
              contentChars += delta.content.length;
            }
          } catch { /* 非 JSON 行忽略 */ }
        }
      });
      res.on('end', () => finish());
    });
    req.on('error', (e) => { errMsg = 'ERR ' + e.message; finish(); });
    req.on('timeout', () => { req.destroy(); errMsg = 'TIMEOUT'; finish(); });
    req.write(data);
    req.end();
  });
}

const sec = (ms) => (ms === null || ms === undefined ? '   -  ' : (ms / 1000).toFixed(1) + 's');

(async () => {
  for (const model of MODELS) {
    console.log('\n===== ' + model + ' =====');
    for (const [label, extra] of CANDIDATES) {
      const r = await probe(model, label, extra, 180000);
      const note = r.status === 200 ? (r.reasoningChars > 0 ? '仍在思考' : '未出现思考') : (r.note || '');
      console.log(
        `${label.padEnd(28)} HTTP ${String(r.status).padEnd(4)} 总${sec(r.total).padStart(6)} ` +
        `首思考${sec(r.firstReasoning).padStart(7)} 首正文${sec(r.firstContent).padStart(7)} ` +
        `思考${String(r.reasoningChars).padStart(5)}字 正文${String(r.contentChars).padStart(4)}字  ${note.slice(0, 90)}`
      );
    }
  }
})();
