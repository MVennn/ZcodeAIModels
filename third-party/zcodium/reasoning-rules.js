#!/usr/bin/env node
/**
 * 思考参数（reasoning / thinking）规则助手
 *
 * 来源：soulvon/AnyBridge@f40dcc23c76f1b641462fb2a5544a252c5738b27 —
 *       https://github.com/soulvon/AnyBridge/blob/f40dcc23c76f1b641462fb2a5544a252c5738b27/sidecar/lib/thinking-effort.js — MIT
 * 来源：ZCodium-project/ZCodium@192f9b8c7b7b61c694920203f1b5c7524bdc7d09 —
 *       https://github.com/ZCodium-project/ZCodium/blob/192f9b8c7b7b61c694920203f1b5c7524bdc7d09/config/provider/zcode-builtin.json — MIT
 *
 * 借鉴方式：只取「协议 → 该协议认的思考字段」这条映射，以及内置规则里三条通用
 * `modelApiRules` 的表达式写法；实现是本仓自己写的，不是整文件照搬。
 *
 * 用途：解决本仓踩过的那个坑 —— ZCode 内置通用规则**无条件**往请求体里塞思考字段，
 * 上游不认就 400。本文件提供两件事：
 *
 *   1. `recommendedReasoningLevelMap()` —— 按**目标协议**算出「最小且正确」的
 *      `optionSpecs.reasoningLevel.map`：协议认哪个字段就只发哪个，不多发一个。
 *      （协议 → 字段的映射借鉴 AnyBridge；表达式写法与 ZCode 内置规则对齐。）
 *
 *   2. `checkBuiltin()` —— 把本机 ZCode 的内置规则文件（`zcode-builtin.json`）
 *      与 `zcode-builtin-reasoning-rules.json` 这份**可引用的上游切片**逐条比对，
 *      报出漂移。上游切片来自 MIT 授权的 ZCodium，是 ZCode 内置规则的独立副本；
 *      本机客户端升级后规则可能变，漂移了就说明要重探。
 *
 * 用法：
 *   node upstream/reasoning-rules.js map --api-type=openai-chat-completions --effort=high
 *   node upstream/reasoning-rules.js map --api-type=anthropic-messages --effort=disabled
 *   node upstream/reasoning-rules.js check                       # 读环境变量 ZCODE_BUILTIN
 *   node upstream/reasoning-rules.js check /path/to/zcode-builtin.json
 *
 * 退出码：0 = 正常 / 一致；1 = 有漂移或参数非法；2 = 用法错误。
 */
'use strict';

const fs = require('fs');
const path = require('path');

const EXCERPT_PATH = path.join(__dirname, 'zcode-builtin-reasoning-rules.json');

/** 切片来源（抄录自上游，勿手改 `_source`）。 */
const EXCERPT_SOURCE = {
  repo: 'https://github.com/ZCodium-project/ZCodium',
  sha: '192f9b8c7b7b61c694920203f1b5c7524bdc7d09',
  path: 'config/provider/zcode-builtin.json',
  license: 'MIT',
};

/**
 * 协议 → 「该协议认的思考字段」映射。
 *
 * - anthropic-messages   : `thinking.type` + `output_config.effort`
 * - openai-responses     : `reasoning.effort`
 * - openai-chat-completions: `reasoning_effort`
 * - 其它/未知            : 一个字段都不发
 *
 * 依据：ZCodium 的 `config/provider/zcode-builtin.json` 里三条通用 `modelApiRules`
 * （modelMatch 均为 `.*`）分别就是上面三组字段；
 * 「只发该协议认的字段」这条取舍借鉴 AnyBridge `sidecar/lib/thinking-effort.js`
 * 的 `applyThinkingToPayload`。
 */
const PROTOCOL_FIELDS = {
  'anthropic-messages': ['thinking', 'output_config'],
  'openai-responses': ['reasoning'],
  'openai-chat-completions': ['reasoning_effort'],
};

/**
 * 算出某模型在某协议下的 `optionSpecs.reasoningLevel.map`。
 *
 * @param {object} opts
 * @param {string} opts.apiType      ZCode 的 `api.type`（三种协议之一）
 * @param {string} [opts.effort]     档位：disabled|none|low|medium|high|xhigh|max|enabled
 * @param {string[]} [opts.supportedEfforts] 该模型支持的档位；用于把档位钳到模型词表内
 * @param {boolean} [opts.supportsThinking=false] 模型是否支持思考；false → 发空 map
 * @returns {{map: string, fields: string[], clamped: boolean, note: string}}
 */
function recommendedReasoningLevelMap(opts) {
  const apiType = String(opts.apiType || '').trim();
  const effort = String(opts.effort || 'high').trim();
  const supported = Array.isArray(opts.supportedEfforts) ? opts.supportedEfforts : [];
  const supportsThinking = opts.supportsThinking !== false;

  const fields = PROTOCOL_FIELDS[apiType] || null;
  if (!fields) {
    return {
      map: '{}',
      fields: [],
      clamped: false,
      note: `未知协议 "${apiType}"：不发任何思考字段（发空 map 覆盖 ZCode 内置通用规则）`,
    };
  }
  if (!supportsThinking) {
    return {
      map: '{}',
      fields: [],
      clamped: false,
      note: '模型不支持思考：发空 map，一个思考字段都不发',
    };
  }

  // 档位归一：disabled/none 都算「关」；enabled 视作 high（与 ZCode 内置规则同口径）。
  let level = effort;
  if (level === 'disabled' || level === 'none') level = 'disabled';
  else if (level === 'enabled') level = 'high';

  // 钳制到模型自己的档位词表（模型不认的档位发过去等于 400）。
  let clamped = false;
  if (level !== 'disabled' && supported.length) {
    if (!supported.includes(level)) {
      const order = ['none', 'low', 'medium', 'high', 'xhigh', 'max'];
      const rank = order.indexOf(level);
      let picked = null;
      for (let i = rank - 1; i >= 0 && picked === null; i--) {
        if (supported.includes(order[i])) picked = order[i];
      }
      for (let i = rank + 1; i < order.length && picked === null; i++) {
        if (supported.includes(order[i])) picked = order[i];
      }
      if (picked) {
        level = picked;
        clamped = true;
      }
    }
  }

  let map;
  if (level === 'disabled') {
    // 「显式关掉」：anthropic 用 thinking.type=disabled；OpenAI 侧用 none。
    if (apiType === 'anthropic-messages') {
      map = { thinking: { type: 'disabled' } };
    } else {
      map = apiType === 'openai-responses'
        ? { reasoning: { effort: 'none' } }
        : { reasoning_effort: 'none' };
    }
  } else if (apiType === 'anthropic-messages') {
    map = { thinking: { type: 'enabled' }, output_config: { effort: level } };
  } else if (apiType === 'openai-responses') {
    map = { reasoning: { effort: level } };
  } else {
    map = { reasoning_effort: level };
  }

  return {
    map: JSON.stringify(map),
    fields,
    clamped,
    note: clamped
      ? `档位已被钳到模型词表内（${level}）`
      : `按 ${apiType} 只发 ${fields.join(' + ')}`,
  };
}

/** 读上游切片。 */
function loadExcerpt(excerptPath) {
  const p = excerptPath || EXCERPT_PATH;
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

/**
 * 从一份 `zcode-builtin.json` 里抽出「通用思考规则」（modelMatch 为 `.*` 的 modelApiRules）。
 *
 * @param {object} builtin 解析后的内置规则 JSON
 * @returns {Array<{index:number, apiTypeMatch:string, modelMatch:string, map:string, values:string[]}>}
 */
function genericReasoningRules(builtin) {
  const rules = (((builtin || {}).config || {}).modelConfigRules || {}).modelApiRules || [];
  return rules
    .map((r, i) => {
      const rl = (((r || {}).config || {}).optionSpecs || {}).reasoningLevel || {};
      return {
        index: i,
        apiTypeMatch: r.apiTypeMatch,
        modelMatch: r.modelMatch,
        map: rl.map == null ? null : String(rl.map),
        values: rl.values || null,
      };
    })
    .filter((r) => r.modelMatch === '.*' && r.map);
}

/**
 * 把本机内置规则与上游切片比对。
 *
 * @param {string} builtinPath 内置规则文件路径
 * @param {string} [excerptPath] 上游切片路径
 * @returns {{ok:boolean, builtinPath:string, rules:Array, drifts:Array}}
 */
function checkBuiltin(builtinPath, excerptPath) {
  const excerpt = loadExcerpt(excerptPath);
  const builtin = JSON.parse(fs.readFileSync(builtinPath, 'utf8'));
  const local = genericReasoningRules(builtin);
  const expected = (excerpt.rules || []).filter((r) => r.modelMatch === '.*');

  const drifts = [];
  for (const want of expected) {
    const got = local.find((r) => r.apiTypeMatch === want.apiTypeMatch);
    if (!got) {
      drifts.push({ apiTypeMatch: want.apiTypeMatch, kind: 'missing', expected: want.map, actual: null });
    } else if (got.map !== want.map) {
      drifts.push({ apiTypeMatch: want.apiTypeMatch, kind: 'changed', expected: want.map, actual: got.map });
    }
  }
  for (const got of local) {
    if (!expected.some((r) => r.apiTypeMatch === got.apiTypeMatch)) {
      drifts.push({ apiTypeMatch: got.apiTypeMatch, kind: 'extra', expected: null, actual: got.map });
    }
  }

  return { ok: drifts.length === 0, builtinPath, rules: local, drifts };
}

// ---------------------------------------------------------------- CLI

function parseArgs(argv) {
  const out = { _: [] };
  for (const a of argv) {
    if (a.startsWith('--')) {
      const eq = a.indexOf('=');
      if (eq === -1) out[a.slice(2)] = 'true';
      else out[a.slice(2, eq)] = a.slice(eq + 1);
    } else {
      out._.push(a);
    }
  }
  return out;
}

function defaultBuiltinPath() {
  const env = process.env.ZCODE_BUILTIN;
  if (env) return env;

  // 1) 本机 ZCode 运行时（按版本/端点刷新的那份，最贴近"本机实际用的规则"）
  const home = process.env.USERPROFILE || process.env.HOME || '';
  const runtimeRoot = path.join(home, '.zcode', 'v2', 'runtime', 'provider');
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
      return found[0];
    }
  }

  // 2) 桌面版安装目录（Electron 应用，包名带 @ 前缀）
  for (const root of [
    path.join(home, 'AppData', 'Local', 'Programs', '@opencodedesktop'),
    path.join(home, 'AppData', 'Local', 'Programs', 'ZCode'),
  ]) {
    const f = path.join(root, 'resources', 'config', 'provider', 'zcode-builtin.json');
    if (fs.existsSync(f)) return f;
  }

  // 3) 仓内 vendor 的开源版本（zai-org/ZCode，Apache-2.0）
  const vendored = path.resolve(__dirname, '..', 'zcode', 'zcode-builtin.json');
  if (fs.existsSync(vendored)) return vendored;

  return path.join(home, '.zcode', 'v2', 'config', 'provider', 'zcode-builtin.json');
}

function main(argv) {
  const args = parseArgs(argv);
  const cmd = args._[0];

  if (cmd === 'map') {
    const supported = args['supported-efforts']
      ? String(args['supported-efforts']).split(',').map((s) => s.trim()).filter(Boolean)
      : [];
    const res = recommendedReasoningLevelMap({
      apiType: args['api-type'] || '',
      effort: args.effort || 'high',
      supportedEfforts: supported,
      supportsThinking: args['supports-thinking'] !== 'false',
    });
    process.stdout.write(res.map + '\n');
    process.stderr.write('# ' + res.note + '\n');
    return 0;
  }

  if (cmd === 'check') {
    const builtinPath = args._[1] || defaultBuiltinPath();
    if (!fs.existsSync(builtinPath)) {
      process.stderr.write('内置规则文件不存在: ' + builtinPath + '\n');
      process.stderr.write('用环境变量 ZCODE_BUILTIN 指定，或作为第一个位置参数传入。\n');
      return 2;
    }
    const res = checkBuiltin(builtinPath);
    process.stdout.write('内置规则: ' + res.builtinPath + '\n');
    for (const r of res.rules) {
      process.stdout.write('  [' + r.apiTypeMatch + '] ' + String(r.map).replace(/\s+/g, ' ').slice(0, 110) + '\n');
    }
    if (res.ok) {
      process.stdout.write('结果: 与上游切片一致（ZCodium@' + EXCERPT_SOURCE.sha.slice(0, 12) + '）\n');
      return 0;
    }
    process.stdout.write('结果: 存在漂移 ' + res.drifts.length + ' 处\n');
    for (const d of res.drifts) {
      process.stdout.write('  - ' + d.apiTypeMatch + ' [' + d.kind + ']\n');
      if (d.expected) process.stdout.write('    上游: ' + String(d.expected).replace(/\s+/g, ' ').slice(0, 160) + '\n');
      if (d.actual) process.stdout.write('    本机: ' + String(d.actual).replace(/\s+/g, ' ').slice(0, 160) + '\n');
    }
    process.stdout.write('→ 内置规则已变，思考参数矩阵需要重测（见 docs/PITFALLS.md §2）。\n');
    return 1;
  }

  process.stderr.write(
    '用法:\n' +
    '  node upstream/reasoning-rules.js map --api-type=<协议> [--effort=<档位>] ' +
    '[--supported-efforts=a,b] [--supports-thinking=false]\n' +
    '  node upstream/reasoning-rules.js check [zcode-builtin.json]\n'
  );
  return 2;
}

if (require.main === module) {
  process.exit(main(process.argv.slice(2)));
}

module.exports = {
  PROTOCOL_FIELDS,
  EXCERPT_PATH,
  EXCERPT_SOURCE,
  recommendedReasoningLevelMap,
  genericReasoningRules,
  checkBuiltin,
  loadExcerpt,
};
