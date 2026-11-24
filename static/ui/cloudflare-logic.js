// Source: Moonie Redirect 7.0.1 Cloudflare plugin, ui/logic.js, trimmed: the entry tabs and their forms (a link
// carries its address here), held hosts, the settings page, text keys built at run time (each one is written out). Added: a link's state as
// the Redirect pages show it, the confirmation a change that stops a Cloudflare address needs, and the reader of the
// state answer. The refused token's banner points to the token's row, as the plugin's pointed to its own settings.
// What the domains of Settings > Cloudflare decide, with no document: which words and levels a state gets, and the
// bodies their calls send. Pure, so that node tests it (tests/js), and the tab only draws what this answers.

// A value from an answer looked up in one of these tables: `constructor` or `__proto__` is no state, whatever a server says
function own(table, key) {
  return typeof key === 'string' && Object.hasOwn(table, key) ? table[key] : undefined
}

// Whether the state answer can be drawn. A proxy's page answered 200 reaches the tab as null or as anything else.
export function stateReadable(state) {
  return Boolean(state?.token && state.counts && Array.isArray(state.accounts) && Array.isArray(state.hosts))
}

// The token's chip, and the lines under the head that say what to do. A token both short of a permission and with one
// that could not be looked at says both.
export function tokenView(token) {
  const missing = Array.isArray(token?.missing) ? token.missing : []
  const unverified = Array.isArray(token?.unverified) ? token.unverified : []
  if (token?.state === 'invalid') {
    return { level: 'danger', chip: 'cloudflare.token_refused', banners: [{ level: 'danger', key: 'cloudflare.token_refused_text', settings: true }] }
  }
  if (token?.state !== 'ok') {
    return { level: 'info', chip: 'cloudflare.token_unchecked', banners: [{ level: 'info', key: 'cloudflare.token_unchecked_text' }] }
  }
  const banners = []
  if (missing.length) banners.push({ level: 'warning', key: 'cloudflare.token_missing_text', params: { permissions: missing.join(', ') } })
  if (unverified.length) banners.push({ level: 'info', key: 'cloudflare.token_unverified_text', params: { permissions: unverified.join(', ') } })
  if (missing.length) return { level: 'warning', chip: 'cloudflare.token_missing', banners }
  if (unverified.length) return { level: 'info', chip: 'cloudflare.token_unverified', banners }
  return { level: 'success', chip: 'cloudflare.token_ok', banners }
}

// Warning from 90% of the account's list items, danger once they are all used
export const QUOTA_WARNING = 0.9

export function quotaLevel(quota) {
  const used = Number(quota?.used) || 0
  const limit = Number(quota?.limit) || 0
  if (limit > 0 && used >= limit) return 'danger'
  if (limit > 0 && used >= limit * QUOTA_WARNING) return 'warning'
  return 'success'
}

// A count with its digits grouped by threes, as the language writes them: 10,000 or 10 000
export function groupDigits(value, separator) {
  return String(value).replace(/\B(?=(\d{3})+$)/g, separator)
}

// The banner a quota needs, or none
export function quotaBanner(account, separator = '') {
  const level = quotaLevel(account.quota)
  if (level === 'success') return null
  const params = { account: account.name, used: groupDigits(account.quota.used, separator), limit: groupDigits(account.quota.limit, separator) }
  return { level, key: level === 'danger' ? 'cloudflare.quota_full_text' : 'cloudflare.quota_near_text', params }
}

const LINK_STATES = {
  active: { level: 'success', key: 'cloudflare.state_active' },
  pending: { level: 'info', key: 'cloudflare.state_pending' },
  error: { level: 'danger', key: 'cloudflare.state_error' },
  expired: { level: 'warning', key: 'cloudflare.state_expired' },
}

// The chip of a link's Cloudflare state, as its answer's `cloudflare` says it; null for a link on the LAN
export function linkStateView(link) {
  if (!link?.cloudflare) return null
  return own(LINK_STATES, link.cloudflare.state) ?? LINK_STATES.pending
}

// The text of each code an error may hold (the sync's codes); any other reads as unknown
const ERROR_TEXTS = {
  foreign_item: 'cloudflare.error_foreign_item',
  refused: 'cloudflare.error_refused',
  rate_limited: 'cloudflare.error_rate_limited',
  token_invalid: 'cloudflare.error_token_invalid',
  permission: 'cloudflare.error_permission',
  unreachable: 'cloudflare.error_unreachable',
  operation_failed: 'cloudflare.error_operation_failed',
  operation_expired: 'cloudflare.error_operation_expired',
  list_full: 'cloudflare.error_list_full',
  list_missing: 'cloudflare.error_list_missing',
  origin_live: 'cloudflare.error_origin_live',
  page_loop: 'cloudflare.error_page_loop',
  admin_host: 'cloudflare.error_admin_host',
  internal: 'cloudflare.error_internal',
}

// What a link or an account error says: the text key of its code, and Cloudflare's own words as they came, or null when
// there is no error
export function errorText(error) {
  if (!error || typeof error !== 'object') return null
  const key = own(ERROR_TEXTS, error.code) ?? 'cloudflare.error_unknown'
  const detail = typeof error.detail === 'string' && error.detail ? error.detail : null
  return { key, params: {}, detail }
}

const VERDICTS = {
  create: { level: 'info', key: 'cloudflare.verdict_create' },
  ready: { level: 'success', key: 'cloudflare.verdict_ready' },
  conflict: { level: 'danger', key: 'cloudflare.verdict_conflict' },
  added: { level: null, key: 'cloudflare.verdict_added' },
}

export function verdictView(verdict) {
  return own(VERDICTS, verdict) ?? VERDICTS.conflict
}

// Whether a proposal can be chosen: one already set up or not proxied would only be refused
export function proposalOpen(proposal) {
  return proposal?.verdict === 'create' || proposal?.verdict === 'ready'
}

// One line of "What will be done", as a text key and its values
export function stepText(step) {
  switch (step?.do) {
    case 'create_list':
      return { key: 'cloudflare.step_create_list', params: { name: step.name } }
    case 'create_entrypoint':
      return { key: 'cloudflare.step_create_entrypoint', params: {} }
    case 'add_rule':
      return { key: 'cloudflare.step_add_rule', params: {} }
    case 'create_record':
      return { key: 'cloudflare.step_create_record', params: { type: step.type, name: step.name, content: step.content } }
    case 'use_record':
      return { key: 'cloudflare.step_use_record', params: { type: step.type, name: step.name, content: step.content } }
    case 'add_fallback':
      return { key: 'cloudflare.step_add_fallback', params: { source: step.source, target: step.target } }
    case 'root_held':
      return { key: 'cloudflare.step_root_held', params: { source: step.source } }
    case 'root_full':
      return { key: 'cloudflare.step_root_full', params: { source: step.source } }
    case 'no_fallback':
      return { key: 'cloudflare.step_no_fallback', params: { name: step.name } }
    case 'keep_ours':
      return { key: 'cloudflare.step_keep_ours', params: { name: step.name } }
    default:
      return { key: 'cloudflare.step_unknown', params: {} }
  }
}

// The pages a host's fallback suggests. Any other address is typed, and the server checks it like a link's target
export const FALLBACK_SUGGESTIONS = [
  { id: 'wikipedia', key: 'cloudflare.fallback_wikipedia', url: 'https://en.wikipedia.org/wiki/HTTP_404' },
  { id: 'google', key: 'cloudflare.fallback_google', url: 'https://www.google.com/' },
]

// The control's choices, nothing first as a host starts with nothing
export const FALLBACK_CHOICES = [
  { id: 'none', key: 'cloudflare.fallback_choice_none' },
  ...FALLBACK_SUGGESTIONS,
  { id: 'other', key: 'cloudflare.fallback_choice_other' },
]

// Which choice an address reads as
export function fallbackOf(target) {
  if (typeof target !== 'string' || !target) return 'none'
  return FALLBACK_SUGGESTIONS.find((choice) => choice.url === target)?.id ?? 'other'
}

// The address a choice stands for, with what was typed for another one: null for none
export function fallbackTarget(id, typed) {
  if (id === 'none') return null
  if (id === 'other') return typed
  return FALLBACK_SUGGESTIONS.find((choice) => choice.id === id)?.url ?? null
}

// What a notice calls a page: a suggestion by its name, any other address as it is. Null: a key to translate is in `key`
export function fallbackName(target) {
  const found = FALLBACK_SUGGESTIONS.find((choice) => choice.url === target)
  return found ? { key: found.key } : { text: visibleUrl(String(target)) }
}

// The hosts whose record now points at a real origin, for the warning at the top of the page: the sync sends them nothing
export function liveHosts(hosts) {
  return (hosts ?? []).filter((host) => host?.fallback_blocked === 'live').map((host) => host.host)
}

// Whether a host has a page for unknown paths: only one set up here, as one found may serve a real site
export function fallbackOffered(host) {
  return host?.created_by_us === true
}

// How a comparison names a row: by the address it answers at, as the server gave it, else by its id
export function resyncLabel(sources, id) {
  return typeof sources?.[id] === 'string' ? sources[id] : id
}

// The body of a page change: an address, or null for none
export function fallbackBody(target) {
  return { fallback: target }
}

// What stops a host's page for unknown paths from being there, said under its choice: null when nothing does
export function fallbackBlockedKey(host) {
  const keys = {
    held: 'cloudflare.fallback_blocked_held',
    refused: 'cloudflare.fallback_blocked_refused',
    full: 'cloudflare.fallback_blocked_full',
    live: 'cloudflare.fallback_blocked_live',
    loops: 'cloudflare.fallback_blocked_loops',
  }
  return own(keys, host?.fallback_blocked) ?? null
}

// What a change of page says, from the host as the call answered it: never a page that will not be reached
export function fallbackNoticeKey(host) {
  if (!host?.fallback) return 'cloudflare.notice_fallback_none'
  const keys = { held: 'cloudflare.notice_fallback_held', full: 'cloudflare.notice_fallback_full', live: 'cloudflare.notice_fallback_live' }
  return own(keys, host.fallback_blocked) ?? 'cloudflare.notice_fallback'
}

// What a refused change says. The select is the only field and it is already back on its value, so the field's own reason
// is the sentence, not the generic "correct the fields"
export function fallbackRefusalText(error) {
  const reason = error?.fields?.fallback ?? error?.fields?.target
  return typeof reason === 'string' ? { key: reason, params: {} } : refusalText(error)
}

// Why a plan cannot be confirmed: the same texts as the refusals its confirmation would get
export function blockedKey(blocked) {
  const keys = {
    conflict: 'cloudflare.conflict',
    lists_full: 'cloudflare.lists_full',
    rules_full: 'cloudflare.rules_full',
    permission: 'cloudflare.permission',
    admin_host: 'cloudflare.admin_host',
    page_points_here: 'cloudflare.page_points_here',
    host_exists: 'cloudflare.host_exists',
  }
  return blocked ? (own(keys, blocked) ?? 'cloudflare.plan_blocked') : null
}

// Whether a plan can be confirmed: never a blocked one, and one on a host already serving traffic only once that is ticked
export function planConfirmable(plan, liveTicked) {
  return Boolean(plan && !plan.blocked && (!plan.live || liveTicked))
}

// The body of an apply: the fingerprint of the plan shown, and what was ticked for a host already serving traffic
export function applyBody(request, plan) {
  return { ...request, fingerprint: plan.fingerprint, confirm_live: Boolean(plan.live) }
}

// An address Cloudflare holds as anyone could have written it, shown as text: an invisible or bidirectional character could
// make it read as another address, so each one shows as its code instead
export function visibleUrl(value) {
  return String(value ?? '').replace(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\p{Cs}]/gu, (found) => `\\u{${found.codePointAt(0).toString(16)}}`)
}

// What a comparison found, all accounts together
export function gapCount(compare) {
  return (compare?.accounts ?? []).reduce((sum, account) => sum + account.missing.length + account.differs.length + account.extra.length, 0)
}

// What a comparison starts with: every push ticked, no removal ticked
export function defaultTicks(compare) {
  const push = new Set()
  for (const account of compare?.accounts ?? []) {
    for (const id of account.missing) push.add(id)
    for (const row of account.differs) push.add(row.id)
  }
  return { push, remove: new Set() }
}

// The body of Compare's fixes: the count of removals is the second confirmation the server checks
export function resyncBody(compare, ticks) {
  const remove = [...ticks.remove]
  return { fingerprint: compare.fingerprint, push: [...ticks.push], remove, confirm_remove: remove.length }
}

// The accounts with a list, for the quota chips: only those hold items
export function accountsWithList(accounts) {
  return (accounts ?? []).filter((account) => account.list)
}

// The quota chips: none while Cloudflare refuses the token, as nothing is synced and the counts are an old reading
export function quotaChipAccounts(state) {
  return state?.token?.state === 'invalid' ? [] : accountsWithList(state?.accounts)
}

// What a refusal says: its code with its values, or a generic line when something in front answered with no code
export function refusalText(error) {
  if (typeof error?.code === 'string') return { key: error.code, params: error.params ?? {} }
  return { key: 'cloudflare.no_answer', params: {} }
}

// --- A link's address, in the Redirect pages --------------------------------------------------------------------------

// Whether a change of address, or of a link's slug (its path on the host), stops a Cloudflare address: what was printed
// or shared with it stops working, so the page asks first and the server wants `confirm_break`
export function breaksAddress(link, address, slug) {
  if (!link || !link.address || link.address === 'lan') return false
  return address !== link.address || (slug !== undefined && slug !== link.slug)
}

// The addresses a form offers: the LAN and the hosts, or nothing while there is no host to choose
export function addressChoices(addresses) {
  return Array.isArray(addresses) && addresses.length > 1 ? addresses : null
}
