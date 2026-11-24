// Ported from moonie-redirect 7.0.1 tests/js/links.test.mjs. The pure part of the Links page.
import assert from 'node:assert/strict'
import test from 'node:test'

import { linkBody, matchesLink, statusNoteKey } from '../../static/ui/links.js'

const LINK = {
  name: 'Resume',
  slug: 'pro/cv',
  target: 'https://cloud.example/cv.pdf',
  public_url: 'http://host.example:8420/redirect/pro/cv',
}

test('what every public address holds tells no link from another', () => {
  for (const search of ['redirect', '/redirect', '/redirect/', 'REDIRECT/']) assert.equal(matchesLink(LINK, search), false, search)
})

test('a link answers its name, its slug, its target and its public address', () => {
  for (const search of ['resume', 'pro/cv', 'cloud.example', '/redirect/pro', 'host.example']) {
    assert.equal(matchesLink(LINK, search), true, search)
  }
})

test('a link named or aimed at what every address holds still answers it', () => {
  assert.equal(matchesLink({ ...LINK, name: 'My redirect' }, 'redirect'), true)
  assert.equal(matchesLink({ ...LINK, slug: 'redirect' }, 'redirect'), true)
  assert.equal(matchesLink({ ...LINK, target: 'https://a.example/redirect' }, 'redirect'), true)
})

// A form as linkBody reads it: one control per name, with the http_status one that a page of 9.1.0 had
function fakeForm(values) {
  return { querySelector: (selector) => ({ value: values[/name="([^"]+)"/.exec(selector)[1]] ?? '' }) }
}

test('a save never sends a status code: a new link takes 302, an edit keeps the stored one (D20)', () => {
  const body = linkBody(fakeForm({ name: 'Resume', slug: 'pro/cv', target: 'https://cloud.example/cv.pdf', http_status: '301' }))
  assert.equal(Object.hasOwn(body, 'http_status'), false)
  assert.deepEqual(body, { name: 'Resume', slug: 'pro/cv', target: 'https://cloud.example/cv.pdf', expires_on: null })
})

test('an expiry goes trimmed, or as none when empty', () => {
  assert.equal(linkBody(fakeForm({ expires_on: ' 2027-12-31 ' })).expires_on, '2027-12-31')
  assert.equal(linkBody(fakeForm({ expires_on: '   ' })).expires_on, null)
})

test('only a link that answers other than 302 gets the note saying a save keeps its code', () => {
  assert.equal(statusNoteKey({ ...LINK, http_status: 301 }), 'redirect.status_kept')
  assert.equal(statusNoteKey({ ...LINK, http_status: 302 }), null)
  assert.equal(statusNoteKey(null), null)
  assert.equal(statusNoteKey(undefined), null)
})
