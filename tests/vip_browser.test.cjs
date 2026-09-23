// Isolated DOM/network regression harness. No production access or credentials.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../src/jabazi/static/vip.js'), 'utf8');

async function setup() {
  const at = Date.parse('2026-09-23T12:00:00Z');
  const state = {elapsed: 0, fail: false, calls: [], timer: null};
  class Element {
    constructor() { this.children = []; this.value = ''; this.hidden = false; this.textContent = ''; }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = [...nodes]; }
    addEventListener() {}
    setAttribute() {}
  }
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  get('sort').value = 'start';
  const row = {event_id: 'test', event: 'TEST Away @ TEST Home', selection: 'TEST Home ML',
    starts_at: new Date(at + 3600000).toISOString(), valid_until: new Date(at + 60000).toISOString(),
    model_probability: .6, market_probability: .5, edge: .1, odds: '+100', book: 'TEST',
    model_version: 'SYNTHETIC_TEST_ONLY', price_at: new Date(at).toISOString()};
  const payload = {rows: [row], games: 1, state: 'RESEARCH', markets: ['h2h'],
    image_pages: [1, 1, 1], server_time: new Date(at).toISOString(),
    session_expires_at: new Date(at + 900000).toISOString(), completed_at: new Date(at).toISOString()};
  const document = {getElementById: get, createElement: () => new Element(),
    querySelectorAll: () => [], addEventListener() {}, head: new Element(), hidden: false};
  class TestDate extends Date { static now() { return at + state.elapsed; } }
  const context = vm.createContext({document, Date: TestDate, URLSearchParams, console,
    performance: {now: () => state.elapsed}, location: {hash: ''}, history: {replaceState() {}},
    setInterval: fn => { state.timer = fn; },
    fetch: async url => {
      state.calls.push(url);
      if (state.fail) throw Error('TEST network failure');
      return {ok: true, json: async () => url === '/vip/info' ? {} : structuredClone(payload)};
    }});
  await vm.runInContext(script, context);
  return {state, context, get};
}

test('old rows expire without initiating a scan or another network request', async () => {
  const {state, get} = await setup();
  assert.equal(get('rows').children.length, 1);
  const before = state.calls.length;
  state.elapsed = 61000;
  state.timer();
  assert.equal(get('rows').children.length, 0);
  assert.equal(get('downloads').children.length, 0);
  assert.equal(state.calls.length, before);
  assert.ok(state.calls.every(url => !url.includes('/scans/') && !url.includes('/mcp')));
});

test('a failed refresh clears the prior card instead of displaying it as current', async () => {
  const {state, context, get} = await setup();
  state.fail = true;
  await vm.runInContext('load()', context);
  assert.equal(get('rows').children.length, 0);
  assert.equal(get('downloads').children.length, 0);
  assert.equal(get('refresh').disabled, false);
  assert.match(get('message').textContent, /network failure/);
});

test('session expiry hides research and clears rows locally', async () => {
  const {state, get} = await setup();
  state.elapsed = 901000;
  state.timer();
  assert.equal(get('workspace').hidden, true);
  assert.equal(get('login').hidden, false);
  assert.equal(get('rows').children.length, 0);
});

test('latest request wins when responses return out of order', async () => {
  const {context, get} = await setup();
  let resolveOld;
  context.fetch = () => new Promise(resolve => { resolveOld = resolve; });
  const pending = vm.runInContext('load()', context);
  vm.runInContext('login("Signed out.")', context);
  resolveOld({ok: true, json: async () => ({rows: [{event: 'OLD'}]})});
  await pending;
  assert.equal(get('workspace').hidden, true);
  assert.equal(get('rows').children.length, 0);
});
