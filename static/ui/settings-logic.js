// Source: Moonie Redirect 7.0.1 admin UI, ui/pages/keys.js, webhook.js, instance.js and plugins.js, their
// pure parts: scopesIn, suggestions, isSuccess, statusText, the event rows and credentialView. Added: the tab in the
// address, where a value comes from, the checks a form makes before it calls, and the readers of the settings answers.
// What the Settings page decides, with no document, so that node tests it (tests/js).

import { stateReadable } from './cloudflare-logic.js'

// --- The page and its tabs --------------------------------------------------------------------------------------------

export const PAGE = '/admin/settings'
export const CONFIGURE_FLAG = 'configure'

// Each tab, its text, and what its load reads
export const TABS = [
  { id: 'security', label: 'settings.tab_security' },
  { id: 'webhook', label: 'settings.tab_webhook' },
  { id: 'cloudflare', label: 'settings.tab_cloudflare' },
]

const DEFAULT_TAB = 'security'

// The tab the address asks for. An address naming none, or one this page has not, reads as the first.
export function tabFrom(query) {
  const asked = query?.get?.('tab')
  return TABS.some((tab) => tab.id === asked) ? asked : DEFAULT_TAB
}

// The address of a tab. The other flags of the address stay (?keys=1), but the webhook's configure flag belongs to one
// visit of its tab.
export function tabAddress(search, tab, { configure = false } = {}) {
  const params = new URLSearchParams(search)
  params.set('tab', tab)
  params.delete(CONFIGURE_FLAG)
  if (configure) params.set(CONFIGURE_FLAG, '1')
  return `${PAGE}?${params}`
}

// --- Where a value comes from -----------------------------------------------------------------------------------------

// The chip of an origin. The database wins; a file or the environment is the fallback while it has none.
const ORIGINS = {
  stored: { text: 'settings.origin_stored', level: 'success' },
  file: { text: 'settings.origin_file', level: 'info' },
  env: { text: 'settings.origin_env', level: 'info' },
  default: { text: 'settings.origin_default' },
  missing: { text: 'settings.origin_missing' },
  unreadable: { text: 'settings.origin_unreadable', level: 'warning' },
}

export function originView(origin) {
  return typeof origin === 'string' && Object.hasOwn(ORIGINS, origin) ? ORIGINS[origin] : ORIGINS.missing
}

// What a credential's row shows, from its origin alone: the chip, the control beside it, and whether it can be cleared.
// Set here has Replace and Clear; from a file has Replace, since a value set here wins over the file; cannot be read has
// Replace and Clear; none has the form.
export function credentialView(origin) {
  const chip = originView(origin)
  if (origin === 'stored' || origin === 'unreadable') return { chip, control: 'replace', clear: true }
  if (origin === 'file') return { chip, control: 'replace', clear: false }
  return { chip, control: 'form', clear: false }
}

// Only a token the instance holds has a check to show
export function tokenChecked(origin) {
  return origin === 'stored' || origin === 'file'
}

// --- Checks before a call ---------------------------------------------------------------------------------------------

export const PASSWORD_MIN = 12
export const PASSWORD_MAX = 1024

function length(text) {
  return [...text].length
}

// The change of password: every field filled, the two new ones equal, the new one 12 to 1024 characters. The fields to
// refuse, or null.
export function passwordCheck({ password, new_password: next, new_password_confirm: confirm }) {
  const fields = {}
  if (!password) fields.password = 'settings.field_required'
  if (!next) fields.new_password = 'settings.field_required'
  else if (length(next) < PASSWORD_MIN || length(next) > PASSWORD_MAX) fields.new_password = 'settings.password_length'
  if (!confirm) fields.new_password_confirm = 'settings.field_required'
  else if (next && confirm !== next) fields.new_password_confirm = 'settings.password_mismatch'
  return Object.keys(fields).length ? fields : null
}

// A new key: a name, a scope at least, and the password
export function keyCheck({ name, scopes, password }) {
  const fields = {}
  if (!name.trim()) fields.name = 'settings.field_required'
  if (!scopes.length) fields.scopes = 'settings.field_required'
  if (!password) fields.password = 'settings.field_required'
  return Object.keys(fields).length ? fields : null
}

const WHOLE = /^[0-9]+$/

// The item limit as typed: empty goes back to the environment or the default, otherwise a whole number of 1 or more
export function limitValue(text) {
  const typed = String(text ?? '').trim()
  if (typed === '') return { value: null }
  if (!WHOLE.test(typed)) return { error: 'settings.cf_limit_invalid' }
  const value = Number(typed)
  if (!Number.isSafeInteger(value) || value < 1) return { error: 'settings.cf_limit_invalid' }
  return { value }
}

// --- Answers ----------------------------------------------------------------------------------------------------------

// A refusal whose code is about one field goes under that field, with the text this page has for it
export function placeCode(error, places) {
  const code = error?.code
  if (typeof code !== 'string' || !Object.hasOwn(places, code)) return error
  const { field, text } = places[code]
  return { ...error, fields: { [field]: text ?? code } }
}

// What each answer must hold for the page to draw it. Something in front may answer 200 with a page of its own.
export function readable(tab, data) {
  if (tab === 'security') return Boolean(data?.password && data.sessions)
  if (tab === 'webhook') {
    const { webhook, keys } = data ?? {}
    return Boolean(webhook && Array.isArray(webhook.available) && Array.isArray(webhook.events) && Array.isArray(keys?.keys))
  }
  if (tab === 'cloudflare') return cloudflareReadable(data?.settings) && stateReadable(data?.domains?.state) && Array.isArray(data.domains.hosts)
  return false
}

// The Cloudflare settings answer alone, as its token, clear and item limit calls answer it
export function cloudflareReadable(settings) {
  return Boolean(settings?.token && settings.item_limit)
}

// --- Webhook ----------------------------------------------------------------------------------------------------------

export function isSuccess(status) {
  return Number.isInteger(status) && status >= 200 && status < 300
}

export function statusText(status, t) {
  return Number.isInteger(status) ? t('webhook.http_status', { status }) : t('webhook.no_answer')
}

// The texts of the events this app sends, by name: 7.0.1's names, so that receivers written for 7.0.1 match
const EVENT_LABELS = {
  'redirect.link.created': 'webhook.event_link_created',
  'redirect.link.updated': 'webhook.event_link_updated',
  'redirect.link.deleted': 'webhook.event_link_deleted',
}

// The events the instance offers first, in its order; a subscription it no longer offers is kept after them, or a save
// would lose it. Each row: its name, its text (or the instance's own label), whether it is ticked and offered.
export function eventRows(available, events) {
  const offered = (Array.isArray(available) ? available : []).filter((event) => typeof event?.name === 'string')
  const ticked = (Array.isArray(events) ? events : []).filter((name) => typeof name === 'string')
  const names = offered.map((event) => event.name)
  const extra = [...new Set(ticked.filter((name) => !names.includes(name)))].sort()
  return [
    ...offered.map((event) => ({
      name: event.name,
      key: Object.hasOwn(EVENT_LABELS, event.name) ? EVENT_LABELS[event.name] : null,
      label: typeof event.label === 'string' ? event.label : event.name,
      checked: ticked.includes(event.name),
      offered: true,
    })),
    ...extra.map((name) => ({ name, key: 'webhook.event_undeclared', label: name, checked: true, offered: false })),
  ]
}

// What a save sends. An empty secret field keeps the stored secret.
export function webhookBody({ url, events, secret }) {
  const body = { url: String(url ?? '').trim(), events: [...events] }
  if (secret) body.secret = secret
  return body
}

// The last delivery, as 7.0.1 said it: {event, status, at, event_id, error}. A delivery row of the outbox reads the same.
export function deliveryView(last) {
  if (!last || typeof last !== 'object' || typeof last.event !== 'string') return null
  const status = Number.isInteger(last.status) ? last.status : Number.isInteger(last.last_status) ? last.last_status : null
  return {
    event: last.event,
    status,
    at: last.at ?? last.finished_at ?? last.created_at ?? null,
    id: last.event_id ?? last.id ?? null,
    error: last.error ?? last.last_error ?? null,
  }
}

// --- API keys ---------------------------------------------------------------------------------------------------------

export function scopesIn(text) {
  return String(text ?? '')
    .split(/[\s,]+/)
    .filter(Boolean)
}

// The instance's list in its own order (it names its wildcards beside the actions they cover). A wildcard it leaves out,
// everything or one per owner, comes first.
export function suggestions(known) {
  const scopes = (Array.isArray(known) ? known : []).filter((scope) => typeof scope === 'string')
  // A wildcard the instance lists is no owner of its own
  const owners = [...new Set(scopes.filter((scope) => scope.includes(':')).map((scope) => scope.split(':', 1)[0]))].filter((owner) => owner && owner !== '*')
  const wildcards = ['*', ...owners.map((owner) => `${owner}:*`)].filter((wildcard) => !scopes.includes(wildcard))
  return [...new Set([...wildcards, ...scopes])]
}

// A scope chip pressed adds the scope, pressed again removes it
export function toggleScope(text, scope) {
  const current = scopesIn(text)
  const next = current.includes(scope) ? current.filter((entry) => entry !== scope) : [...current, scope]
  return next.join(', ')
}

// The token file first, as a fixed row with no Revoke, then the keys made here in the instance's order
export function keyRows(keys) {
  const rows = (Array.isArray(keys) ? keys : []).filter((key) => key && typeof key.id === 'string')
  const file = rows.filter((key) => key.origin === 'file').map((key) => ({ ...key, fixed: true }))
  const stored = rows.filter((key) => key.origin !== 'file').map((key) => ({ ...key, fixed: false }))
  return [...file, ...stored]
}
