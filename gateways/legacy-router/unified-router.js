#!/usr/bin/env node
/**
 * 统一路由：把 OpenCode-Go、WorkBuddy 与 Qoder 放在同一个 baseUrl 后面
 *
 * 为什么需要它
 * ------------
 * ZCode 的一个 provider 只能填一个 `api.baseUrl`。OpenCode-Go 与 WorkBuddy
 * 是两个不同上游，要把它们并进「主力 / 免费 / 低耗 / 高耗 / 备用」
 * 这些 OpenCode provider，就必须有一个本地路由按 model 分流。Qoder 并入同一批
 * 组后也走这里（用 `qoder:` 前缀区分同名模型）。
 *
 * 路由规则
 * --------
 *   model 以 `qoder:` 开头              -> Qoder 网关（默认 http://127.0.0.1:8790），
 *                                          转发前剥掉 `qoder:` 前缀
 *   model 以 `cn:` / `global:` 开头      -> WorkBuddy 网关（默认 http://127.0.0.1:7863）
 *   其余 model                          -> OpenCode-Go（默认 https://opencode.ai/zen/go/v1）
 *
 * 只监听 127.0.0.1；不要把端口暴露到公网。
 *
 * 用法
 * ----
 *   node gateways/legacy-router/unified-router.js
 *   UNIFIED_ROUTER_PORT=7871 node gateways/legacy-router/unified-router.js
 *
 * 环境变量
 * --------
 *   UNIFIED_ROUTER_PORT / UNIFIED_ROUTER_HOST   默认 7871 / 127.0.0.1
 *   OPENCODE_GO_BASE                            默认 https://opencode.ai/zen/go/v1
 *   WB_GATEWAY_BASE                             默认 http://127.0.0.1:7863
 *   QD_GATEWAY_BASE                             默认 http://127.0.0.1:8790
 *   OPENCODE_GO_KEY / WB_GATEWAY_KEY / QD_API_KEY
 *                                               缺省时从 provider_config.json /
 *                                               gateways/upstream/workbuddy/config.json /
 *                                               qoder/.env.local 读
 *   OPENCODE_SESSION                            OpenCode 会话头，默认 unified-router
 *
 * 健康检查
 * --------
 *   GET /health  ->  {"ok":true,"opencode":{...},"workbuddy":{...},"qoder":{...}}
 *                    （不返回 key）
 */
'use strict';

const http = require('http');
const https = require('https');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { forwardChat } = require('./protocol_bridge');

const HOST = process.env.UNIFIED_ROUTER_HOST || '127.0.0.1';
const PORT = Number(process.env.UNIFIED_ROUTER_PORT || 7871);
const OPENCODE_BASE = (process.env.OPENCODE_GO_BASE || 'https://opencode.ai/zen/go/v1').replace(/\/+$/, '');
const WB_BASE = (process.env.WB_GATEWAY_BASE || 'http://127.0.0.1:7863').replace(/\/+$/, '');
const QD_BASE = (process.env.QD_GATEWAY_BASE || 'http://127.0.0.1:8790')
  .replace(/\/+$/, '')
  .replace(/\/v1$/, '');
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

function readEnvFile(file) {
  const out = {};
  try {
    for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#') || !trimmed.includes('=')) continue;
      const index = trimmed.indexOf('=');
      out[trimmed.slice(0, index).trim()] = trimmed.slice(index + 1).trim();
    }
  } catch {
    // missing file is fine; the caller reports the missing key
  }
  return out;
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
  let qoder = process.env.QD_API_KEY || '';
  if (!opencode) {
    opencode = findKey(cfg, (rule, base) =>
      /opencode\.ai/i.test(base) || /^opencode-go/.test(rule.providerId || ''));
  }
  if (!workbuddy) {
    workbuddy = findKey(cfg, (rule, base) =>
      /127\.0\.0\.1:7863|localhost:7863/i.test(base) || /^workbuddy-/.test(rule.providerId || ''));
  }
  if (!workbuddy) {
    const gateway = readJson(path.join(__dirname, '..', 'upstream', 'workbuddy', 'config.json'));
    if (gateway && gateway.api_key) workbuddy = String(gateway.api_key);
  }
  if (!qoder) {
    const env = readEnvFile(path.join(__dirname, '..', '..', 'providers', 'qoder', '.env.local'));
    if (env.QD_API_KEY) qoder = String(env.QD_API_KEY);
  }
  if (!qoder) {
    qoder = findKey(cfg, (rule, base) =>
      /127\.0\.0\.1:8790|localhost:8790/i.test(base) || rule.providerId === 'qoder');
  }
  return { opencode, workbuddy, qoder };
}

const KEYS = loadKeys();
if (!KEYS.opencode) {
  console.warn('[router] 缺少 OpenCode-Go key：设置 OPENCODE_GO_KEY 或检查 provider_config.json');
}
if (!KEYS.workbuddy) {
  console.warn('[router] 缺少 WorkBuddy key：设置 WB_GATEWAY_KEY 或检查 gateways/upstream/workbuddy/config.json');
}
if (!KEYS.qoder) {
  console.warn('[router] 缺少 Qoder key：设置 QD_API_KEY 或检查 providers/qoder/.env.local');
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

function isQoderModel(model) {
  return /^qoder:/i.test(String(model || ''));
}

const ALIAS_MAP_PATH = process.env.UNIFIED_MODEL_MAP ||
  path.join(os.homedir(), '.zcode', 'v2', 'model-alias-map.json');
let aliasCache = { mtime: -1, data: null };

function loadAliasMap() {
  try {
    const stat = fs.statSync(ALIAS_MAP_PATH);
    if (stat.mtimeMs !== aliasCache.mtime) {
      aliasCache = {
        mtime: stat.mtimeMs,
        data: JSON.parse(fs.readFileSync(ALIAS_MAP_PATH, 'utf8')),
      };
    }
    return aliasCache.data;
  } catch {
    return null;
  }
}

function resolveAlias(alias, model) {
  if (!alias || !model) return null;
  if (alias.models && alias.models[model]) return alias.models[model];
  const target = alias.legacy && alias.legacy[model];
  if (target && alias.models && alias.models[target]) return alias.models[target];
  return null;
}

function keyForChannel(channel) {
  if (channel === 'WB') return KEYS.workbuddy;
  if (channel === 'QD') return KEYS.qoder;
  if (channel === 'OC') return KEYS.opencode;
  return '';
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

// Try a primary upstream, then its fallbacks (WorkBuddy GB -> CN). Only
// retry on pool/rate/gateway failures; a 400/404 is a model error, not a
// reason to switch regions.
function forwardChain(req, res, body, baseUrl, pathname, search, headers, chain) {
  const attempt = (index) => {
    if (index >= chain.length) {
      return sendJson(res, 502, {
        error: { message: 'all upstreams failed: ' + chain.join(' -> '), type: 'proxy_error' },
      });
    }
    let payload;
    try {
      payload = JSON.parse(body.toString('utf8'));
      payload.model = chain[index];
    } catch (err) {
      return sendJson(res, 400, {
        error: { message: 'invalid JSON body', type: 'invalid_request_error' },
      });
    }
    const outBody = Buffer.from(JSON.stringify(payload), 'utf8');
    const attemptHeaders = { ...headers, 'content-length': String(outBody.length) };
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
        headers: attemptHeaders,
      },
      (upstreamRes) => {
        const status = upstreamRes.statusCode || 502;
        if ([429, 502, 503, 504].includes(status) && index + 1 < chain.length) {
          console.log(`[router] ${chain[index]} -> ${status}, fallback ${chain[index + 1]}`);
          upstreamRes.resume();
          attempt(index + 1);
          return;
        }
        res.writeHead(status, upstreamRes.headers);
        upstreamRes.pipe(res);
      }
    );
    upstream.on('error', (err) => {
      if (index + 1 < chain.length) {
        console.log(`[router] ${chain[index]} -> ${err.message}, fallback ${chain[index + 1]}`);
        attempt(index + 1);
      } else if (!res.headersSent) {
        sendJson(res, 502, {
          error: { message: 'unified-router upstream error: ' + err.message, type: 'proxy_error' },
        });
      } else {
        res.destroy();
      }
    });
    req.on('aborted', () => upstream.destroy());
    if (outBody.length) upstream.write(outBody);
    upstream.end();
  };
  attempt(0);
}

const server = http.createServer(async (req, res) => {
  try {
    const { pathname, search } = normalizePath(req.url);
    if (pathname === '/health') {
      const alias = loadAliasMap();
      return sendJson(res, 200, {
        ok: true,
        opencode: { base: OPENCODE_BASE, key: Boolean(KEYS.opencode) },
        workbuddy: { base: WB_BASE, key: Boolean(KEYS.workbuddy) },
        qoder: { base: QD_BASE, key: Boolean(KEYS.qoder) },
        alias: {
          path: ALIAS_MAP_PATH,
          models: alias && alias.models ? Object.keys(alias.models).length : 0,
        },
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
    const useQoder = isChat && isQoderModel(model);
    const useWorkBuddy = isChat && isWorkBuddyModel(model);
    if (!isChat && (isQoderModel(model) || isWorkBuddyModel(model))) {
      return sendJson(res, 400, {
        error: {
          message: 'WorkBuddy/Qoder models only support chat/completions',
          type: 'invalid_request_error',
        },
      });
    }

    let forwardBody = body;
    const headers = { ...req.headers };
    delete headers.host;
    delete headers['content-length'];
    delete headers['transfer-encoding'];
    if (body.length) headers['content-length'] = String(body.length);
    if (!headers['user-agent']) headers['user-agent'] = 'unified-router/1.0';

    const alias = loadAliasMap();
    const mapped = resolveAlias(alias, model);
    if (mapped) {
      const protocol = mapped.protocol || 'chat';
      const key = keyForChannel(mapped.channel);
      if (!key) {
        return sendJson(res, 502, {
          error: { message: mapped.channel + ' key not configured', type: 'configuration_error' },
        });
      }
      if (protocol !== 'chat') {
        if (!isChat) {
          return sendJson(res, 400, {
            error: {
              message: mapped.channel + ' bridged models only support chat/completions',
              type: 'invalid_request_error',
            },
          });
        }
        let payload;
        try {
          payload = JSON.parse(forwardBody.toString('utf8'));
        } catch (err) {
          return sendJson(res, 400, {
            error: { message: 'invalid JSON body', type: 'invalid_request_error' },
          });
        }
        console.log(`${req.method} ${pathname}${search} model=${model} -> ${mapped.channel}:${protocol}`);
        return forwardChat(res, {
          protocol,
          base: mapped.base,
          key,
          body: payload,
          upstreamModel: mapped.upstream,
          displayModel: model,
        });
      }

      const chain = [mapped.upstream, ...(mapped.fallbacks || [])].filter(Boolean);
      headers['authorization'] = 'Bearer ' + key;
      if (mapped.channel === 'OC') {
        headers['user-agent'] = 'opencode-cli/1.0';
        headers['x-opencode-session'] = headers['x-opencode-session'] || SESSION;
      }
      console.log(`${req.method} ${pathname}${search} model=${model} -> ${mapped.channel}` +
        (chain.length > 1 ? ` (${chain.join(' -> ')})` : ''));
      if (chain.length > 1) {
        return forwardChain(req, res, body, mapped.base, pathname, search, headers, chain);
      }

      try {
        const payload = JSON.parse(forwardBody.toString('utf8'));
        payload.model = mapped.upstream;
        forwardBody = Buffer.from(JSON.stringify(payload), 'utf8');
      } catch (err) {
        return sendJson(res, 400, {
          error: { message: 'invalid JSON body', type: 'invalid_request_error' },
        });
      }
      headers['content-length'] = String(forwardBody.length);
      return forward(req, res, forwardBody, mapped.base, pathname, search, headers);
    }

    let baseUrl;
    let label;
    if (useQoder) {
      if (!KEYS.qoder) {
        return sendJson(res, 502, {
          error: { message: 'Qoder key not configured', type: 'configuration_error' },
        });
      }
      try {
        const payload = JSON.parse(forwardBody.toString('utf8'));
        payload.model = String(model).replace(/^qoder:/i, '');
        forwardBody = Buffer.from(JSON.stringify(payload), 'utf8');
      } catch (err) {
        return sendJson(res, 400, {
          error: { message: 'invalid JSON body for Qoder model', type: 'invalid_request_error' },
        });
      }
      headers['content-length'] = String(forwardBody.length);
      baseUrl = QD_BASE + '/v1';
      headers['authorization'] = 'Bearer ' + KEYS.qoder;
      label = 'qoder';
    } else if (useWorkBuddy) {
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
      headers['user-agent'] = 'opencode-cli/1.0';
      headers['x-opencode-session'] = headers['x-opencode-session'] || SESSION;
      label = 'opencode';
    }

    console.log(`${req.method} ${pathname}${search} model=${model || '-'} -> ${label}`);
    forward(req, res, forwardBody, baseUrl, pathname, search, headers);
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
  console.log(`Qoder      : ${QD_BASE}/v1 (key=${KEYS.qoder ? 'ok' : 'missing'})`);
  const alias = loadAliasMap();
  console.log(`Alias map  : ${ALIAS_MAP_PATH} (${alias && alias.models ? Object.keys(alias.models).length : 0} models)`);
});
