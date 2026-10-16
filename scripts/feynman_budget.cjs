// Preflight guard for bounded text-only extraction, loaded through NODE_OPTIONS.
const fs = require('node:fs');
const models = require('./feynman_models.json');
const originalFetch = globalThis.fetch;
globalThis.fetch = async function(input, init) {
  const request = new Request(input, init);
  const url = new URL(request.url);
  if (url.origin !== 'https://api.openai.com')
    throw new Error('Budget guard: unsupported provider or endpoint');
  if (url.pathname !== '/v1/responses' || request.method !== 'POST')
    throw new Error('Budget guard: unsupported OpenAI endpoint');
  const payload = JSON.parse(await request.clone().text());
  const model = process.env.FEYNMAN_MODEL || 'gpt-4.1';
  const rates = Object.hasOwn(models, model) ? models[model] : null;
  const maxOutput = Number(process.env.FEYNMAN_MAX_OUTPUT_TOKENS || 5000);
  if (!rates || payload.model !== model || payload.previous_response_id || payload.conversation)
    throw new Error('Budget guard: unsupported model or server-side context');
  if (!Number.isInteger(maxOutput) || maxOutput < 1 || maxOutput > rates.max_output_tokens)
    throw new Error('Budget guard: invalid output cap');
  // No model tools, external search, or delegated API work in this bounded pilot.
  delete payload.tools;
  delete payload.tool_choice;
  payload.max_output_tokens = maxOutput;
  payload.service_tier = 'default';
  const body = JSON.stringify(payload);
  const serialized = Buffer.byteLength(body, 'utf8');
  // Text-only byte count upper-bounds tokenizer pieces; add framing headroom.
  if (/"(?:input_image|input_file|image_url|file_id)"/.test(body))
    throw new Error('Budget guard: non-text input is not supported');
  const bound = ((serialized + 4096) * rates.input + maxOutput * rates.output) / 1000000;
  const path = process.env.FEYNMAN_BUDGET_LEDGER;
  const state = JSON.parse(fs.readFileSync(path, 'utf8'));
  if (!Number.isFinite(state.budget_usd) || state.budget_usd <= 0 ||
      !Number.isFinite(state.reserved_usd) || state.reserved_usd < 0 || !Array.isArray(state.requests))
    throw new Error('Budget guard: invalid ledger');
  if (state.reserved_usd + bound > state.budget_usd)
    throw new Error('Budget guard: request exceeds remaining reserved budget');
  state.reserved_usd += bound;
  state.requests.push({model, input_bytes: serialized, max_output_tokens: maxOutput,
    pricing_per_million_usd: rates, reserved_usd: bound});
  fs.writeFileSync(path, JSON.stringify(state, null, 2));
  // Keep the reservation even on failure: retry attempts cannot overspend it.
  const headers = new Headers(request.headers);
  headers.delete('content-length');
  return originalFetch(request.url, {method: 'POST', headers, body, signal: request.signal, redirect: 'error'});
};
