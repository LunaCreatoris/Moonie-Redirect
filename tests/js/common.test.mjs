// Ported from moonie-redirect 7.0.1 tests/js/common.test.mjs, less what 9.0.0 dropped. The pure part of what the pages share.
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  addressWith,
  bringIntoView,
  byCount,
  clearNotice,
  drawsNew,
  formatTime,
  isGone,
  isLeaving,
  keepForNextDraw,
  matchesSearch,
  matchesTelling,
  noRowsKey,
  pageMemory,
  savedLink,
  takeKept,
} from '../../static/ui/common.js'

const LINK = {
  name: 'Résumé, updated',
  slug: 'pro/resume',
  target: 'https://cloud.example/Resume-2026.pdf',
  public_url: 'http://redirect.lan:8420/redirect/pro/resume',
}

test('a time shows in full, in the zone of the browser', () => {
  process.env.TZ = 'UTC'
  assert.equal(formatTime('2026-11-02T09:15:07Z'), '2026-11-02 09:15:07')
})

test('what is no time shows as it came', () => {
  assert.equal(formatTime('soon'), 'soon')
  assert.equal(formatTime(null), '')
  assert.equal(formatTime(undefined), '')
})

for (const [search, expected] of [
  ['', true],
  ['   ', true],
  ['résumé,', true],
  ['RÉSUMÉ,', true],
  ['pro/', true],
  ['cloud.example/resume', true],
  ['redirect.lan', true],
  ['  updated  ', true],
  ['absent', false],
]) {
  test(`the search ${JSON.stringify(search)} answers ${expected}`, () => {
    assert.equal(matchesSearch(LINK, search), expected)
  })
}

test('a link with a missing field does not break the search', () => {
  assert.equal(matchesSearch({ name: 'A' }, 'a'), true)
  assert.equal(matchesSearch({ name: 'A' }, 'b'), false)
})

test('a search on what a field always holds leaves that field out, and the others still answer', () => {
  const fields = { name: [], public_url: ['/redirect/'] }
  assert.equal(matchesTelling({ name: 'A', public_url: 'http://h/redirect/x' }, 'redirect', fields), false)
  assert.equal(matchesTelling({ name: 'A', public_url: 'http://h/redirect/x' }, ' /REDIRECT/ ', fields), false)
  assert.equal(matchesTelling({ name: 'My redirect', public_url: 'http://h/redirect/x' }, 'redirect', fields), true)
  assert.equal(matchesTelling({ name: 'A', public_url: 'http://h/redirect/x' }, 'redirect/x', fields), true)
  assert.equal(matchesTelling({ name: 'A', public_url: 'http://h/redirect/x' }, '', fields), true)
})

test('a search reads only the fields it is told to', () => {
  assert.equal(matchesSearch(LINK, 'pro/resume'), true)
  assert.equal(matchesSearch(LINK, 'pro/resume', ['name', 'target']), false)
  assert.equal(matchesSearch(LINK, 'CLOUD', ['name', 'target']), true)
})

test('an address keeps the rest of the query', () => {
  const query = new URLSearchParams('zones=1&link=abc')
  assert.equal(addressWith('/admin/links', query, { link: 'def' }), '/admin/links?zones=1&link=def')
  assert.equal(addressWith('/admin/links', query, { link: null }), '/admin/links?zones=1')
  assert.equal(addressWith('/admin/links', query, { new: '1', link: null }), '/admin/links?zones=1&new=1')
})

test('an address with nothing left has no question mark', () => {
  assert.equal(addressWith('/admin/links', new URLSearchParams('link=abc'), { link: null }), '/admin/links')
})

test('an address leaves the query it was given alone', () => {
  const query = new URLSearchParams('link=abc')
  addressWith('/admin/links', query, { link: null })
  assert.equal(query.get('link'), 'abc')
})

test('leaving and a lost session are nothing to tell', () => {
  assert.equal(isLeaving({ name: 'AbortError' }), true)
  assert.equal(isLeaving({ status: 401, code: 'errors.unauthorized' }), true)
  assert.equal(isLeaving({ status: 401, code: 'redirect.other' }), false)
  assert.equal(isLeaving({ status: 500 }), false)
  assert.equal(isLeaving(null), false)
})

test('what a page keeps is read once', () => {
  keepForNextDraw({ search: 'a' })
  assert.deepEqual(takeKept(), { search: 'a' })
  assert.equal(takeKept(), null)
})

test('an answer that holds no link saved nothing, and says so as a failed call', () => {
  assert.deepEqual(savedLink({ id: 'abc' }), { id: 'abc' })
  for (const junk of [null, undefined, {}, { id: 1 }, 'portal']) {
    assert.throws(() => savedLink(junk), (error) => error.status === 200 && error.code === null)
  }
})

test('a search skips a field that is no text', () => {
  assert.equal(matchesSearch({ name: 12, slug: 'abc' }, 'abc'), true)
})

test('only the instance says that a row is gone', () => {
  assert.equal(isGone({ status: 404, code: 'errors.not_found' }), true)
  assert.equal(isGone({ status: 404, code: null }), false)
  assert.equal(isGone({ status: 500, code: 'errors.not_found' }), false)
  assert.equal(isGone(undefined), false)
})

// --- What a page keeps, compares and says ----------------------------------------------------------------------------

function at(pathname, search = '') {
  globalThis.location = { pathname, search }
}

test('what a page kept is dropped by another page, and read once by its own', (t) => {
  t.after(() => delete globalThis.location)
  at('/admin/nanourls')
  keepForNextDraw({ said: 'saved' })
  at('/admin/links')
  assert.equal(takeKept(), null)
  at('/admin/nanourls')
  assert.equal(takeKept(), null)
  keepForNextDraw({ said: 'saved' })
  assert.deepEqual(takeKept(), { said: 'saved' })
  assert.equal(takeKept(), null)
})

test('a page memory comes back at its own address only, and once', (t) => {
  t.after(() => delete globalThis.location)
  const memory = pageMemory()
  at('/admin/nanourls', '?link=a')
  memory.leaving({ address: '/admin/nanourls?link=a', id: 'a' })
  assert.equal(memory.takeShown('/admin/nanourls'), null)
  memory.leaving({ address: '/admin/nanourls?link=a', id: 'a' })
  assert.equal(memory.takeShown('/admin/nanourls?link=a').id, 'a')
  assert.equal(memory.takeShown('/admin/nanourls?link=a'), null)
})

test('a new form stays new when the address asks for it or when the form it comes back to was one', () => {
  assert.equal(drawsNew(true, null), true)
  assert.equal(drawsNew(false, { isNew: true }), true)
  assert.equal(drawsNew(false, { id: 'a', isNew: false }), false)
  assert.equal(drawsNew(false, null), false)
  assert.equal(drawsNew(false, undefined), false)
})

test('a list with no row says why: none answers the search, or there is none yet', () => {
  assert.equal(noRowsKey(3, 'match', 'yet'), 'match')
  assert.equal(noRowsKey(1, 'match', 'yet'), 'match')
  assert.equal(noRowsKey(0, 'match', 'yet'), 'yet')
})

function boxAt(top, bottom = top + 900) {
  const box = {
    scrolled: 0,
    getBoundingClientRect: () => ({ top, bottom }),
    scrollIntoView: () => {
      box.scrolled += 1
    },
  }
  return box
}

function scrollsAt(top) {
  globalThis.window = { innerHeight: 600 }
  const box = boxAt(top)
  bringIntoView(box)
  return box.scrolled
}

test('a form whose top is in view stays where it is, however tall it is', () => {
  assert.equal(scrollsAt(0), 0)
  assert.equal(scrollsAt(120), 0)
  assert.equal(scrollsAt(600 - 48), 0)
})

test('a form above the window or below it comes into view', () => {
  assert.equal(scrollsAt(-1), 1)
  assert.equal(scrollsAt(2400), 1)
  assert.equal(scrollsAt(600), 1)
})

test('a form with barely its top in the window comes into view too: a press must show something', () => {
  assert.equal(scrollsAt(600 - 47), 1)
})

test('a line that gave way says nothing and shows nothing', () => {
  const removed = []
  const line = { hidden: false, textContent: 'Gone', classList: { remove: (name) => removed.push(name) } }
  clearNotice(line)
  assert.equal(line.hidden, true)
  assert.equal(line.textContent, '')
  assert.deepEqual(removed, ['redirect-notice-error'])
})

test('a count picks the form of none, one or many', () => {
  const forms = [[0, 'none'], [1, 'one'], [2, 'many'], [21, 'many'], [1000000, 'many']]
  for (const [count, form] of forms) assert.equal(byCount(count, 'none', 'one', 'many'), form)
})
