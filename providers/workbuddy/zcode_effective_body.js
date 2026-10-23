#!/usr/bin/env node
/**
 * Compute the exact request-body fields ZCode will send for a given model id,
 * by replaying the engine's own rule resolution against zcode-builtin.json.
 *
 * ── 引擎语义（已对照**开源上游**逐条核对，不是从私有 bundle 反推的）────────────
 *
 * 上游：zai-org/ZCode（Apache-2.0）
 *   钉住的 commit：见 third-party/zcode/.upstream-sha
 *   相关源码（已 vendor 进本仓 third-party/zcode/）：
 *     packages/provider/src/config/model-config.ts  → ModelConfigRules.resolve() / matchesRule()
 *     packages/provider/src/config/schema.ts       → parseZCodeBuiltinModelConfigRules()（扁平化顺序）
 *     packages/provider/src/config-overlay.ts      → ConfigOverlay.overlayValue()（合并语义）
 *     config/provider/zcode-builtin.json           → 规则数据
 *
 *   1) resolve() 按 #rules 的顺序遍历，把每条命中规则的 config 叠加到累加器上 → **后者胜**。
 *   2) #rules 的扁平化顺序（schema.ts:81-101）：
 *        model → model-api → provider-site → template-model → provider-model
 *   3) matchesRule() 是**全匹配**正则 `^(?:pattern)$`；modelMatch 用 ignoreCase=true。
 *   4) model-api / provider-site 还要 apiTypeMatch 命中请求的 api type
 *      （**apiTypeMatch 缺省时对所有 api type 生效**）；provider-site 额外要
 *      baseUrlMatch 命中请求的 base URL。
 *   5) template-model / provider-model 是**精确匹配**（templateId+modelId / providerId+modelId），
 *      不走 modelMatch。
 *   6) 合并语义 overlayValue(base, next) = next === undefined ? base : next
 *      —— 后者胜，但 undefined 不清空已有值；null 会清空；数组整体替换而非合并。
 *   7) optionSpecs.reasoningLevel.map 是 JS 表达式，求值时作用域里只有
 *      `reasoningLevel` 与 `maxOutputTokens` 两个自由变量（已核对全部 120 条表达式），
 *      它必须返回 JSON 对象。
 *   8) optionSpecs.maxOutputTokens.map 是**另一条**独立规则（上游同样会施加），
 *      典型形如 `{'max_completion_tokens': maxOutputTokens}` —— 求值时用的是
 *      **调用方**请求里带的那个值（--max-output-tokens），不是常量。
 *
 * ── 输出 ────────────────────────────────────────────────────────────────
 * stdout 是 JSON：{ "<model id>": { "body": {...}, "values": [...], "level": "..." } }
 *   body / values / level 是**既有契约**（workbuddy_probe_zcode.py 依赖），
 *   config / matched 是新增的诊断信息，消费方忽略无妨。
 *
 * 用法：
 *   node zcode_effective_body.js <model id> [...]
 *   node zcode_effective_body.js --api-type openai-responses --base-url http://127.0.0.1:7863 <id>
 * 环境变量：
 *   ZCODE_BUILTIN   指定 zcode-builtin.json 路径（优先级最高）
 *   ZCODE_API_TYPE  请求的 api type（默认 openai-chat-completions）
 *   ZCODE_BASE_URL  请求的 base URL（provider-site 规则要靠它命中）
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

const HERE = __dirname;
const REPO = path.resolve(HERE, '..');

// ── 1. 找到 zcode-builtin.json ────────────────────────────────────────────
// 顺序：环境变量 → 仓内 vendor 的开源版本 → 本机 ZCode 运行时 → 桌面版安装目录
function findBuiltin() {
  const env = process.env.ZCODE_BUILTIN;
  if (env) {
    if (!fs.existsSync(env)) throw new Error(`ZCODE_BUILTIN 指向的文件不存在: ${env}`);
    return { path: env, from: 'ZCODE_BUILTIN' };
  }
  const vendored = path.join(REPO, 'third-party', 'zcode', 'zcode-builtin.json');
  if (fs.existsSync(vendored)) return { path: vendored, from: '仓内 vendor（third-party/zcode）' };

  // 本机运行时：~/.zcode/v2/runtime/provider/<platform>/<version>/<endpoint>/zcode-builtin.json
  const runtimeRoot = path.join(os.homedir(), '.zcode', 'v2', 'runtime', 'provider');
  if (fs.existsSync(runtimeRoot)) {
    const found = [];
    for (const platform of fs.readdirSync(runtimeRoot)) {
      const pDir = path.join(runtimeRoot, platform);
      if (!fs.statSync(pDir).isDirectory()) continue;
      for (const ver of fs.readdirSync(pDir)) {
        const vDir = path.join(pDir, ver);
        if (!fs.statSync(vDir).isDirectory()) continue;
        for (const ep of fs.readdirSync(vDir)) {
          const f = path.join(vDir, ep, 'zcode-builtin.json');
          if (fs.existsSync(f)) found.push(f);
        }
      }
    }
    if (found.length) {
      found.sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
      return { path: found[0], from: `本机 ZCode 运行时（最新：${path.basename(path.dirname(found[0]))}）` };
    }
  }

  // 桌面版安装目录（Electron 应用，包名带 @ 前缀）
  const appRoots = [
    path.join(os.homedir(), 'AppData', 'Local', 'Programs', '@opencodedesktop'),
    path.join(os.homedir(), 'AppData', 'Local', 'Programs', 'ZCode'),
  ];
  for (const root of appRoots) {
    const f = path.join(root, 'resources', 'config', 'provider', 'zcode-builtin.json');
    if (fs.existsSync(f)) return { path: f, from: 'ZCode 桌面版安装目录' };
  }
  throw new Error(
    '找不到 zcode-builtin.json。已尝试：环境变量、仓内 third-party/zcode/、' +
      '~/.zcode/v2/runtime/provider/、桌面版安装目录。' +
      '请用 ZCODE_BUILTIN 显式指定路径。'
  );
}

// ── 2. 规则扁平化（顺序同上游 schema.ts）────────────────────────────────
function flattenRules(mcr) {
  const rules = [];
  const push = (arr, type) => {
    for (const r of arr || []) rules.push({ ...r, type });
  };
  push(mcr.modelRules, 'model');
  push(mcr.modelApiRules, 'model-api');
  push(mcr.providerSiteRules, 'provider-site');
  push(mcr.templateModelRules, 'template-model');
  push(mcr.builtinProviderModelRules, 'provider-model');
  return rules;
}

// ── 3. 合并语义（上游 ConfigOverlay.overlayValue）───────────────────────
function overlayValue(base, next) {
  if (next === undefined) return base;
  if (next === null) return null;
  if (Array.isArray(next)) return next;
  if (typeof next === 'object') {
    if (base === null || base === undefined || typeof base !== 'object' || Array.isArray(base)) {
      return next;
    }
    const out = { ...base };
    for (const [k, v] of Object.entries(next)) out[k] = overlayValue(base[k], v);
    return out;
  }
  return next;
}

// ── 4. 规则匹配与求解 ───────────────────────────────────────────────────
const matchesRule = (pattern, value, ignoreCase = false) =>
  new RegExp(`^(?:${pattern})$`, ignoreCase ? 'i' : undefined).test(value ?? '');

function resolveConfig(rules, input) {
  let result = {};
  const matched = [];
  for (const rule of rules) {
    if (rule.type === 'provider-model' || rule.type === 'manual-provider-model') {
      if (rule.providerId !== input.providerId || rule.modelId !== input.modelId) continue;
      result = overlayValue(result, rule.config);
      matched.push(rule.type);
      continue;
    }
    if (rule.type === 'template-model') {
      if (rule.templateId !== input.templateId || rule.modelId !== input.modelId) continue;
      result = overlayValue(result, rule.config);
      matched.push(rule.type);
      continue;
    }
    if (!matchesRule(rule.modelMatch, input.modelId, true)) continue;
    if ((rule.type === 'model-api' || rule.type === 'provider-site') && rule.apiTypeMatch !== undefined) {
      if (input.apiType == null || !matchesRule(rule.apiTypeMatch, input.apiType)) continue;
    }
    if (rule.type === 'provider-site') {
      if (input.baseUrl == null || !matchesRule(rule.baseUrlMatch, input.baseUrl)) continue;
    }
    result = overlayValue(result, rule.config);
    matched.push(rule.type);
  }
  return { config: result, matched };
}

// ── 5. 求值 map 表达式（作用域只有 reasoningLevel / maxOutputTokens）────
function evalMap(expr, level, maxTokens) {
  const fn = new Function('reasoningLevel', 'maxOutputTokens', `return (${expr});`);
  const out = fn(level, maxTokens);
  if (out === null || typeof out !== 'object' || Array.isArray(out)) {
    throw new Error('map did not return an object');
  }
  return out;
}

// ── 5b. 用户 providerModelRules（provider_config.json）──────────────
// The builtin file only contains ZCode's shipped rules. Per-model overrides
// written by the sync scripts live in provider_config.json and are applied
// last by the engine, so append them after the builtin rules.
function loadUserProviderRules() {
  const file = process.env.ZCODE_PERSONAL_PROVIDER_CONFIG_FILE ||
    path.join(os.homedir(), '.zcode', 'v2', 'provider_config.json');
  try {
    const cfg = JSON.parse(fs.readFileSync(file, 'utf8'));
    const modelConfig = (cfg.config && cfg.config.modelConfigRules) || {};
    const out = [];
    for (const entry of modelConfig.providerModelRules || []) {
      out.push({
        type: 'provider-model',
        providerId: entry.providerId,
        modelId: entry.modelId,
        config: entry.config || {},
      });
    }
    for (const entry of modelConfig.manualProviderModelRules || []) {
      out.push({
        type: 'manual-provider-model',
        providerId: entry.providerId,
        modelId: entry.modelId,
        config: entry.config || {},
      });
    }
    return out;
  } catch {
    return [];
  }
}

// ── 6. 主流程 ───────────────────────────────────────────────────────────
function parseArgs(argv) {
  const opts = { ids: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--api-type') opts.apiType = argv[++i];
    else if (a === '--base-url') opts.baseUrl = argv[++i];
    else if (a === '--provider-id') opts.providerId = argv[++i];
    else if (a === '--template-id') opts.templateId = argv[++i];
    else if (a === '--max-output-tokens') opts.maxTokens = Number(argv[++i]);
    else if (a === '--verbose') opts.verbose = true;
    else opts.ids.push(a);
  }
  return opts;
}

const opts = parseArgs(process.argv.slice(2));
if (!opts.ids.length) {
  console.error('usage: node zcode_effective_body.js [--api-type T] [--base-url U] <model id> [...]');
  process.exit(2);
}

const API_TYPE = opts.apiType || process.env.ZCODE_API_TYPE || 'openai-chat-completions';
const BASE_URL = opts.baseUrl || process.env.ZCODE_BASE_URL || undefined;
// maxOutputTokens 是 map 表达式作用域里的第二个自由变量。
// 它代表**调用方**请求时带的 max output tokens —— 探测脚本会把自己的取值传进来，
// 这样 `{'max_completion_tokens': maxOutputTokens}` 求出来就是调用方要的那个数，
// 而不是脚本里写死的常量。
const MAX_TOKENS = opts.maxTokens || Number(process.env.ZCODE_MAX_OUTPUT_TOKENS) || 1024;

const { path: builtinPath, from: builtinFrom } = findBuiltin();
const raw = JSON.parse(fs.readFileSync(builtinPath, 'utf8'));
const rules = [...flattenRules(raw.config.modelConfigRules), ...loadUserProviderRules()];
if (opts.verbose) {
  console.error(`builtin: ${builtinPath}  (${builtinFrom})`);
  console.error(`规则总数: ${rules.length}  apiType=${API_TYPE}  baseUrl=${BASE_URL ?? '(无)'}`);
}

// ZCode 每个模型的默认推理档位 = 解析出的 values 列表里的第一个；通用回退是 "enabled"。
function pickLevel(values) {
  if (!values || !values.length) return 'enabled';
  if (values.includes('enabled')) return 'enabled';
  if (values.includes('high')) return 'high';
  return values[0];
}

const result = {};
for (const id of opts.ids) {
  const providerId = opts.providerId ||
    (rules.find((rule) => rule.modelId === id &&
      (rule.type === 'provider-model' || rule.type === 'manual-provider-model')) || {}).providerId;
  const { config, matched } = resolveConfig(rules, {
    modelId: id,
    apiType: API_TYPE,
    baseUrl: BASE_URL,
    providerId,
    templateId: opts.templateId,
  });
  const spec = config?.optionSpecs?.reasoningLevel || {};
  const values = Array.isArray(spec.values) ? spec.values : null;
  const level = pickLevel(values);

  let body = {};
  let error = null;
  if (typeof spec.map === 'string') {
    try {
      body = evalMap(spec.map, level, MAX_TOKENS);
    } catch (e) {
      error = String(e.message || e);
    }
  }
  // maxOutputTokens 的 map 也可能被单独命中
  const moSpec = config?.optionSpecs?.maxOutputTokens || {};
  if (!error && typeof moSpec.map === 'string') {
    try {
      Object.assign(body, evalMap(moSpec.map, level, MAX_TOKENS));
    } catch (e) {
      error = String(e.message || e);
    }
  }

  result[id] = { body, values, level, error, config, matched: [...new Set(matched)] };
}

console.log(JSON.stringify(result, null, 1));
