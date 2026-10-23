#!/usr/bin/env node
/**
 * OpenCode Go 请求头注入代理
 *
 * 用途：给不支持自定义请求头的客户端（ChatBox、Open WebUI、各类 OpenAI 兼容前端）
 * 自动补上 opencode Go 网关必需的 x-opencode-session 头。
 *
 * 用法：
 *   node opencode-header-proxy.js
 *   node opencode-header-proxy.js --port 8787 --session my-session-id
 *
 * 客户端里这样填：
 *   API 地址 / Base URL:  http://127.0.0.1:8787/v1
 *   API Key:              照旧填 oc_sk_...（代理不保存、不读取密钥，原样转发）
 *
 * 会话头取值优先级：
 *   客户端自己发的 x-opencode-session / x-session-id / session_id
 *   > 启动参数 --session > 环境变量 OPENCODE_SESSION > 默认固定值
 */
'use strict';

const http = require('http');
const https = require('https');

function arg(name, fallback) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const PORT = Number(arg('port', process.env.PORT || 8787));
const HOST = arg('host', process.env.HOST || '127.0.0.1');
const FALLBACK_SESSION = arg('session', process.env.OPENCODE_SESSION || 'local-client-session');

const TARGET_HOST = 'opencode.ai';
const TARGET_PREFIX = '/zen/go/v1';

// 客户端 Base URL 可能是 /v1 或 /zen/go/v1，统一映射到上游 /zen/go/v1
function upstreamPath(url) {
  let p = url || '/';
  p = p.replace(/^\/zen\/go\/v1(?=\/|$)/, '');
  p = p.replace(/^\/v1(?=\/|$)/, '');
  if (!p.startsWith('/')) p = '/' + p;
  return TARGET_PREFIX + p;
}

const server = http.createServer((req, res) => {
  const session =
    req.headers['x-opencode-session'] ||
    req.headers['x-session-id'] ||
    req.headers['session_id'] ||
    FALLBACK_SESSION;

  const headers = { ...req.headers };
  delete headers.host;
  delete headers['content-length']; // 改用 chunked，避免长度不匹配
  headers['x-opencode-session'] = String(session);
  if (!headers['user-agent'] || /python-urllib|python-requests/i.test(headers['user-agent'])) {
    headers['user-agent'] = 'opencode-compatible-client/1.0';
  }

  const upstream = https.request(
    {
      hostname: TARGET_HOST,
      port: 443,
      method: req.method,
      path: upstreamPath(req.url),
      headers,
    },
    (ures) => {
      res.writeHead(ures.statusCode || 502, ures.headers);
      ures.pipe(res);
    }
  );

  upstream.on('error', (e) => {
    if (!res.headersSent) res.writeHead(502, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: { message: 'proxy error: ' + e.message, type: 'proxy_error' } }));
  });

  req.on('aborted', () => upstream.destroy());
  req.pipe(upstream);
});

server.requestTimeout = 0;
server.headersTimeout = 0;
server.listen(PORT, HOST, () => {
  console.log(`OpenCode Go 注入代理已启动: http://${HOST}:${PORT}/v1`);
  console.log(`会话头取值: 客户端 x-opencode-session/x-session-id > ${FALLBACK_SESSION}`);
});
