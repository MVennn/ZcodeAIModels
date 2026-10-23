'use strict';
/**
 * Protocol bridge: OpenAI Chat Completions -> Anthropic Messages / OpenAI
 * Responses, and the reverse for the response.
 *
 * The unified router exposes four chat providers. A few OpenCode-Go models are
 * only available over `messages` or `responses`; this bridge lets them live in
 * the same chat groups without asking ZCode to speak three protocols.
 *
 * Upstream calls are non-streaming; the bridge synthesizes the chat SSE that
 * ZCode expects. That keeps the translation small and deterministic (no SSE
 * delta accumulation across chunk boundaries). The trade-off is that bridged
 * models deliver their text in one chunk instead of token-by-token.
 */

const http = require('http');
const https = require('https');
const { randomUUID } = require('crypto');

function textOf(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => (typeof part === 'string' ? part : (part && (part.text || part.content)) || ''))
      .join('');
  }
  return '';
}

function safeJson(value) {
  if (value && typeof value === 'object') return value;
  if (typeof value !== 'string') return {};
  try {
    return JSON.parse(value);
  } catch {
    return { value };
  }
}

function requestJson(url, headers, payload, timeoutMs = 120000) {
  return new Promise((resolve) => {
    const target = new URL(url);
    const transport = target.protocol === 'https:' ? https : http;
    const body = Buffer.from(JSON.stringify(payload));
    const request = transport.request(
      {
        protocol: target.protocol,
        hostname: target.hostname,
        port: target.port || (target.protocol === 'https:' ? 443 : 80),
        method: 'POST',
        path: target.pathname + target.search,
        headers: { ...headers, 'content-length': String(body.length) },
      },
      (response) => {
        const chunks = [];
        response.on('data', (chunk) => chunks.push(chunk));
        response.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          let json = null;
          try {
            json = JSON.parse(text);
          } catch {
            // leave null; the caller reports the text
          }
          resolve({ status: response.statusCode || 502, json, text });
        });
      }
    );
    request.on('error', (error) => resolve({ status: 502, json: null, text: error.message }));
    request.setTimeout(timeoutMs, () => request.destroy(new Error('upstream timeout')));
    request.write(body);
    request.end();
  });
}

function chatToAnthropic(body, model) {
  const systemParts = [];
  const messages = [];
  for (const message of body.messages || []) {
    const role = message.role;
    if (role === 'system') {
      systemParts.push(textOf(message.content));
      continue;
    }
    if (role === 'tool') {
      messages.push({
        role: 'user',
        content: [{
          type: 'tool_result',
          tool_use_id: message.tool_call_id || '',
          content: textOf(message.content),
        }],
      });
      continue;
    }
    if (role === 'assistant') {
      const blocks = [];
      const text = textOf(message.content);
      if (text) blocks.push({ type: 'text', text });
      for (const call of message.tool_calls || []) {
        blocks.push({
          type: 'tool_use',
          id: call.id || 'call_' + randomUUID().slice(0, 8),
          name: (call.function && call.function.name) || 'tool',
          input: safeJson(call.function && call.function.arguments),
        });
      }
      messages.push({ role: 'assistant', content: blocks.length ? blocks : [{ type: 'text', text: '' }] });
      continue;
    }
    messages.push({ role: 'user', content: [{ type: 'text', text: textOf(message.content) }] });
  }
  if (!messages.length) messages.push({ role: 'user', content: [{ type: 'text', text: '' }] });

  const tools = (body.tools || []).map((tool) => ({
    name: (tool.function && tool.function.name) || 'tool',
    description: (tool.function && tool.function.description) || '',
    input_schema: (tool.function && tool.function.parameters) || { type: 'object', properties: {} },
  }));

  const payload = {
    model,
    max_tokens: body.max_completion_tokens || body.max_tokens || 4096,
    messages,
    stream: false,
  };
  if (systemParts.filter(Boolean).length) payload.system = systemParts.filter(Boolean).join('\n\n');
  if (tools.length) payload.tools = tools;
  if (body.temperature !== undefined) payload.temperature = body.temperature;
  if (body.top_p !== undefined) payload.top_p = body.top_p;
  if (body.stop) payload.stop_sequences = Array.isArray(body.stop) ? body.stop : [body.stop];
  if (body.tool_choice === 'auto') payload.tool_choice = { type: 'auto' };
  else if (body.tool_choice === 'none') payload.tool_choice = { type: 'none' };
  else if (body.tool_choice && body.tool_choice.function) {
    payload.tool_choice = { type: 'tool', name: body.tool_choice.function.name };
  }
  return payload;
}

function anthropicToChat(data, model) {
  const texts = [];
  const reasoning = [];
  const toolCalls = [];
  for (const block of (data && data.content) || []) {
    if (block.type === 'text') texts.push(block.text || '');
    else if (block.type === 'thinking') reasoning.push(block.thinking || '');
    else if (block.type === 'tool_use') {
      toolCalls.push({
        id: block.id || 'call_' + randomUUID().slice(0, 8),
        type: 'function',
        function: {
          name: block.name || 'tool',
          arguments: JSON.stringify(block.input || {}),
        },
      });
    }
  }
  const message = { role: 'assistant', content: texts.join('') };
  if (reasoning.length) message.reasoning_content = reasoning.join('');
  if (toolCalls.length) message.tool_calls = toolCalls;
  const stop = data && data.stop_reason;
  const finish = toolCalls.length ? 'tool_calls'
    : stop === 'max_tokens' ? 'length'
      : stop === 'tool_use' ? 'tool_calls'
        : 'stop';
  const usage = data && data.usage
    ? {
      prompt_tokens: data.usage.input_tokens || 0,
      completion_tokens: data.usage.output_tokens || 0,
      total_tokens: (data.usage.input_tokens || 0) + (data.usage.output_tokens || 0),
    }
    : undefined;
  return {
    id: 'chatcmpl-' + randomUUID(),
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [{ index: 0, message, finish_reason: finish }],
    ...(usage ? { usage } : {}),
  };
}

function chatToResponses(body, model) {
  const systemParts = [];
  const input = [];
  for (const message of body.messages || []) {
    const role = message.role;
    if (role === 'system') {
      systemParts.push(textOf(message.content));
      continue;
    }
    if (role === 'tool') {
      input.push({
        type: 'function_call_output',
        call_id: message.tool_call_id || '',
        output: textOf(message.content),
      });
      continue;
    }
    if (role === 'assistant') {
      const text = textOf(message.content);
      if (text) input.push({ role: 'assistant', content: text });
      for (const call of message.tool_calls || []) {
        input.push({
          type: 'function_call',
          call_id: call.id || 'call_' + randomUUID().slice(0, 8),
          name: (call.function && call.function.name) || 'tool',
          arguments: (call.function && call.function.arguments) || '{}',
        });
      }
      continue;
    }
    input.push({ role: 'user', content: textOf(message.content) });
  }

  const tools = (body.tools || []).map((tool) => ({
    type: 'function',
    name: (tool.function && tool.function.name) || 'tool',
    description: (tool.function && tool.function.description) || '',
    parameters: (tool.function && tool.function.parameters) || { type: 'object', properties: {} },
  }));

  const payload = { model, input, stream: false };
  if (systemParts.filter(Boolean).length) payload.instructions = systemParts.filter(Boolean).join('\n\n');
  if (tools.length) payload.tools = tools;
  const max = body.max_completion_tokens || body.max_tokens;
  if (max) payload.max_output_tokens = max;
  if (body.temperature !== undefined) payload.temperature = body.temperature;
  if (body.top_p !== undefined) payload.top_p = body.top_p;
  if (body.tool_choice === 'auto' || body.tool_choice === 'none') payload.tool_choice = body.tool_choice;
  else if (body.tool_choice && body.tool_choice.function) {
    payload.tool_choice = { type: 'function', name: body.tool_choice.function.name };
  }
  return payload;
}

function responsesToChat(data, model) {
  const texts = [];
  const reasoning = [];
  const toolCalls = [];
  for (const item of (data && data.output) || []) {
    if (item.type === 'message') {
      for (const part of item.content || []) {
        if (part.type === 'output_text' || part.type === 'text') texts.push(part.text || '');
      }
    } else if (item.type === 'function_call') {
      toolCalls.push({
        id: item.call_id || item.id || 'call_' + randomUUID().slice(0, 8),
        type: 'function',
        function: {
          name: item.name || 'tool',
          arguments: item.arguments || '{}',
        },
      });
    } else if (item.type === 'reasoning') {
      for (const part of item.summary || []) reasoning.push(part.text || '');
    }
  }
  if (!texts.length && data && typeof data.output_text === 'string') texts.push(data.output_text);
  const message = { role: 'assistant', content: texts.join('') };
  if (reasoning.length) message.reasoning_content = reasoning.join('');
  if (toolCalls.length) message.tool_calls = toolCalls;
  const finish = toolCalls.length ? 'tool_calls'
    : data && data.status === 'incomplete' ? 'length'
      : 'stop';
  const usage = data && data.usage
    ? {
      prompt_tokens: data.usage.input_tokens || 0,
      completion_tokens: data.usage.output_tokens || 0,
      total_tokens: (data.usage.input_tokens || 0) + (data.usage.output_tokens || 0),
    }
    : undefined;
  return {
    id: 'chatcmpl-' + randomUUID(),
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [{ index: 0, message, finish_reason: finish }],
    ...(usage ? { usage } : {}),
  };
}

function sendJson(res, status, payload) {
  const text = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(text),
  });
  res.end(text);
}

function sendSse(res, chat) {
  res.writeHead(200, {
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-cache',
    connection: 'keep-alive',
  });
  const base = {
    id: chat.id,
    object: 'chat.completion.chunk',
    created: chat.created,
    model: chat.model,
  };
  const send = (delta, finish = null) => {
    res.write('data: ' + JSON.stringify({
      ...base,
      choices: [{ index: 0, delta, finish_reason: finish }],
    }) + '\n\n');
  };
  send({ role: 'assistant' });
  const message = chat.choices[0].message;
  if (message.reasoning_content) send({ reasoning_content: message.reasoning_content });
  if (message.content) send({ content: message.content });
  for (let index = 0; index < (message.tool_calls || []).length; index += 1) {
    send({ tool_calls: [{ index, ...message.tool_calls[index] }] });
  }
  send({}, chat.choices[0].finish_reason);
  res.write('data: [DONE]\n\n');
  res.end();
}

async function forwardChat(res, options) {
  const { protocol, base, key, body, upstreamModel, displayModel } = options;
  let payload;
  let headers;
  let url;
  if (protocol === 'messages') {
    payload = chatToAnthropic(body, upstreamModel);
    headers = {
      'content-type': 'application/json',
      'user-agent': 'opencode-cli/1.0',
      'x-opencode-session': 'unified-bridge',
      'x-api-key': key,
      'anthropic-version': '2023-06-01',
    };
    url = base.replace(/\/+$/, '') + '/messages';
  } else if (protocol === 'responses') {
    payload = chatToResponses(body, upstreamModel);
    headers = {
      'content-type': 'application/json',
      'user-agent': 'opencode-cli/1.0',
      'x-opencode-session': 'unified-bridge',
      authorization: 'Bearer ' + key,
    };
    url = base.replace(/\/+$/, '') + '/responses';
  } else {
    sendJson(res, 500, { error: { message: 'unknown bridge protocol: ' + protocol, type: 'proxy_error' } });
    return;
  }

  const result = await requestJson(url, headers, payload);
  if (result.status < 200 || result.status >= 300) {
    const message = (result.json && result.json.error && result.json.error.message)
      || (result.json && result.json.message)
      || result.text.slice(0, 500)
      || ('upstream HTTP ' + result.status);
    sendJson(res, 502, {
      error: { message: 'bridge upstream error: ' + message, type: 'upstream_error' },
    });
    return;
  }
  if (!result.json) {
    sendJson(res, 502, {
      error: { message: 'bridge upstream returned non-JSON: ' + result.text.slice(0, 300), type: 'upstream_error' },
    });
    return;
  }
  const chat = protocol === 'messages'
    ? anthropicToChat(result.json, displayModel)
    : responsesToChat(result.json, displayModel);
  if (body.stream) sendSse(res, chat);
  else sendJson(res, 200, chat);
}

module.exports = { forwardChat };
