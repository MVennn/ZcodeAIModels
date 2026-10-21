#!/usr/bin/env node
/**
 * 统一路由：把 OpenCode-Go 与 WorkBuddy 放在同一个 baseUrl 后面
 *
 * 为什么需要它
 * ------------
 * ZCode 的一个 provider 只能填一个 `api.baseUrl`。OpenCode-Go 与 WorkBuddy
 * 是两个不同上游，要把 WorkBuddy 模型并进「主力 / 免费 / 低耗 / 高耗 / 备用」
 * 这些 OpenCode provider，就必须有一个本地路由按 model 分流。
 *
 * 路由规则
 * --------
 *   model 以 `cn:` / `global:` 开头  -> WorkBuddy 网关（默认 http://127.0.0.1:7863）
 *   其余 model                        -> OpenCode-Go（默认 https://opencode.ai/zen/go/v1）
 *
 * 只监听 127.0.0.1；不要把端口暴露到公网。
 *
 * 用法
 * ----
 *   node tools/unified-router.js
 *   UNIFIED_ROUTER_PORT=7871 node tools/unified-router.js
 *
 * 环境变量
 * --------
 *   UNIFIED_ROUTER_PORT / UNIFIED_ROUTER_HOST   默认 7871 / 127.0.0.1
 *   OPENCODE_GO_BASE                            默认 https://opencode.ai/zen/go/v1
 *   WB_GATEWAY_BASE                             默认 http://127.0.0.1:7863
 *   OPENCODE_GO_KEY / WB_GATEWAY_KEY            缺省时从 provider_config.json /
 *                                               workbuddy/gateway/config.json 读
 *   OPENCODE_SESSION                            OpenCode 会话头，默认 unified-router
 *
 * 健康检查
 * --------
 *   GET /health  ->  {"ok":true,"opencode":{...},"workbuddy":{...}}（不返回 key）
 */
'use strict';

const http = require('http');
const https = require('https');
const fs = require('fs');
const os = require('os');
const path = require('path');

const HOST = process.env.UNIFIED_ROUTER_HOST || '127.0.0.1';
const PORT = Number(process.env.UNIFIED_ROUTER_PORT || 7871);
const OPENCODE_BASE = (process.env.OPENCODE_GO_BASE || 'https://opencode.ai/zen/go/v1').replace(/\/+$/, '');
const WB_BASE = (process.env.WB_GATEWAY_BASE || 'http://127.0.0.1:7863').replace(/\/+$/, '');
const SESSION = process.env.OPENCODE_SESSION || 'unified-router';

function configPath() {
  return process.env.ZCODE_PERSONAL_PROVIDER_CONFIG_FILE ||
    path.join(os.homedir(), '.zcode', 'v2', 'provider_config.json');
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

function providerRules(cfg) {
  const pcr = cfg && cfg.config && cfg.config.providerConfigRules;
  return (pcr && (Array.isArray(pcr) ? pcr : pcr.providerRules)) || [];
}

function findKey(cfg, match) {
  for (const rule of providerRules(cfg)) {
    const cfgPart = rule.config || {};
    const base = (cfgPart.api && cfgPart.api.baseUrl) || '';
    if (match(rule, base) && cfgPart.access && cfgPart.access.apiKey) {
      return cfgPart.access.apiKey;
    }
  }
  return '';
}

function loadKeys() {
  const cfg = readJson(configPath());
  let opencode = process.env.OPENCODE_GO_KEY || '';
  let workbuddy = process.env.WB_GATEWAY_KEY || '';
  if (!opencode) {
    opencode = findKey(cfg, (rule, base) =>
      /opencode\.ai/i.test(base) || /^opencode-go/.test(rule.providerId || ''));
  }
  if (!workbuddy) {
    workbuddy = findKey(cfg, (rule, base) =>
      /127\.0\.0\.1:7863|localhost:7863/i.test(base) || /^workbuddy-/.test(rule.providerId || ''));
  }
  if (!workbuddy) {
    const gateway = readJson(path.join(__dirname, '..', 'workbuddy', 'gateway', 'config.json'));
    if (gateway && gateway.api_key) workbuddy = String(gateway.api_key);
  }
  return { opencode, workbuddy };
}

const KEYS = loadKeys();
if (!KEYS.opencode) {
  console.warn('[router] 缺少 OpenCode-Go key：设置 OPENCODE_GO_KEY 或检查 provider_config.json');
}
if (!KEYS.workbuddy) {
  console.warn('[router] 缺少 WorkBuddy key：设置 WB_GATEWAY_KEY 或检查 workbuddy/gateway/config.json');
}

function normalizePath(rawUrl) {
  const url = new URL(rawUrl || '/', 'http://localhost');
  let pathname = url.pathname.replace(/^\/v1(?=\/|$)/, '');
  if (!pathname.startsWith('/')) pathname = '/' + pathname;
  return { pathname, search: url.search };
}

function isWorkBuddyModel(model) {
  return /^(cn|global):/i.test(String(model || ''));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
}

function forward(req, res, body, baseUrl, pathname, search, headers) {
  const target = new URL(baseUrl + pathname + search);
  const isHttps = target.protocol === 'https:';
  const transport = isHttps ? https : http;
  const upstream = transport.request(
    {
      protocol: target.protocol,
      hostname: target.hostname,
      port: target.port || (isHttps ? 443 : 80),
      method: req.method,
      path: target.pathname + target.search,
      headers,
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    }
  );
  upstream.on('error', (err) => {
    if (!res.headersSent) {
      sendJson(res, 502, {
        error: { message: 'unified-router upstream error: ' + err.message, type: 'proxy_error' },
      });
    } else {
      res.destroy();
    }
  });
  req.on('aborted', () => upstream.destroy());
  if (body.length) upstream.write(body);
  upstream.end();
}

const server = http.createServer(async (req, res) => {
  try {
    const { pathname, search } = normalizePath(req.url);
    if (pathname === '/health') {
      return sendJson(res, 200, {
        ok: true,
        opencode: { base: OPENCODE_BASE, key: Boolean(KEYS.opencode) },
        workbuddy: { base: WB_BASE, key: Boolean(KEYS.workbuddy) },
      });
    }

    const body = await readBody(req);
    let model = '';
    if (body.length && (req.headers['content-type'] || '').includes('application/json')) {
      try {
        model = JSON.parse(body.toString('utf8')).model || '';
      } catch {
        model = '';
      }
    }

    const isChat = pathname === '/chat/completions';
    const useWorkBuddy = isChat && isWorkBuddyModel(model);
    if (!isChat && isWorkBuddyModel(model)) {
      return sendJson(res, 400, {
        error: {
          message: 'WorkBuddy models only support chat/completions',
          type: 'invalid_request_error',
        },
      });
    }

    const headers = { ...req.headers };
    delete headers.host;
    delete headers['content-length'];
    delete headers['transfer-encoding'];
    if (body.length) headers['content-length'] = String(body.length);
    if (!headers['user-agent']) headers['user-agent'] = 'unified-router/1.0';

    let baseUrl;
    let label;
    if (useWorkBuddy) {
      if (!KEYS.workbuddy) {
        return sendJson(res, 502, {
          error: { message: 'WorkBuddy key not configured', type: 'configuration_error' },
        });
      }
      baseUrl = WB_BASE + '/v1';
      headers['authorization'] = 'Bearer ' + KEYS.workbuddy;
      label = 'workbuddy';
    } else {
      if (!KEYS.opencode) {
        return sendJson(res, 502, {
          error: { message: 'OpenCode-Go key not configured', type: 'configuration_error' },
        });
      }
      baseUrl = OPENCODE_BASE;
      headers['authorization'] = 'Bearer ' + KEYS.opencode;
      headers['x-opencode-session'] = headers['x-opencode-session'] || SESSION;
      label = 'opencode';
    }

    console.log(`${req.method} ${pathname}${search} model=${model || '-'} -> ${label}`);
    forward(req, res, body, baseUrl, pathname, search, headers);
  } catch (err) {
    if (!res.headersSent) {
      sendJson(res, 500, {
        error: { message: 'unified-router error: ' + err.message, type: 'proxy_error' },
      });
    } else {
      res.destroy();
    }
  }
});

server.requestTimeout = 0;
server.headersTimeout = 0;
server.listen(PORT, HOST, () => {
  console.log(`统一路由已启动: http://${HOST}:${PORT}/v1`);
  console.log(`OpenCode-Go: ${OPENCODE_BASE} (key=${KEYS.opencode ? 'ok' : 'missing'})`);
  console.log(`WorkBuddy  : ${WB_BASE}/v1 (key=${KEYS.workbuddy ? 'ok' : 'missing'})`);
});
