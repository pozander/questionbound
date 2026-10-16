const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'feynman-budget-test-'));
const ledger = path.join(directory, 'budget.json');
process.env.FEYNMAN_BUDGET_LEDGER = ledger;
let sent = [];
globalThis.fetch = async (url, init) => {
  sent.push(JSON.parse(init.body));
  return new Response('{}');
};
require('../scripts/feynman_budget.cjs');
const request = body => fetch('https://api.openai.com/v1/responses', {
  method: 'POST', body: JSON.stringify(body), headers: {'Content-Type': 'application/json'}
});
(async () => {
  try {
    fs.writeFileSync(ledger, JSON.stringify({budget_usd: 0.50, reserved_usd: 0, requests: []}));
    await request({model: 'gpt-4.1', input: 'test', tools: [{type: 'web_search'}]});
    assert.equal(sent.length, 1);
    fs.writeFileSync(ledger, JSON.stringify({budget_usd: 2, reserved_usd: 0.1, requests: []}));
    process.env.FEYNMAN_MODEL = 'gpt-4.1-mini';
    process.env.FEYNMAN_MAX_OUTPUT_TOKENS = '2000';
    await request({model: 'gpt-4.1-mini', input: 'test'});
    assert.equal(sent.length, 2);
    assert.equal(sent[1].max_output_tokens, 2000);
    const updated = JSON.parse(fs.readFileSync(ledger, 'utf8'));
    const reservation = updated.requests[0];
    assert.equal(reservation.model, 'gpt-4.1-mini');
    assert.equal(reservation.reserved_usd, ((reservation.input_bytes + 4096) * 0.4 + 2000 * 1.6) / 1e6);
    assert.equal(updated.reserved_usd, 0.1 + reservation.reserved_usd);
    process.env.FEYNMAN_MAX_OUTPUT_TOKENS = 'NaN';
    await assert.rejects(request({model: 'gpt-4.1-mini'}), /invalid output cap/);
    await assert.rejects(fetch('https://example.com/v1/responses'), /unsupported provider/);
    delete process.env.FEYNMAN_MODEL;
    delete process.env.FEYNMAN_MAX_OUTPUT_TOKENS;
    sent = sent.slice(0, 1);
    assert.equal(sent[0].tools, undefined);
    assert.equal(sent[0].max_output_tokens, 5000);
    assert.equal(sent[0].service_tier, 'default');
    await assert.rejects(request({model: 'gpt-4.1-mini', input: 'test'}), /unsupported model/);
    await assert.rejects(request({model: 'gpt-4.1', previous_response_id: 'old'}), /server-side context/);
    fs.writeFileSync(ledger, JSON.stringify({budget_usd: 0.01, reserved_usd: 0, requests: []}));
    await assert.rejects(request({model: 'gpt-4.1', input: 'test'}), /remaining reserved budget/);
    assert.equal(sent.length, 1);
    console.log('Budget guard checks passed; no network requests made.');
  } finally {
    fs.unlinkSync(ledger);
    fs.rmdirSync(directory);
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
