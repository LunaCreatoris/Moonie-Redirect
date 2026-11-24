// What the Settings page decides without a document, and how it talks to a fake of the settings API (the README's
// settings API): each action's method and path, and how each refusal reaches the field it is about.
import assert from 'node:assert/strict'
import test from 'node:test'

import { callAction } from '../../static/ui/shell.js'
import { makeT, request } from '../../static/ui/lib.js'
import {
  PAGE,
  TABS,
  cloudflareReadable,
  credentialView,
  deliveryView,
  eventRows,
  isSuccess,
  keyCheck,
  keyRows,
  limitValue,
  originView,
  passwordCheck,
  placeCode,
  readable,
  scopesIn,
  statusText,
  suggestions,
  tabAddress,
  tabFrom,
  toggleScope,
  tokenChecked,
  webhookBody,
} from '../../static/ui/settings-logic.js'
import strings from '../../static/ui/en.json' with { type: 'json' }

const t = makeT(strings)

// --- A fake of the settings API ---------------------------------------------------------------------------------------

// The instance's known_scopes, in its order: the wildcards beside the actions they cover
const KNOWN = [
  '*',
  'redirect:*',
  'redirect:links.read',
  'redirect:links.write',
  'redirect:nanourls.read',
  'redirect:nanourls.write',
  'redirect:qrcodes.read',
  'redirect:qrcodes.write',
  'cloudflare:*',
  'cloudflare:read',
  'cloudflare:write',
  'cloudflare:setup',
]
const AVAILABLE = [
  { name: 'redirect.link.created', label: 'Link created' },
  { name: 'redirect.link.updated', label: 'Link updated' },
  { name: 'redirect.link.deleted', label: 'Link deleted' },
]
const PASSWORD = 'correct horse battery'

// The answers of the settings API, from a state in memory. Every call is recorded with its method, path, header and body.
function fakeServer() {
  const state = {
    password: 'file',
    active: 2,
    keys: [{ id: 'file', name: 'Token file', prefix: null, scopes: ['*'], created_at: null, last_used_at: null, origin: 'file' }],
    webhook: null,
    token: { origin: 'missing', state: null, missing: [], unverified: [], checked_at: null },
    limit: { value: 10000, origin: 'default' },
    testing: false,
    braked: false,
  }
  const calls = []
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  const none = () => new Response(null, { status: 204 })
  const webhookAnswer = () => ({
    configured: state.webhook !== null,
    url: state.webhook?.url ?? null,
    events: state.webhook?.events ?? [],
    available: AVAILABLE,
    secret: state.webhook?.secret ? 'stored' : 'missing',
    cleartext: Boolean(state.webhook?.url?.startsWith('http:')),
    disabled_reason: null,
    last_delivery: null,
    waiting: 0,
    timeout_seconds: 30,
  })
  const cloudflareAnswer = () => ({ token: { ...state.token }, item_limit: { ...state.limit } })
  const routes = {
    'GET /api/settings/security': () =>
      json(200, { password: { origin: state.password }, sessions: { active: state.active, hours: 12 }, login_brake_seconds: 1 }),
    'POST /api/settings/password': (body) => {
      if (state.braked) return json(429, { error: 'too_many_attempts' })
      if (body.password !== PASSWORD) return json(400, { error: 'login_failed', fields: { password: 'wrong password' } })
      if ([...body.new_password].length < 12) return json(400, { error: 'invalid', fields: { new_password: 'too short' } })
      state.password = 'stored'
      state.active = 1
      return none()
    },
    'POST /api/settings/sessions/end': () => {
      state.active = 0
      return none()
    },
    'GET /api/settings/keys': () => json(200, { keys: state.keys, known_scopes: KNOWN }),
    'POST /api/settings/keys': (body) => {
      if (state.braked) return json(429, { error: 'too_many_attempts' })
      if (body.password !== PASSWORD) return json(400, { error: 'login_failed', fields: { password: 'wrong password' } })
      const unknown = body.scopes.filter((scope) => !KNOWN.includes(scope))
      if (unknown.length) return json(400, { error: 'invalid', fields: { scopes: `unknown scope ${unknown[0]}` } })
      const key = { id: `k${state.keys.length}`, name: body.name, prefix: 'mrk_AbCd', scopes: body.scopes }
      state.keys.push({ ...key, created_at: '2026-11-24T10:00:00Z', last_used_at: null, origin: 'stored' })
      return json(201, { ...key, secret: 'mrk_AbCdsecret' })
    },
    'DELETE /api/settings/keys/:id': (body, id) => {
      const index = state.keys.findIndex((key) => key.id === id && key.origin === 'stored')
      if (index < 0) return json(404, { error: 'not_found' })
      state.keys.splice(index, 1)
      return none()
    },
    'GET /api/settings/webhook': () => json(200, webhookAnswer()),
    'PUT /api/settings/webhook': (body) => {
      if (body.url.startsWith('http://127.')) return json(400, { error: 'invalid', fields: { url: 'url_closed' } })
      if (!state.webhook?.secret && !body.secret) return json(400, { error: 'invalid', fields: { secret: 'secret_required' } })
      if (body.secret !== undefined && body.secret.length < 16) return json(400, { error: 'invalid', fields: { secret: 'too short' } })
      state.webhook = { url: body.url, events: body.events, secret: body.secret ?? state.webhook.secret }
      return json(200, webhookAnswer())
    },
    'DELETE /api/settings/webhook': () => {
      state.webhook = null
      return none()
    },
    'POST /api/settings/webhook/test': () => {
      if (!state.webhook) return json(409, { error: 'not_configured' })
      if (state.testing) return json(429, { error: 'busy' })
      return json(200, { status: 200, duration_ms: 42, error: null, reply_is_json: true })
    },
    'GET /api/settings/cloudflare': () => json(200, cloudflareAnswer()),
    'PUT /api/settings/cloudflare/token': (body) => {
      // The instance's own words for a token that holds a character no header can carry
      if (!/^[A-Za-z0-9_-]{40}$/.test(body.token)) return json(400, { error: 'invalid', fields: { token: 'a printable ASCII token' } })
      if (body.token.startsWith('x')) return json(400, { error: 'token_invalid' })
      state.token = { origin: 'stored', state: 'ok', missing: body.token.startsWith('m') ? ['DNS Write'] : [], unverified: [], checked_at: 'now' }
      return json(200, cloudflareAnswer())
    },
    'DELETE /api/settings/cloudflare/token': () => {
      state.token = { origin: 'missing', state: null, missing: [], unverified: [], checked_at: null }
      return json(200, cloudflareAnswer())
    },
    'PUT /api/settings/cloudflare/item-limit': (body) => {
      if (body.value !== null && !(Number.isInteger(body.value) && body.value >= 1)) return json(400, { error: 'invalid', fields: { value: 'whole number' } })
      state.limit = body.value === null ? { value: 10000, origin: 'default' } : { value: body.value, origin: 'stored' }
      return json(200, cloudflareAnswer())
    },
  }
  async function fetcher(address, init) {
    const url = new URL(address, 'http://redirect.test')
    const body = init.body === undefined ? undefined : JSON.parse(init.body)
    calls.push({ method: init.method, path: url.pathname, csrf: init.headers['X-CSRF-Token'], body })
    const keyPath = url.pathname.match(/^\/api\/settings\/keys\/([^/]+)$/)
    const route = keyPath ? `${init.method} /api/settings/keys/:id` : `${init.method} ${url.pathname}`
    if (!Object.hasOwn(routes, route)) return json(404, { error: 'not_found' })
    return routes[route](body, keyPath ? decodeURIComponent(keyPath[1]) : undefined)
  }
  // What a page's ctx.api does in the browser, with the session's token
  const api = (action, options) => callAction((path, sent) => request(path, { ...sent, fetcher, token: () => 'csrf-1' }), action, options)
  return { state, calls, api }
}

// --- Tabs -------------------------------------------------------------------------------------------------------------

test('the tabs are Security, Webhook & API and Cloudflare, Security first', () => {
  assert.deepEqual(
    TABS.map((tab) => [tab.id, t(tab.label)]),
    [
      ['security', 'Security'],
      ['webhook', 'Webhook & API'],
      ['cloudflare', 'Cloudflare'],
    ],
  )
})

test('the tab comes from the address, and an unknown one reads as Security', () => {
  const tab = (search) => tabFrom(new URLSearchParams(search))
  assert.equal(tab(''), 'security')
  assert.equal(tab('?tab=webhook'), 'webhook')
  assert.equal(tab('?tab=cloudflare&keys=1'), 'cloudflare')
  for (const search of ['?tab=', '?tab=Webhook', '?tab=__proto__', '?tab=constructor', '?tab=keys']) assert.equal(tab(search), 'security', search)
  assert.equal(tabFrom(null), 'security')
})

test('a tab address keeps the other flags and drops the webhook form flag', () => {
  assert.equal(PAGE, '/admin/settings')
  assert.equal(tabAddress('', 'webhook'), '/admin/settings?tab=webhook')
  assert.equal(tabAddress('?tab=webhook&configure=1&keys=1', 'cloudflare'), '/admin/settings?tab=cloudflare&keys=1')
  assert.equal(tabAddress('?tab=webhook', 'webhook', { configure: true }), '/admin/settings?tab=webhook&configure=1')
})

// --- Origins and credentials ------------------------------------------------------------------------------------------

test('each origin has its chip, and an unknown one says Not set', () => {
  const said = (origin) => [t(originView(origin).text), originView(origin).level]
  assert.deepEqual(said('stored'), ['Set here', 'success'])
  assert.deepEqual(said('file'), ['From file', 'info'])
  assert.deepEqual(said('env'), ['From environment', 'info'])
  assert.deepEqual(said('default'), ['Default', undefined])
  assert.deepEqual(said('missing'), ['Not set', undefined])
  assert.deepEqual(said('unreadable'), ['Cannot be read', 'warning'])
  assert.deepEqual(said('__proto__'), ['Not set', undefined])
  assert.deepEqual(said(undefined), ['Not set', undefined])
})

test('a credential set here or unreadable can be replaced and cleared, one from a file only replaced, none has the form', () => {
  assert.deepEqual(
    ['stored', 'unreadable', 'file', 'missing', 'other'].map((origin) => [credentialView(origin).control, credentialView(origin).clear]),
    [
      ['replace', true],
      ['replace', true],
      ['replace', false],
      ['form', false],
      ['form', false],
    ],
  )
  assert.equal(tokenChecked('stored'), true)
  assert.equal(tokenChecked('file'), true)
  assert.equal(tokenChecked('missing'), false)
  assert.equal(tokenChecked('unreadable'), false)
})

// --- Checks before a call ---------------------------------------------------------------------------------------------

test('a password change needs every field, two equal new ones, of 12 to 1024 characters', () => {
  assert.deepEqual(passwordCheck({ password: '', new_password: '', new_password_confirm: '' }), {
    password: 'settings.field_required',
    new_password: 'settings.field_required',
    new_password_confirm: 'settings.field_required',
  })
  assert.deepEqual(passwordCheck({ password: 'x', new_password: 'short', new_password_confirm: 'short' }), { new_password: 'settings.password_length' })
  assert.deepEqual(passwordCheck({ password: 'x', new_password: 'a'.repeat(1025), new_password_confirm: 'a'.repeat(1025) }), {
    new_password: 'settings.password_length',
  })
  assert.deepEqual(passwordCheck({ password: 'x', new_password: 'long enough here', new_password_confirm: 'long enough herE' }), {
    new_password_confirm: 'settings.password_mismatch',
  })
  assert.equal(passwordCheck({ password: 'x', new_password: 'long enough here', new_password_confirm: 'long enough here' }), null)
  // Characters, not UTF-16 units: 12 emoji are 12 characters
  const emoji = '🌙'.repeat(12)
  assert.equal(passwordCheck({ password: 'x', new_password: emoji, new_password_confirm: emoji }), null)
  assert.deepEqual(passwordCheck({ password: 'x', new_password: '🌙'.repeat(11), new_password_confirm: '🌙'.repeat(11) }), {
    new_password: 'settings.password_length',
  })
})

test('a new key needs a name, a scope and the password', () => {
  assert.deepEqual(keyCheck({ name: '  ', scopes: [], password: '' }), {
    name: 'settings.field_required',
    scopes: 'settings.field_required',
    password: 'settings.field_required',
  })
  assert.equal(keyCheck({ name: 'n8n', scopes: ['*'], password: 'x' }), null)
})

test('the item limit is empty for the default, or a whole number of 1 or more', () => {
  assert.deepEqual(limitValue(''), { value: null })
  assert.deepEqual(limitValue('   '), { value: null })
  assert.deepEqual(limitValue(' 25000 '), { value: 25000 })
  assert.deepEqual(limitValue('1'), { value: 1 })
  for (const typed of ['0', '-1', '1.5', '1e3', '10,000', 'ten', '0x10', '99999999999999999999', '１２']) {
    assert.deepEqual(limitValue(typed), { error: 'settings.cf_limit_invalid' }, typed)
  }
})

// --- Webhook ----------------------------------------------------------------------------------------------------------

test('a 2xx is a success, anything else or nothing is not', () => {
  assert.deepEqual([200, 204, 299].map(isSuccess), [true, true, true])
  assert.deepEqual([199, 300, 410, 500, null, undefined, '200', 200.5].map(isSuccess), [false, false, false, false, false, false, false, false])
  assert.equal(statusText(410, t), 'HTTP 410')
  assert.equal(statusText(null, t), 'no response')
  assert.equal(statusText(undefined, t), 'no response')
})

test('the events offered come first in their order, then what is ticked but no longer offered', () => {
  const rows = eventRows(AVAILABLE, ['redirect.link.deleted', 'old.event', 'redirect.link.created', 'old.event', 'a.event'])
  assert.deepEqual(
    rows.map((row) => [row.name, row.key ? t(row.key) : row.label, row.checked, row.offered]),
    [
      ['redirect.link.created', 'Link created', true, true],
      ['redirect.link.updated', 'Link changed', false, true],
      ['redirect.link.deleted', 'Link deleted', true, true],
      ['a.event', 'No longer sent, still ticked', true, false],
      ['old.event', 'No longer sent, still ticked', true, false],
    ],
  )
})

test('an event this page has no text for shows the label the instance gave', () => {
  const [row] = eventRows([{ name: 'redirect.other', label: 'Other thing' }], [])
  assert.deepEqual([row.key, row.label], [null, 'Other thing'])
  assert.deepEqual(eventRows(null, null), [])
  assert.deepEqual(eventRows([{ label: 'no name' }, null], [7]), [])
})

test('a save sends the secret only when one was typed', () => {
  const events = ['redirect.link.created']
  assert.deepEqual(webhookBody({ url: ' http://n8n:5678/webhook/x ', events, secret: '' }), { url: 'http://n8n:5678/webhook/x', events })
  assert.deepEqual(webhookBody({ url: 'https://n8n.example/h', events, secret: ' 16 characters!! ' }), {
    url: 'https://n8n.example/h',
    events,
    secret: ' 16 characters!! ',
  })
})

test('the last delivery reads in 7.0.1 words and as an outbox row', () => {
  assert.equal(deliveryView(null), null)
  assert.equal(deliveryView({ status: 200 }), null)
  assert.deepEqual(deliveryView({ event: 'redirect.link.created', status: 200, at: '2026-11-24T10:00:00Z', event_id: 'e1', error: null }), {
    event: 'redirect.link.created',
    status: 200,
    at: '2026-11-24T10:00:00Z',
    id: 'e1',
    error: null,
  })
  assert.deepEqual(
    deliveryView({ id: 'e2', event: 'redirect.link.deleted', status: 'failed', last_status: 500, last_error: 'HTTP 500', finished_at: 'then' }),
    { event: 'redirect.link.deleted', status: 500, at: 'then', id: 'e2', error: 'HTTP 500' },
  )
})

// --- API keys ---------------------------------------------------------------------------------------------------------

test('scopes are split on spaces and commas', () => {
  assert.deepEqual(scopesIn(' redirect:*, cloudflare:read\tcloudflare:write,,'), ['redirect:*', 'cloudflare:read', 'cloudflare:write'])
  assert.deepEqual(scopesIn(''), [])
  assert.deepEqual(scopesIn(undefined), [])
})

test('the scope chips are the known scopes in the instance order, the wildcards it leaves out first', () => {
  assert.deepEqual(suggestions(KNOWN), KNOWN)
  const actions = KNOWN.filter((scope) => !scope.endsWith('*'))
  assert.deepEqual(suggestions(actions), ['*', 'redirect:*', 'cloudflare:*', ...actions])
  assert.deepEqual(suggestions(['redirect:*', 'redirect:links.read']), ['*', 'redirect:*', 'redirect:links.read'])
  assert.deepEqual(suggestions(undefined), ['*'])
  assert.deepEqual(suggestions(['*', 7]), ['*'])
  assert.deepEqual(suggestions(['*', 'redirect:*', 'redirect:links.read', 'odd']), ['*', 'redirect:*', 'redirect:links.read', 'odd'])
})

test('a scope chip adds its scope, and pressed again removes it', () => {
  assert.equal(toggleScope('', 'redirect:*'), 'redirect:*')
  assert.equal(toggleScope('redirect:*', 'cloudflare:read'), 'redirect:*, cloudflare:read')
  assert.equal(toggleScope('redirect:*,cloudflare:read', 'redirect:*'), 'cloudflare:read')
})

test('the token file is a fixed first row, then the keys made here in their order', () => {
  const rows = keyRows([
    { id: 'b', name: 'n8n', origin: 'stored' },
    { id: 'file', name: 'token file', origin: 'file' },
    { id: 'a', name: 'backup', origin: 'stored' },
    { name: 'no id' },
    null,
  ])
  assert.deepEqual(
    rows.map((row) => [row.id, row.fixed]),
    [
      ['file', true],
      ['b', false],
      ['a', false],
    ],
  )
  assert.deepEqual(keyRows(undefined), [])
})

// --- Answers ----------------------------------------------------------------------------------------------------------

test('a refusal about one field goes under it, with the page own text when it has one', () => {
  const error = { status: 400, code: 'cloudflare.token_invalid', params: {}, fields: {} }
  assert.deepEqual(placeCode(error, { 'cloudflare.token_invalid': { field: 'token', text: 'settings.cf_token_refused' } }).fields, {
    token: 'settings.cf_token_refused',
  })
  assert.deepEqual(placeCode({ ...error, code: 'errors.login_failed' }, { 'errors.login_failed': { field: 'password' } }).fields, {
    password: 'errors.login_failed',
  })
  assert.equal(placeCode(error, {}), error)
  assert.equal(placeCode({ ...error, code: 'constructor' }, {}).code, 'constructor')
  assert.equal(placeCode(null, {}), null)
})

test('an answer the page cannot draw is a failed load', () => {
  assert.equal(readable('security', { password: { origin: 'file' }, sessions: { active: 1, hours: 12 } }), true)
  assert.equal(readable('security', null), false)
  assert.equal(readable('security', '<html>'), false)
  assert.equal(readable('webhook', { webhook: { available: [], events: [] }, keys: { keys: [] } }), true)
  assert.equal(readable('webhook', { webhook: { available: [], events: [] }, keys: null }), false)
  assert.equal(readable('webhook', { webhook: null, keys: { keys: [] } }), false)
  const domains = { state: { token: {}, counts: {}, accounts: [], hosts: [] }, hosts: [] }
  assert.equal(readable('cloudflare', { settings: { token: {}, item_limit: {} }, domains }), true)
  assert.equal(readable('cloudflare', { settings: { token: {}, item_limit: {} }, domains: null }), false)
  assert.equal(readable('cloudflare', { settings: { token: {}, item_limit: {} }, domains: { state: '<html>', hosts: undefined } }), false)
  assert.equal(readable('cloudflare', { settings: { token: {}, item_limit: {} }, domains: { state: domains.state, hosts: null } }), false)
  assert.equal(readable('cloudflare', { settings: null, domains }), false)
  assert.equal(readable('cloudflare', {}), false)
  assert.equal(cloudflareReadable({ token: {}, item_limit: {} }), true)
  assert.equal(cloudflareReadable({ token: {} }), false)
  assert.equal(readable('other', {}), false)
})

// --- Against the fake API ---------------------------------------------------------------------------------------------

test('every settings action reaches its route with its method, and changes carry the session token', async () => {
  const server = fakeServer()
  await server.api('admin.security')
  await server.api('admin.password', { json: { password: PASSWORD, new_password: 'a new long password' } })
  await server.api('admin.sessions_end', { json: {} })
  await server.api('admin.keys')
  await server.api('admin.key_create', { json: { name: 'n8n', scopes: ['*'], password: PASSWORD } })
  await server.api('admin.key_revoke', { id: 'k1' })
  await server.api('admin.webhook')
  await server.api('admin.webhook_save', { json: { url: 'http://n8n:5678/h', events: [], secret: 'a secret of 16 chars' } })
  await server.api('admin.webhook_test', { json: {} })
  await server.api('admin.webhook_delete')
  await server.api('admin.cloudflare')
  await server.api('admin.cf_token_set', { json: { token: 'a'.repeat(40) } })
  await server.api('admin.cf_token_clear')
  await server.api('admin.cf_item_limit', { json: { value: 20000 } })
  assert.deepEqual(
    server.calls.map((call) => `${call.method} ${call.path}`),
    [
      'GET /api/settings/security',
      'POST /api/settings/password',
      'POST /api/settings/sessions/end',
      'GET /api/settings/keys',
      'POST /api/settings/keys',
      'DELETE /api/settings/keys/k1',
      'GET /api/settings/webhook',
      'PUT /api/settings/webhook',
      'POST /api/settings/webhook/test',
      'DELETE /api/settings/webhook',
      'GET /api/settings/cloudflare',
      'PUT /api/settings/cloudflare/token',
      'DELETE /api/settings/cloudflare/token',
      'PUT /api/settings/cloudflare/item-limit',
    ],
  )
  for (const call of server.calls) assert.equal(call.csrf, call.method === 'GET' ? undefined : 'csrf-1', `${call.method} ${call.path}`)
})

test('a key id is one segment of the path, whatever it holds', async () => {
  const server = fakeServer()
  await assert.rejects(server.api('admin.key_revoke', { id: '../webhook' }), { status: 404 })
  assert.equal(server.calls[0].path, '/api/settings/keys/..%2Fwebhook')
  assert.notEqual(server.state.webhook, undefined)
})

test('a wrong current password is said under the current password field', async () => {
  const server = fakeServer()
  const error = await server.api('admin.password', { json: { password: 'nope', new_password: 'a new long password' } }).catch((failure) => failure)
  assert.equal(error.status, 400)
  assert.equal(error.code, 'errors.login_failed')
  assert.deepEqual(placeCode(error, { 'errors.login_failed': { field: 'password' } }).fields, { password: 'errors.login_failed' })
  assert.equal(t('errors.login_failed'), 'Wrong password. Try again.')
  assert.equal(server.state.password, 'file')
})

test('a new password the instance refuses is said under the new password', async () => {
  const server = fakeServer()
  const error = await server.api('admin.password', { json: { password: PASSWORD, new_password: 'short' } }).catch((failure) => failure)
  assert.deepEqual(error.fields, { new_password: 'settings.password_length' })
})

test('a password change makes it set here; the security answer says it', async () => {
  const server = fakeServer()
  assert.equal((await server.api('admin.security')).password.origin, 'file')
  assert.equal(await server.api('admin.password', { json: { password: PASSWORD, new_password: 'a new long password' } }), null)
  const after = await server.api('admin.security')
  assert.deepEqual([after.password.origin, after.sessions.active, after.login_brake_seconds], ['stored', 1, 1])
  assert.equal(readable('security', after), true)
})

test('a new key shows its secret once, then lists with the token file first', async () => {
  const server = fakeServer()
  const made = await server.api('admin.key_create', { json: { name: 'n8n', scopes: ['redirect:*', 'cloudflare:read'], password: PASSWORD } })
  assert.equal(made.secret, 'mrk_AbCdsecret')
  const { keys, known_scopes: known } = await server.api('admin.keys')
  assert.deepEqual(
    keyRows(keys).map((key) => [key.name, key.fixed, Object.hasOwn(key, 'secret')]),
    [
      ['Token file', true, false],
      ['n8n', false, false],
    ],
  )
  assert.deepEqual(suggestions(known), KNOWN)
})

test('a braked password check is said under the password, in the dialog of a password change or of a new key', async () => {
  const server = fakeServer()
  server.state.braked = true
  const places = { 'errors.login_failed': { field: 'password' }, 'errors.too_many_attempts': { field: 'password' } }
  for (const [action, json] of [
    ['admin.password', { password: PASSWORD, new_password: 'a new long password' }],
    ['admin.key_create', { name: 'n8n', scopes: ['*'], password: PASSWORD }],
  ]) {
    const error = await server.api(action, { json }).catch((failure) => failure)
    assert.deepEqual([error.status, error.code], [429, 'errors.too_many_attempts'], action)
    assert.deepEqual(placeCode(error, places).fields, { password: 'errors.too_many_attempts' }, action)
  }
  assert.equal(t('errors.too_many_attempts'), 'Too many attempts. Try again in 1 s.')
})

test('a key without the scope is told so, in words', async () => {
  const error = await request('/api/links', {
    fetcher: async () => new Response(JSON.stringify({ error: 'scope_denied' }), { status: 403, headers: { 'Content-Type': 'application/json' } }),
  }).catch((failure) => failure)
  assert.deepEqual([error.status, error.code], [403, 'errors.scope_denied'])
  assert.notEqual(t(error.code), error.code)
})

test('a new key with a wrong password or an unknown scope is refused under that field', async () => {
  const server = fakeServer()
  const wrong = await server.api('admin.key_create', { json: { name: 'n8n', scopes: ['*'], password: 'nope' } }).catch((failure) => failure)
  assert.deepEqual(wrong.fields, { password: 'errors.login_failed' })
  const scope = await server.api('admin.key_create', { json: { name: 'n8n', scopes: ['redirect:links'], password: PASSWORD } }).catch((failure) => failure)
  assert.deepEqual(scope.fields, { scopes: 'keys.field_scopes_invalid' })
  assert.equal(t(scope.fields.scopes), 'Use only the known scopes.')
})

test('revoking a key that is already gone is a 404, which the page takes as done', async () => {
  const server = fakeServer()
  const error = await server.api('admin.key_revoke', { id: 'k9' }).catch((failure) => failure)
  assert.equal(error.status, 404)
})

test('the first webhook save needs a secret, a closed address is said under the URL, then a save keeps the secret', async () => {
  const server = fakeServer()
  const empty = await server.api('admin.webhook')
  assert.deepEqual([empty.configured, empty.secret, readable('webhook', { webhook: empty, keys: { keys: [] } })], [false, 'missing', true])
  const events = ['redirect.link.created']
  const noSecret = await server.api('admin.webhook_save', { json: webhookBody({ url: 'http://n8n:5678/h', events, secret: '' }) }).catch((failure) => failure)
  assert.deepEqual(noSecret.fields, { secret: 'webhook.field_secret_required' })
  const closed = await server.api('admin.webhook_save', { json: webhookBody({ url: 'http://127.0.0.1/h', events, secret: 'x'.repeat(16) }) }).catch((failure) => failure)
  assert.deepEqual(closed.fields, { url: 'webhook.field_url_closed' })
  const short = await server.api('admin.webhook_save', { json: webhookBody({ url: 'http://n8n:5678/h', events, secret: 'short' }) }).catch((failure) => failure)
  assert.deepEqual(short.fields, { secret: 'webhook.field_secret' })
  const saved = await server.api('admin.webhook_save', { json: webhookBody({ url: 'http://n8n:5678/h', events, secret: 'x'.repeat(16) }) })
  assert.deepEqual([saved.configured, saved.secret, saved.cleartext, saved.events], [true, 'stored', true, events])
  const again = await server.api('admin.webhook_save', { json: webhookBody({ url: 'https://n8n.example/h', events: [], secret: '' }) })
  assert.deepEqual([again.url, again.secret, again.cleartext], ['https://n8n.example/h', 'stored', false])
  assert.equal(Object.hasOwn(server.calls.at(-1).body, 'secret'), false)
})

test('the webhook test answers its result, or why it could not run', async () => {
  const server = fakeServer()
  const off = await server.api('admin.webhook_test', { json: {} }).catch((failure) => failure)
  assert.deepEqual([off.status, t(off.code)], [409, 'Save the webhook before testing it.'])
  await server.api('admin.webhook_save', { json: { url: 'http://n8n:5678/h', events: [], secret: 'x'.repeat(16) } })
  const result = await server.api('admin.webhook_test', { json: {} })
  assert.deepEqual([isSuccess(result.status), result.duration_ms, result.reply_is_json], [true, 42, true])
  server.state.testing = true
  const busy = await server.api('admin.webhook_test', { json: {} }).catch((failure) => failure)
  assert.equal(busy.status, 429)
  await server.api('admin.webhook_delete')
  assert.equal((await server.api('admin.webhook')).configured, false)
})

test('a Cloudflare token is checked by the instance; a refused one is said under the token', async () => {
  const server = fakeServer()
  const before = await server.api('admin.cloudflare')
  assert.deepEqual([credentialView(before.token.origin).control, before.item_limit.origin], ['form', 'default'])
  const format = await server.api('admin.cf_token_set', { json: { token: 'not a token' } }).catch((failure) => failure)
  assert.deepEqual(format.fields, { token: 'settings.cf_token_invalid' })
  const refused = await server.api('admin.cf_token_set', { json: { token: 'x'.repeat(40) } }).catch((failure) => failure)
  assert.equal(refused.code, 'cloudflare.token_invalid')
  const placed = placeCode(refused, { 'cloudflare.token_invalid': { field: 'token', text: 'settings.cf_token_refused' } })
  assert.equal(t(placed.fields.token), 'Cloudflare does not accept this token. Nothing was stored.')
  const missing = await server.api('admin.cf_token_set', { json: { token: 'm'.repeat(40) } })
  assert.deepEqual([missing.token.origin, missing.token.missing, cloudflareReadable(missing)], ['stored', ['DNS Write'], true])
  const cleared = await server.api('admin.cf_token_clear')
  assert.equal(cleared.token.origin, 'missing')
})

test('the item limit is set, refused when it is no whole number, and emptied back to the default', async () => {
  const server = fakeServer()
  const set = await server.api('admin.cf_item_limit', { json: { value: limitValue('25000').value } })
  assert.deepEqual(set.item_limit, { value: 25000, origin: 'stored' })
  const bad = await server.api('admin.cf_item_limit', { json: { value: 0 } }).catch((failure) => failure)
  assert.deepEqual(bad.fields, { value: 'settings.cf_limit_invalid' })
  const back = await server.api('admin.cf_item_limit', { json: { value: limitValue('').value } })
  assert.deepEqual(back.item_limit, { value: 10000, origin: 'default' })
  assert.deepEqual(server.calls.at(-1).body, { value: null })
})

test('every text the settings fields can be refused with exists', () => {
  for (const key of [
    'settings.field_required',
    'settings.password_length',
    'settings.password_mismatch',
    'settings.cf_limit_invalid',
    'settings.cf_token_invalid',
    'settings.cf_token_refused',
    'webhook.field_url',
    'webhook.field_url_closed',
    'webhook.field_secret',
    'webhook.field_secret_required',
    'webhook.field_events',
    'webhook.test_busy',
    'webhook.test_not_configured',
    'keys.field_scopes_invalid',
    'errors.login_failed',
  ]) {
    assert.notEqual(t(key), key, key)
  }
})
