// What the shell decides without a document: its menu, its routes, its status, and where a taken path is said.
import assert from 'node:assert/strict'
import test from 'node:test'

import { FOOT, NAV, findRoute, movedTo, placeTaken, statusText } from '../../static/ui/shell.js'
import { GLYPH } from '../../static/ui/icons.js'
import strings from '../../static/ui/en.json' with { type: 'json' }
import { makeT } from '../../static/ui/lib.js'

const t = makeT(strings)

test('the menu holds the three pages of 7.0.1 under Redirect, and no other section', () => {
  assert.deepEqual(
    NAV.flatMap((section) => section.items.map((item) => [item.path, t(item.label)])),
    [
      ['/admin/links', 'Links'],
      ['/admin/nanourls', 'NanoURLs'],
      ['/admin/qrcodes', 'QR codes'],
    ],
  )
  assert.deepEqual(
    NAV.map((section) => t(section.label)),
    ['Redirect'],
  )
  for (const item of NAV.flatMap((section) => section.items)) assert.equal(typeof item.page.load, 'function')
})

test('the sidebar foot holds Settings as a vendored glyph, with no eyebrow on its page', () => {
  assert.deepEqual(
    FOOT.items.map((item) => [item.path, t(item.label), item.glyph]),
    [['/admin/settings', 'Settings', 'settings']],
  )
  for (const item of FOOT.items) {
    assert.equal(typeof item.page.load, 'function')
    assert.ok(Object.hasOwn(GLYPH, item.glyph), item.glyph)
  }
  const route = findRoute('/admin/settings')
  assert.equal(route.item, FOOT.items[0])
  assert.equal(route.section.label, null)
  assert.equal(Object.values(strings).includes('Administration'), false)
  // Settings is in the foot only: the menu never draws it twice
  assert.equal(NAV.flatMap((section) => section.items).some((item) => item.path === '/admin/settings'), false)
})

test('an address is a page of the menu, or none', () => {
  assert.equal(findRoute('/admin/qrcodes').item.path, '/admin/qrcodes')
  assert.equal(findRoute('/admin/qrcodes/'), null)
  assert.equal(findRoute('/admin/cloudflare'), null)
  assert.equal(findRoute('/admin/settings').item.path, '/admin/settings')
  assert.equal(findRoute('/admin/settings/security'), null)
  assert.equal(findRoute('/admin/links/new'), null)
})

test('the old Cloudflare page opens the Cloudflare tab of Settings, its other flags kept', () => {
  assert.equal(movedTo('/admin/cloudflare', ''), '/admin/settings?tab=cloudflare')
  assert.equal(movedTo('/admin/cloudflare', '?keys=1'), '/admin/settings?keys=1&tab=cloudflare')
  assert.equal(movedTo('/admin/cloudflare', '?tab=security&configure=1'), '/admin/settings?tab=cloudflare')
  // Where it goes is a page of the menu, which moves nowhere: no loop
  const target = new URL(movedTo('/admin/cloudflare', ''), 'http://redirect.test')
  assert.equal(findRoute(target.pathname).item.path, '/admin/settings')
  assert.equal(movedTo(target.pathname, target.search), null)
  for (const path of ['/admin/cloudflare/', '/admin/Cloudflare', '/admin/settings', '/admin/links', '/admin/constructor', '/admin/__proto__']) {
    assert.equal(movedTo(path, ''), null, path)
  }
})

test('the status counts the links of every kind, in the words of 7.0.1', () => {
  assert.equal(statusText(t, 0), 'Running · 0 redirects')
  assert.equal(statusText(t, 1), 'Running · 1 redirect')
  assert.equal(statusText(t, 4), 'Running · 4 redirects')
  assert.equal(statusText(t, null), 'Running')
  assert.equal(statusText(t, '4'), 'Running')
})

test('a path someone else holds is said under the field that makes it', () => {
  const taken = { status: 409, code: 'redirect.slug_taken', params: {}, fields: {} }
  assert.deepEqual(placeTaken(taken, 'slug').fields, { slug: 'redirect.slug_taken' })
  assert.deepEqual(placeTaken(taken, 'name').fields, { name: 'redirect.name_taken' })
  assert.equal(placeTaken(taken, undefined), taken)
  const other = { status: 400, code: 'invalid', fields: { name: 'redirect.name_required' } }
  assert.equal(placeTaken(other, 'name'), other)
})

test('a path taken on a Cloudflare host stays under the address, where the server said it', () => {
  const taken = { status: 409, code: 'redirect.slug_taken', params: {}, fields: { address: 'redirect.address_taken' } }
  assert.equal(placeTaken(taken, 'slug'), taken)
  assert.equal(placeTaken(taken, 'name'), taken)
})
