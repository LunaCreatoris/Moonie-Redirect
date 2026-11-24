// Source: Moonie Redirect 7.0.1 admin UI, ui/lib.js, trimmed: languages, times, ages, sizes, plugin routes,
// bootstrap, typed values kept across a redraw, forms (the pages have their own). Added: the CSRF header and the reading
// of this app's error answers, the Cloudflare and Settings ones included. Pure front logic: nothing runs on import.

// --- Texts ------------------------------------------------------------------------------------------------------

// One pass, so a value holding {name} stays as it is. Values are only ever inserted as text.
export function interpolate(text, params = {}) {
  return text.replace(/\{(\w+)\}/g, (match, name) => (Object.hasOwn(params, name) ? String(params[name]) : match))
}

// `t(key, params)` over a strings table. A missing key shows the key itself; `showKeys` shows every key.
export function makeT(strings, { showKeys = false } = {}) {
  return (key, params = {}) => {
    if (showKeys || !Object.hasOwn(strings, key)) return key
    return interpolate(strings[key], params)
  }
}

// --- Addresses --------------------------------------------------------------------------------------------------

export const HOME = '/admin/links'
const ADMIN = '/admin/'
const LOGIN = '/login'

// The path the browser makes of an address: dots, encoded dots and backslashes are resolved, query and fragment dropped
function resolvedPath(address) {
  return new URL(address, 'file:').pathname
}

// An address of the admin pages, and nothing a browser would read as another place
export function safeNext(next) {
  if (typeof next !== 'string' || !next.startsWith(ADMIN) || next.startsWith('//')) return false
  return resolvedPath(next).startsWith(ADMIN)
}

// The login address from the current one. No `next` when there is nothing to come back to.
export function loginUrl(current, flags = {}) {
  const params = new URLSearchParams()
  if (flags.expired) params.set('expired', '1')
  const path = current.split(/[?#]/, 1)[0]
  if (path !== HOME && safeNext(current)) params.set('next', current)
  const query = params.toString()
  return query ? `${LOGIN}?${query}` : LOGIN
}

// --- API --------------------------------------------------------------------------------------------------------

export const NO_RESPONSE = 0

// This app's error words, as the kit's codes. A word not listed stays as it is: no text has it, so the page says the
// instance did not answer, as for something in front of it.
const ERROR_CODES = {
  unauthorized: 'errors.unauthorized',
  not_found: 'errors.not_found',
  csrf: 'errors.csrf',
  slug_taken: 'redirect.slug_taken',
  design_unreadable: 'redirect.design_unreadable',
  quota_full: 'redirect.quota_full',
  cloudflare_off: 'redirect.cloudflare_off',
  confirm_break: 'redirect.confirm_break',
  needs_admin: 'cloudflare.needs_admin',
  scope_denied: 'errors.scope_denied',
  too_many_attempts: 'errors.too_many_attempts',
  plan_stale: 'cloudflare.plan_stale',
  busy: 'cloudflare.busy',
  confirm_live: 'cloudflare.confirm_live',
  remote_changed: 'cloudflare.remote_changed',
  rate_limited: 'cloudflare.rate_limited',
  unreachable: 'cloudflare.unreachable',
  token_invalid: 'cloudflare.token_invalid',
  permission: 'cloudflare.permission',
  refused: 'cloudflare.refused',
  internal: 'cloudflare.internal',
  conflict: 'cloudflare.conflict',
  lists_full: 'cloudflare.lists_full',
  rules_full: 'cloudflare.rules_full',
  admin_host: 'cloudflare.admin_host',
  page_points_here: 'cloudflare.page_points_here',
  host_exists: 'cloudflare.host_exists',
  login_failed: 'errors.login_failed',
  not_configured: 'webhook.test_not_configured',
  url_closed: 'webhook.field_url_closed',
  secret_required: 'webhook.field_secret_required',
}

// What the server says of a field, in its own English words, as the key of the 7.0.1 text for that refusal. The first
// rule whose words start the message wins; a message no rule knows shows as `redirect.value_invalid`.
const FIELD_TEXTS = {
  slug: [
    ['required', 'redirect.slug_required'],
    ['at most', 'redirect.slug_too_long'],
    ['starts with a reserved', 'redirect.slug_reserved'],
    ['no empty segment', 'redirect.slug_empty_segment'],
    ["no '.' or '..' segment", 'redirect.slug_dot_segment'],
    ['letters, digits', 'redirect.slug_invalid'],
  ],
  name: [
    ['required', 'redirect.name_required'],
    ['at most', 'redirect.name_too_long'],
    ['holds control', 'redirect.name_invalid'],
    ['makes no usable path', 'redirect.name_unusable'],
  ],
  target: [
    ['required', 'redirect.target_required'],
    ['at most', 'redirect.target_too_long'],
    ['', 'redirect.target_invalid'],
  ],
  address: [
    ['not a host set up here', 'redirect.address_unknown'],
    ['.well-known', 'redirect.address_well_known'],
    ['this path is taken', 'redirect.address_taken'],
    ["this instance's own host", 'redirect.address_admin_host'],
    ['', 'redirect.address_invalid'],
  ],
  label: [['', 'cloudflare.label_invalid']],
  fallback: [
    ['page_loop', 'cloudflare.fallback_loop'],
    ['admin_host', 'cloudflare.admin_host'],
    ['', 'cloudflare.fallback_invalid'],
  ],
  expires_on: [['', 'redirect.expires_on_invalid']],
  password: [
    ['required', 'settings.field_required'],
    ['', 'errors.login_failed'],
  ],
  new_password: [['', 'settings.password_length']],
  scopes: [
    ['required', 'settings.field_required'],
    ['', 'keys.field_scopes_invalid'],
  ],
  url: [
    ['url_closed', 'webhook.field_url_closed'],
    ['', 'webhook.field_url'],
  ],
  secret: [
    ['secret_required', 'webhook.field_secret_required'],
    ['', 'webhook.field_secret'],
  ],
  events: [['', 'webhook.field_events']],
  token: [
    ['required', 'settings.field_required'],
    ['', 'settings.cf_token_invalid'],
  ],
  value: [['', 'settings.cf_limit_invalid']],
  design: [
    ['logo is at most', 'redirect.design_logo_size'],
    ['logo is a', 'redirect.design_logo'],
    ['colours need a contrast', 'redirect.design_contrast'],
    ['color must be', 'redirect.design_color'],
    ['eye_color must be', 'redirect.design_color'],
    ['background must be', 'redirect.design_color'],
  ],
}

export function fieldCode(field, message) {
  if (typeof message !== 'string') return 'redirect.value_invalid'
  const rules = Object.hasOwn(FIELD_TEXTS, field) ? FIELD_TEXTS[field] : []
  const found = rules.find(([start]) => message.startsWith(start))
  return found ? found[1] : 'redirect.value_invalid'
}

// The kit's failure from this app's answer: `{error, fields: {name: message}}`
export function apiError(method, path, status, body) {
  const word = typeof body?.error === 'string' ? body.error : null
  const fields = {}
  if (body?.fields && typeof body.fields === 'object') {
    for (const [name, message] of Object.entries(body.fields)) fields[name] = fieldCode(name, message)
  }
  return {
    method,
    path,
    status,
    code: word === null ? null : (ERROR_CODES[word] ?? word),
    params: {},
    fields,
  }
}

// Only this code says the session is gone. Any other 401 is an answer like any other.
export function sessionGone(error) {
  return error?.status === 401 && error.code === 'errors.unauthorized'
}

// What the page sends a change with: the session's token, which the server compares with the cookie's
export function csrfToken(doc = globalThis.document) {
  return doc?.querySelector?.('meta[name="csrf-token"]')?.getAttribute('content') ?? ''
}

const SAFE_METHODS = ['GET', 'HEAD']

// One call. Throws {method, path, status, code, params, fields}; status 0 means no answer came.
// A 401 that means the session is gone calls `onExpired`. A 403 csrf calls `renewToken` and, when it says it took the
// session's token afresh, sends the call once more: from this page, that refusal means a login in another tab replaced
// the session and its token, and the refused call changed nothing.
export async function request(path, options = {}) {
  try {
    return await send(path, options)
  } catch (failure) {
    if (failure?.status !== 403 || failure.code !== 'errors.csrf' || !options.renewToken) throw failure
    let renewed = false
    try {
      renewed = await options.renewToken()
    } catch (error) {
      if (error?.name === 'AbortError') throw error
    }
    if (renewed !== true) throw failure
    return send(path, options)
  }
}

async function send(path, { method, query, json, signal, onExpired, fetcher = fetch, token = csrfToken } = {}) {
  const verb = method ?? (json === undefined ? 'GET' : 'POST')
  const search = new URLSearchParams()
  for (const [name, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) search.set(name, String(value))
  }
  const address = search.size ? `${path}?${search}` : path
  const headers = { Accept: 'application/json' }
  if (json !== undefined) headers['Content-Type'] = 'application/json'
  if (!SAFE_METHODS.includes(verb)) headers['X-CSRF-Token'] = token()
  let response
  try {
    response = await fetcher(address, {
      method: verb,
      signal,
      credentials: 'same-origin',
      headers,
      body: json === undefined ? undefined : JSON.stringify(json),
    })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw apiError(verb, path, NO_RESPONSE, null)
  }
  if (response.status === 204) return null
  let body = null
  try {
    body = await response.json()
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    body = null
  }
  if (response.ok) return body
  const failure = apiError(verb, path, response.status, body)
  if (sessionGone(failure)) onExpired?.(failure)
  throw failure
}

// The error state's line: METHOD path → status
export function requestLine(error, t) {
  if (!error || !error.method || !error.path) return null
  const answer = error.status === NO_RESPONSE ? t('state.no_response') : error.status
  return `${error.method} ${error.path} → ${answer}`
}

// --- Copy -------------------------------------------------------------------------------------------------------

// `from` is the control asking. A modal makes everything outside it inert, where the helper could hold no selection.
export async function copyText(text, from) {
  const focused = document.activeElement
  // The Clipboard API only exists in secure contexts; a LAN tool is usually plain http://
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // fall back below
    }
  }
  const helper = document.createElement('textarea')
  helper.value = text
  helper.setAttribute('readonly', '')
  helper.className = 'clipboard-helper'
  ;(from?.closest('dialog[open]') ?? document.body).append(helper)
  helper.select()
  let copied = false
  try {
    copied = document.execCommand('copy')
  } catch {
    copied = false
  }
  helper.remove()
  // The helper took the focus with it: give it back to whoever had it
  focused?.focus?.({ preventScroll: true })
  return copied
}
