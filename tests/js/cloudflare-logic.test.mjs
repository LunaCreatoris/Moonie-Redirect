// What the Cloudflare page decides, with no document: the cases of the Cloudflare plugin's tests/js/logic.test.mjs for what
// this app kept, and the address of a link in the Redirect pages.
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  FALLBACK_CHOICES,
  accountsWithList,
  quotaChipAccounts,
  addressChoices,
  applyBody,
  blockedKey,
  breaksAddress,
  defaultTicks,
  errorText,
  fallbackBlockedKey,
  fallbackBody,
  fallbackName,
  fallbackNoticeKey,
  fallbackOf,
  fallbackOffered,
  fallbackRefusalText,
  fallbackTarget,
  gapCount,
  groupDigits,
  linkStateView,
  liveHosts,
  planConfirmable,
  proposalOpen,
  quotaBanner,
  quotaLevel,
  refusalText,
  resyncBody,
  resyncLabel,
  stateReadable,
  stepText,
  tokenView,
  verdictView,
  visibleUrl,
} from '../../static/ui/cloudflare-logic.js'
import { deleteOptions, sharedUrl } from '../../static/ui/common.js'
import { apiError } from '../../static/ui/lib.js'
import strings from '../../static/ui/en.json' with { type: 'json' }

test('a value named after something every object has is no state, verdict or block', () => {
  for (const name of ['constructor', '__proto__', 'toString', 'hasOwnProperty']) {
    assert.equal(linkStateView({ cloudflare: { state: name } }).key, 'cloudflare.state_pending')
    assert.equal(verdictView(name).key, 'cloudflare.verdict_conflict')
    assert.equal(fallbackBlockedKey({ fallback_blocked: name }), null)
    assert.equal(fallbackNoticeKey({ fallback: 'https://example.org/', fallback_blocked: name }), 'cloudflare.notice_fallback')
    assert.equal(blockedKey(name), 'cloudflare.plan_blocked')
    assert.equal(errorText({ code: name }).key, 'cloudflare.error_unknown')
  }
})

test('a plan on a host already serving traffic is confirmed only once that is ticked', () => {
  assert.equal(planConfirmable(null, true), false)
  assert.equal(planConfirmable({ blocked: 'conflict', live: false }, true), false)
  assert.equal(planConfirmable({ blocked: null, live: false }, false), true)
  assert.equal(planConfirmable({ blocked: null, live: true }, false), false)
  assert.equal(planConfirmable({ blocked: null, live: true }, true), true)
  assert.equal(blockedKey('admin_host'), 'cloudflare.admin_host')
  assert.equal(blockedKey('page_points_here'), 'cloudflare.page_points_here')
  assert.equal(blockedKey('host_exists'), 'cloudflare.host_exists')
  assert.deepEqual(applyBody({ zone_id: 'z', label: 'go' }, { fingerprint: 'f', live: true }), {
    zone_id: 'z',
    label: 'go',
    fingerprint: 'f',
    confirm_live: true,
  })
  assert.equal(applyBody({}, { fingerprint: 'f', live: false }).confirm_live, false)
})

test('an address never hides a character that makes it read as another one', () => {
  assert.equal(visibleUrl('go.example.com/promo'), 'go.example.com/promo')
  assert.equal(visibleUrl('go.example.com/‮gnp.exe'), 'go.example.com/\\u{202e}gnp.exe')
  assert.equal(visibleUrl('a​b c\u0007d'), 'a\\u{200b}b\\u{2028}c\\u{7}d')
  assert.equal(visibleUrl('https://bücher.example/é'), 'https://bücher.example/é')
  assert.equal(visibleUrl(null), '')
})

test('each token state has its chip and its lines', () => {
  assert.deepEqual(tokenView({ state: 'ok', missing: [], unverified: [] }), { level: 'success', chip: 'cloudflare.token_ok', banners: [] })
  const refused = tokenView({ state: 'invalid', missing: [], unverified: [] })
  assert.equal(refused.level, 'danger')
  assert.equal(refused.banners[0].key, 'cloudflare.token_refused_text')
  assert.equal(tokenView({ state: 'unchecked' }).chip, 'cloudflare.token_unchecked')
  assert.equal(tokenView({ state: 'off' }).chip, 'cloudflare.token_unchecked')
  assert.equal(tokenView(undefined).chip, 'cloudflare.token_unchecked')
  const both = tokenView({ state: 'ok', missing: ['DNS Write', 'Zone Read'], unverified: ['Account Rulesets Write'] })
  assert.equal(both.chip, 'cloudflare.token_missing')
  assert.deepEqual(
    both.banners.map((line) => [line.level, line.params.permissions]),
    [
      ['warning', 'DNS Write, Zone Read'],
      ['info', 'Account Rulesets Write'],
    ],
  )
  assert.equal(tokenView({ state: 'ok', missing: [], unverified: ['DNS Write'] }).chip, 'cloudflare.token_unverified')
})

test('a count groups its digits by threes, as the language writes them', () => {
  assert.equal(groupDigits(10000, ','), '10,000')
  assert.equal(groupDigits(999, ','), '999')
  assert.equal(groupDigits(1234567, ','), '1,234,567')
  assert.equal(quotaBanner({ name: 'A', quota: { used: 10000, limit: 10000 } }, ',').params.limit, '10,000')
})

test('the quota warns from 90% and is full at the limit', () => {
  assert.equal(quotaLevel({ used: 8, limit: 10 }), 'success')
  assert.equal(quotaLevel({ used: 9, limit: 10 }), 'warning')
  assert.equal(quotaLevel({ used: 10, limit: 10 }), 'danger')
  assert.equal(quotaLevel({ used: 12, limit: 10 }), 'danger')
  assert.equal(quotaLevel({ used: 0, limit: 0 }), 'success')
  assert.equal(quotaBanner({ name: 'A', quota: { used: 1, limit: 10 } }), null)
  assert.deepEqual(quotaBanner({ name: 'A', quota: { used: 10, limit: 10 } }), {
    level: 'danger',
    key: 'cloudflare.quota_full_text',
    params: { account: 'A', used: '10', limit: '10' },
  })
  assert.equal(quotaBanner({ name: 'A', quota: { used: 9, limit: 10 } }).key, 'cloudflare.quota_near_text')
  assert.deepEqual(accountsWithList([{ list: null }, { list: { id: 'x' } }]), [{ list: { id: 'x' } }])
  const accounts = [{ list: null }, { list: { id: 'x' } }]
  assert.deepEqual(quotaChipAccounts({ token: { state: 'ok' }, accounts }), [{ list: { id: 'x' } }])
  assert.deepEqual(quotaChipAccounts({ token: { state: 'invalid' }, accounts }), [])
})

test('link states, verdicts and steps have their words', () => {
  assert.equal(linkStateView({ cloudflare: null }), null)
  assert.equal(linkStateView(undefined), null)
  assert.equal(linkStateView({ cloudflare: { state: 'error' } }).level, 'danger')
  assert.equal(linkStateView({ cloudflare: { state: 'expired' } }).key, 'cloudflare.state_expired')
  assert.equal(linkStateView({ cloudflare: { state: 'odd' } }).key, 'cloudflare.state_pending')
  assert.equal(verdictView('ready').level, 'success')
  assert.equal(verdictView('added').level, null)
  assert.equal(proposalOpen({ verdict: 'create' }), true)
  assert.equal(proposalOpen({ verdict: 'conflict' }), false)
  assert.equal(proposalOpen({ verdict: 'added' }), false)
  assert.deepEqual(stepText({ do: 'create_record', type: 'A', name: 'go.example.com', content: '192.0.2.1', proxied: true }), {
    key: 'cloudflare.step_create_record',
    params: { type: 'A', name: 'go.example.com', content: '192.0.2.1' },
  })
  assert.equal(stepText({ do: 'create_list', name: 'moonie_redirect' }).params.name, 'moonie_redirect')
  for (const step of ['add_fallback', 'root_held', 'root_full', 'no_fallback', 'keep_ours', 'use_record', 'create_entrypoint', 'add_rule']) {
    assert.equal(stepText({ do: step }).key, `cloudflare.step_${step}`)
  }
  assert.equal(stepText({ do: 'what' }).key, 'cloudflare.step_unknown')
  assert.equal(blockedKey(null), null)
  assert.equal(blockedKey('conflict'), 'cloudflare.conflict')
})

test('a host shows its own choice, none first, and any other address as another address', () => {
  assert.deepEqual(
    FALLBACK_CHOICES.map((choice) => choice.id),
    ['none', 'wikipedia', 'google', 'other'],
  )
  assert.equal(fallbackOf('https://www.google.com/'), 'google')
  assert.equal(fallbackOf('https://en.wikipedia.org/wiki/HTTP_404'), 'wikipedia')
  assert.equal(fallbackOf('https://www.example.org/lost'), 'other')
  for (const target of [null, undefined, '', 3]) assert.equal(fallbackOf(target), 'none')
  assert.equal(fallbackTarget('none', 'ignored'), null)
  assert.equal(fallbackTarget('google', 'ignored'), 'https://www.google.com/')
  assert.equal(fallbackTarget('other', 'https://www.example.org/lost'), 'https://www.example.org/lost')
  assert.deepEqual(fallbackName('https://www.google.com/'), { key: 'cloudflare.fallback_google' })
  assert.deepEqual(fallbackName('https://www.example.org/lost'), { text: 'https://www.example.org/lost' })
  assert.deepEqual(fallbackBody(null), { fallback: null })
})

test('the hosts sent nothing as their record points at a real origin are named for the warning', () => {
  assert.deepEqual(liveHosts([{ host: 'a', fallback_blocked: 'live' }, { host: 'b', fallback_blocked: 'held' }, { host: 'c', fallback_blocked: null }]), ['a'])
  assert.deepEqual(liveHosts(undefined), [])
})

test('only a host set up here offers a page for unknown paths', () => {
  assert.equal(fallbackOffered({ created_by_us: true }), true)
  assert.equal(fallbackOffered({ created_by_us: false }), false)
  assert.equal(fallbackOffered({}), false)
  assert.equal(fallbackOffered(null), false)
})

test('a comparison names a row by the address the server gave it, else by its id', () => {
  const sources = { abc: 'https://go.example.com/promo', 'fallback:go.example.com': 'https://go.example.com/' }
  assert.equal(resyncLabel(sources, 'abc'), 'https://go.example.com/promo')
  assert.equal(resyncLabel(sources, 'fallback:go.example.com'), 'https://go.example.com/')
  assert.equal(resyncLabel(sources, 'zzz'), 'zzz')
  assert.equal(resyncLabel(undefined, 'abc'), 'abc')
  assert.equal(resyncLabel({ constructor: 1 }, 'constructor'), 'constructor')
})

test('a comparison ticks every push and no removal, and confirms the count it removes', () => {
  const compare = {
    fingerprint: 'f',
    accounts: [
      { account_id: 'a', missing: ['e1'], differs: [{ id: 'e2', remote: {} }], extra: [{ remote_id: 'r1' }, { remote_id: 'r2' }] },
      { account_id: 'b', missing: [], differs: [], extra: [] },
    ],
  }
  assert.equal(gapCount(compare), 4)
  assert.equal(gapCount({ accounts: [] }), 0)
  const ticks = defaultTicks(compare)
  assert.deepEqual([...ticks.push], ['e1', 'e2'])
  assert.equal(ticks.remove.size, 0)
  ticks.remove.add('r2')
  assert.deepEqual(resyncBody(compare, ticks), { fingerprint: 'f', push: ['e1', 'e2'], remove: ['r2'], confirm_remove: 1 })
})

test('an error says its code, with Cloudflare\'s words apart', () => {
  assert.equal(errorText(null), null)
  assert.equal(errorText('an English sentence'), null)
  assert.deepEqual(errorText({ code: 'foreign_item', detail: null }), { key: 'cloudflare.error_foreign_item', params: {}, detail: null })
  assert.deepEqual(errorText({ code: 'refused', detail: '400: invalid source_url' }), {
    key: 'cloudflare.error_refused',
    params: {},
    detail: '400: invalid source_url',
  })
  assert.deepEqual(errorText({ code: 'from_a_newer_server', detail: '' }), { key: 'cloudflare.error_unknown', params: {}, detail: null })
  assert.equal(errorText({ code: 'refused', detail: 7 }).detail, null)
  assert.equal(errorText({ code: 'admin_host', detail: null }).key, 'cloudflare.error_admin_host')
})

test('a host says what stops its page, and a change of page never promises one it will not reach', () => {
  assert.equal(fallbackBlockedKey({ fallback_blocked: 'held' }), 'cloudflare.fallback_blocked_held')
  assert.equal(fallbackBlockedKey({ fallback_blocked: 'loops' }), 'cloudflare.fallback_blocked_loops')
  for (const host of [{ fallback_blocked: null }, { fallback_blocked: 'other' }, {}, null]) assert.equal(fallbackBlockedKey(host), null)
  const page = 'https://example.org/'
  assert.equal(fallbackNoticeKey({ fallback: page, fallback_blocked: null }), 'cloudflare.notice_fallback')
  assert.equal(fallbackNoticeKey({ fallback: page, fallback_blocked: 'live' }), 'cloudflare.notice_fallback_live')
  assert.equal(fallbackNoticeKey({ fallback: null, fallback_blocked: null }), 'cloudflare.notice_fallback_none')
})

test('a refused change of page says the reason of its field, else the refusal itself', () => {
  assert.deepEqual(fallbackRefusalText({ fields: { fallback: 'cloudflare.fallback_loop' } }), { key: 'cloudflare.fallback_loop', params: {} })
  assert.deepEqual(fallbackRefusalText({ fields: { target: 'redirect.target_invalid' } }), { key: 'redirect.target_invalid', params: {} })
  assert.deepEqual(fallbackRefusalText({ code: 'cloudflare.busy' }), { key: 'cloudflare.busy', params: {} })
  assert.deepEqual(fallbackRefusalText({}), { key: 'cloudflare.no_answer', params: {} })
  assert.deepEqual(refusalText({ status: 200, code: null }), { key: 'cloudflare.no_answer', params: {} })
})

test('the server\'s Cloudflare refusals read as texts of the page', () => {
  for (const word of ['plan_stale', 'busy', 'remote_changed', 'unreachable', 'rate_limited', 'needs_admin', 'confirm_live']) {
    const key = apiError('POST', '/api/cloudflare/apply', 409, { error: word }).code
    assert.ok(Object.hasOwn(strings, key), `${word} -> ${key}`)
  }
  for (const word of ['quota_full', 'cloudflare_off', 'confirm_break']) {
    assert.ok(Object.hasOwn(strings, apiError('POST', '/api/links', 409, { error: word }).code), word)
  }
  const fields = (field, message) => apiError('POST', '/api/links', 400, { error: 'invalid', fields: { [field]: message } }).fields[field]
  assert.equal(fields('address', 'not a host set up here'), 'redirect.address_unknown')
  assert.equal(fields('address', '.well-known is reserved on a Cloudflare host'), 'redirect.address_well_known')
  assert.equal(fields('address', 'this path is taken on this host'), 'redirect.address_taken')
  assert.equal(fields('address', "this instance's own host: choose another"), 'redirect.address_admin_host')
  assert.equal(fields('address', 'lan or a host set up here'), 'redirect.address_invalid')
  assert.equal(fields('fallback', 'page_loop'), 'cloudflare.fallback_loop')
  assert.equal(fields('fallback', 'admin_host'), 'cloudflare.admin_host')
  assert.equal(fields('label', 'one DNS label'), 'cloudflare.label_invalid')
})

test('a form offers an address only once a host is set up', () => {
  const lan = { address: 'lan', url: 'http://redirect.lan', adopted: false }
  assert.equal(addressChoices(undefined), null)
  assert.equal(addressChoices([lan]), null)
  const both = [lan, { address: 'go.example.com', url: 'https://go.example.com', adopted: false }]
  assert.equal(addressChoices(both), both)
})

test('giving up a Cloudflare address is asked first, any other change is not', () => {
  const onHost = { address: 'go.example.com' }
  assert.equal(breaksAddress(onHost, 'lan'), true)
  assert.equal(breaksAddress(onHost, 'www.example.com'), true)
  assert.equal(breaksAddress(onHost, 'go.example.com'), false)
  assert.equal(breaksAddress({ address: 'lan' }, 'go.example.com'), false)
  assert.equal(breaksAddress(null, 'lan'), false)
  // A link's new slug moves its path on the host; the same slug, or none sent (NanoURLs, QR codes), moves nothing
  const promo = { address: 'go.example.com', slug: 'promo' }
  assert.equal(breaksAddress(promo, 'go.example.com', 'renamed'), true)
  assert.equal(breaksAddress(promo, 'go.example.com', 'promo'), false)
  assert.equal(breaksAddress(promo, 'go.example.com', undefined), false)
  assert.equal(breaksAddress({ address: 'lan', slug: 'promo' }, 'lan', 'renamed'), false)
})

test('a row shows and copies its Cloudflare address, and a delete of one says it was asked', () => {
  const lan = { cloudflare: null, address_url: 'http://redirect.lan/redirect/promo' }
  const onHost = { cloudflare: { state: 'active', error: null }, address_url: 'https://go.example.com/promo' }
  assert.equal(sharedUrl(lan, 'http://redirect.lan/links/abc'), 'http://redirect.lan/links/abc')
  assert.equal(sharedUrl(onHost, 'http://redirect.lan/links/abc'), 'https://go.example.com/promo')
  assert.deepEqual(deleteOptions(lan, 'abc'), { method: 'DELETE', id: 'abc' })
  assert.deepEqual(deleteOptions(onHost, 'abc'), { method: 'DELETE', id: 'abc', json: { confirm_break: true } })
})

test('a state answer the tab cannot draw is a failed load', () => {
  assert.equal(stateReadable({ token: {}, counts: {}, accounts: [], hosts: [] }), true)
  assert.equal(stateReadable({ token: {}, counts: {}, accounts: [], hosts: null }), false)
  assert.equal(stateReadable({ token: {}, counts: {}, accounts: {}, hosts: [] }), false)
  assert.equal(stateReadable({ counts: {}, accounts: [], hosts: [] }), false)
  assert.equal(stateReadable(null), false)
  assert.equal(stateReadable('<html>'), false)
})
