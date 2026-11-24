// Ported from moonie-redirect 7.0.1 tests/js/nanourls.test.mjs. The pure part of the NanoURL page.
import assert from 'node:assert/strict'
import test from 'node:test'

import { matchesNano } from '../../static/ui/nanourls.js'

const nano = { name: 'Team lunch', target: 'https://wiki.example/lunch', short_url: 'http://redirect.lan/links/AbCd2345', slug: 'NanoURL/Team-lunch' }

test('what every short link holds finds no row', () => {
  for (const search of ['/links/', 'links', '/links', 'LINKS/', ' /links/ ']) assert.equal(matchesNano(nano, search), false, search)
})

test('what tells a row from another finds it', () => {
  for (const search of ['', 'lunch', 'wiki.example', 'redirect.lan', 'AbCd', '/links/Ab', 'http://redirect.lan/links/AbCd2345']) {
    assert.equal(matchesNano(nano, search), true, search)
  }
})

test('a name or a target holding it is still found', () => {
  assert.equal(matchesNano({ ...nano, name: 'My links' }, 'links'), true)
  assert.equal(matchesNano({ ...nano, target: 'https://a.example/links/x' }, '/links/'), true)
})

test('the path is not searched: it holds NanoURL on every row', () => {
  assert.equal(matchesNano(nano, 'NanoURL'), false)
})
