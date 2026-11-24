// The front logic of static/ui/lib.js: addresses, this app's errors as the kit's codes, and what a call sends.
import assert from 'node:assert/strict'
import test from 'node:test'

import { apiError, fieldCode, interpolate, loginUrl, makeT, request, requestLine, safeNext, sessionGone } from '../../static/ui/lib.js'

test('a text takes its values once, and only as text', () => {
  assert.equal(interpolate('Copy {address}', { address: '{name}' }), 'Copy {name}')
  assert.equal(interpolate('{missing} stays', {}), '{missing} stays')
  const t = makeT({ 'a.b': 'Hello {who}' })
  assert.equal(t('a.b', { who: 'you' }), 'Hello you')
  assert.equal(t('a.none'), 'a.none')
  assert.equal(makeT({ 'a.b': 'x' }, { showKeys: true })('a.b'), 'a.b')
})

for (const [value, kept] of [
  ['/admin/links', true],
  ['/admin/qrcodes?qr=abc', true],
  ['/admin', false],
  ['/adminx', false],
  ['//evil.test/admin/', false],
  ['/admin/../login', false],
  ['/admin/%2e%2e/login', false],
  ['/admin/..\\login', false],
  ['https://evil.test/admin/', false],
  [null, false],
]) {
  test(`${JSON.stringify(value)} is ${kept ? '' : 'not '}an admin address`, () => {
    assert.equal(safeNext(value), kept)
  })
}

test('the login comes back to the page that sent the user there, never to the home page or elsewhere', () => {
  assert.equal(loginUrl('/admin/qrcodes?qr=abc', { expired: true }), '/login?expired=1&next=%2Fadmin%2Fqrcodes%3Fqr%3Dabc')
  assert.equal(loginUrl('/admin/links', { expired: true }), '/login?expired=1')
  assert.equal(loginUrl('/admin/links'), '/login')
  assert.equal(loginUrl('//evil.test/', { expired: true }), '/login?expired=1')
})

for (const [field, message, key] of [
  ['slug', 'required', 'redirect.slug_required'],
  ['slug', 'at most 255 characters', 'redirect.slug_too_long'],
  ['slug', "letters, digits, '.', '_', '-' in '/'-separated segments", 'redirect.slug_invalid'],
  ['slug', "no empty segment: no '/' at either end, no '//'", 'redirect.slug_empty_segment'],
  ['slug', "no '.' or '..' segment", 'redirect.slug_dot_segment'],
  ['slug', 'starts with a reserved section (Api, NanoURL, QRcodes)', 'redirect.slug_reserved'],
  ['name', 'required', 'redirect.name_required'],
  ['name', 'at most 100 characters', 'redirect.name_too_long'],
  ['name', 'holds control or invisible characters', 'redirect.name_invalid'],
  ['name', 'makes no usable path', 'redirect.name_unusable'],
  ['target', 'required', 'redirect.target_required'],
  ['target', 'at most 2048 characters', 'redirect.target_too_long'],
  ['target', 'at most 2048 characters once encoded', 'redirect.target_too_long'],
  ['target', 'must be an http or https URL', 'redirect.target_invalid'],
  ['target', 'invalid host', 'redirect.target_invalid'],
  ['expires_on', 'YYYY-MM-DD', 'redirect.expires_on_invalid'],
  ['expires_on', 'not a real date', 'redirect.expires_on_invalid'],
  ['design', 'color must be #rrggbb', 'redirect.design_color'],
  ['design', 'eye_color must be #rrggbb', 'redirect.design_color'],
  ['design', 'background must be #rrggbb', 'redirect.design_color'],
  ['design', 'logo is at most 256 KiB', 'redirect.design_logo_size'],
  ['design', 'logo is a PNG, JPEG, WebP or SVG data URI', 'redirect.design_logo'],
  ['design', 'colours need a contrast of 3:1 with the background to scan', 'redirect.design_contrast'],
  ['design', 'margin is a whole number from 0 to 10', 'redirect.value_invalid'],
  ['kind', 'link, nano or qrcode', 'redirect.value_invalid'],
  // The pages never send a status code (decision D20): an answer about one has no text of its own
  ['http_status', '301 or 302', 'redirect.value_invalid'],
  ['name', 42, 'redirect.value_invalid'],
  ['constructor', 'required', 'redirect.value_invalid'],
]) {
  test(`${field}: "${message}" reads as ${key}`, () => {
    assert.equal(fieldCode(field, message), key)
  })
}

test('an answer of this app becomes the kit failure, its words as codes', () => {
  assert.deepEqual(apiError('POST', '/api/links', 400, { error: 'invalid', fields: { name: 'required' } }), {
    method: 'POST',
    path: '/api/links',
    status: 400,
    code: 'invalid',
    params: {},
    fields: { name: 'redirect.name_required' },
  })
  assert.equal(apiError('GET', '/x', 404, { error: 'not_found' }).code, 'errors.not_found')
  assert.equal(apiError('GET', '/x', 409, { error: 'slug_taken' }).code, 'redirect.slug_taken')
  assert.equal(apiError('GET', '/x', 422, { error: 'design_unreadable' }).code, 'redirect.design_unreadable')
  assert.equal(apiError('GET', '/x', 500, null).code, null)
  assert.equal(apiError('GET', '/x', 500, { error: 5 }).code, null)
  assert.ok(sessionGone(apiError('GET', '/x', 401, { error: 'unauthorized' })))
  assert.ok(!sessionGone(apiError('GET', '/x', 403, { error: 'unauthorized' })))
})

function fakeFetch(status, body) {
  const calls = []
  const fetcher = async (address, options) => {
    calls.push({ address, options })
    if (status === 'throw') throw new TypeError('network')
    return {
      status,
      ok: status >= 200 && status < 300,
      json: async () => {
        if (body === undefined) throw new SyntaxError('no JSON')
        return body
      },
    }
  }
  return { calls, fetcher }
}

test('a read sends no token, and a change sends the session token with JSON', async () => {
  const read = fakeFetch(200, { links: [] })
  assert.deepEqual(await request('/api/links', { query: { kind: 'link', none: null }, fetcher: read.fetcher, token: () => 'tok' }), { links: [] })
  assert.equal(read.calls[0].address, '/api/links?kind=link')
  assert.equal(read.calls[0].options.method, 'GET')
  assert.equal(read.calls[0].options.headers['X-CSRF-Token'], undefined)
  assert.equal(read.calls[0].options.credentials, 'same-origin')

  for (const method of ['POST', 'PATCH', 'DELETE']) {
    const change = fakeFetch(204)
    const json = method === 'DELETE' ? undefined : { name: 'A' }
    assert.equal(await request('/api/links/x', { method, json, fetcher: change.fetcher, token: () => 'tok' }), null)
    const { options } = change.calls[0]
    assert.equal(options.method, method)
    assert.equal(options.headers['X-CSRF-Token'], 'tok')
    assert.equal(options.body, json === undefined ? undefined : '{"name":"A"}')
  }
})

test('no answer, a refusal and a lost session each say what they are', async () => {
  await assert.rejects(request('/api/links', { fetcher: fakeFetch('throw').fetcher }), (error) => error.status === 0)
  await assert.rejects(
    request('/api/links', { fetcher: fakeFetch(502, undefined).fetcher }),
    (error) => error.status === 502 && error.code === null,
  )
  let expired = 0
  await assert.rejects(
    request('/api/links', { fetcher: fakeFetch(401, { error: 'unauthorized' }).fetcher, onExpired: () => (expired += 1) }),
    (error) => sessionGone(error),
  )
  assert.equal(expired, 1)
  await assert.rejects(
    request('/api/links', { method: 'POST', json: {}, fetcher: fakeFetch(403, { error: 'csrf' }).fetcher, onExpired: () => (expired += 1) }),
    (error) => error.code === 'errors.csrf',
  )
  assert.equal(expired, 1)
})

function sequence(...answers) {
  const calls = []
  const fetcher = async (address, options) => {
    calls.push({ address, options })
    const [status, body] = answers.shift()
    return { status, ok: status >= 200 && status < 300, json: async () => body }
  }
  return { calls, fetcher }
}

test('a csrf refusal takes the session token afresh and sends the change once more', async () => {
  let token = 'old'
  const server = sequence([403, { error: 'csrf' }], [201, { id: 'a' }])
  const renewToken = async () => {
    token = 'new'
    return true
  }
  const answer = await request('/api/links', { json: { name: 'A' }, fetcher: server.fetcher, token: () => token, renewToken })
  assert.deepEqual(answer, { id: 'a' })
  assert.deepEqual(server.calls.map((call) => call.options.headers['X-CSRF-Token']), ['old', 'new'])
  assert.equal(server.calls[1].options.body, '{"name":"A"}')
})

test('a csrf refusal is sent again once at most, and only when a token came', async () => {
  const twice = sequence([403, { error: 'csrf' }], [403, { error: 'csrf' }], [201, {}])
  await assert.rejects(
    request('/api/links', { json: {}, fetcher: twice.fetcher, token: () => 't', renewToken: async () => true }),
    (error) => error.code === 'errors.csrf',
  )
  assert.equal(twice.calls.length, 2)
  for (const renewToken of [async () => false, async () => { throw new Error('no answer') }, undefined]) {
    const once = sequence([403, { error: 'csrf' }], [201, {}])
    await assert.rejects(
      request('/api/links', { json: {}, fetcher: once.fetcher, token: () => 't', renewToken }),
      (error) => error.code === 'errors.csrf',
    )
    assert.equal(once.calls.length, 1)
  }
  const other = sequence([403, { error: 'not_found' }], [201, {}])
  let asked = 0
  await assert.rejects(request('/api/links', { json: {}, fetcher: other.fetcher, token: () => 't', renewToken: async () => (asked += 1) > 0 }))
  assert.equal(asked, 0)
})

test('the error line says the call and its answer', () => {
  const t = (key) => (key === 'state.no_response' ? 'no response' : key)
  assert.equal(requestLine({ method: 'GET', path: '/api/links', status: 500 }, t), 'GET /api/links → 500')
  assert.equal(requestLine({ method: 'GET', path: '/api/links', status: 0 }, t), 'GET /api/links → no response')
  assert.equal(requestLine({}, t), null)
})
