// Source: Moonie Redirect 7.0.1 admin UI, ui/shell.js, trimmed: bootstrap, plugins, zones, languages,
// banners, setup and login pages (the login is a server page here), page style sheets and module loading (the four
// pages are imported once). Added: one table from the action names of 7.0.1 and its Cloudflare plugin to this app's routes, the
// Settings page (7.0.1's instance, webhook and keys pages, and the Cloudflare plugin's settings and page), the old
// Cloudflare page's address, which opens its tab of Settings (D29), and the sidebar's foot: Settings and Log out as
// glyphs, in place of the menu's settings section and the Log out button, the Settings page headed by its title alone
// (D30).
// The shell: routes, frame and page states.

import { errorMark, glyphNode, iconNode } from './icons.js'
import { createKit, dismissDialogs, h } from './kit.js'
import { HOME, loginUrl, makeT, request, requestLine, safeNext } from './lib.js'
import { byCount } from './common.js'
import links from './links.js'
import nanourls from './nanourls.js'
import qrcodes from './qrcodes.js'
import settings from './settings.js'
import { tabAddress } from './settings-logic.js'
import strings from './en.json' with { type: 'json' }

const SKELETON_BARS = [1, 2, 3, 4, 5]
const STATUS_TEXTS = ['redirect.status_none', 'redirect.status_one', 'redirect.status_many']

// The menu: 7.0.1's REDIRECT section. Each item is an address, its text, its glyph and its page.
export const NAV = [
  {
    label: 'redirect.name',
    items: [
      { path: '/admin/links', label: 'redirect.page_links', icon: 'links', page: links },
      { path: '/admin/nanourls', label: 'redirect.page_nanourls', icon: 'page', page: nanourls },
      { path: '/admin/qrcodes', label: 'redirect.page_qrcodes', icon: 'page', page: qrcodes },
    ],
  },
]

// The sidebar's foot: Settings as a glyph, beside the template's Log out. It has no label: its page shows no eyebrow
// above its title.
export const FOOT = {
  label: null,
  items: [{ path: '/admin/settings', label: 'settings.page', glyph: 'settings', page: settings }],
}

// What a 7.0.1 page asks for, as this app's route, and what that answer becomes for the page. `kind` is the kind of row
// the action is about: the server answers a path someone else holds as slug_taken, which a page without a slug field shows
// under the name. `method` is the verb an action needs when its body alone would not say it.
const ACTIONS = {
  'links.list': { path: () => '/api/links', query: { kind: 'link' }, shape: (answer) => ({ links: answer?.links, addresses: answer?.addresses }) },
  'nanourls.list': { path: () => '/api/links', query: { kind: 'nano' }, shape: (answer) => ({ nanourls: answer?.links, addresses: answer?.addresses }) },
  'qrcodes.list': { path: () => '/api/links', query: { kind: 'qrcode' }, shape: (answer) => ({ qrcodes: answer?.links, addresses: answer?.addresses }) },
  'links.suggest': { path: () => '/api/links/suggest', query: { kind: 'link' } },
  'links.create': { path: () => '/api/links', body: { kind: 'link' }, taken: 'slug' },
  'nanourls.create': { path: () => '/api/links', body: { kind: 'nano' }, taken: 'name' },
  'qrcodes.create': { path: () => '/api/links', body: { kind: 'qrcode' }, taken: 'name' },
  'links.update': { path: (id) => `/api/links/${encodeURIComponent(id)}`, taken: 'slug' },
  'nanourls.update': { path: (id) => `/api/links/${encodeURIComponent(id)}`, taken: 'name' },
  'qrcodes.update': { path: (id) => `/api/links/${encodeURIComponent(id)}`, taken: 'name' },
  'links.delete': { path: (id) => `/api/links/${encodeURIComponent(id)}` },
  'nanourls.delete': { path: (id) => `/api/links/${encodeURIComponent(id)}` },
  'qrcodes.delete': { path: (id) => `/api/links/${encodeURIComponent(id)}` },
  'qrcodes.preview': { path: () => '/api/qrcodes/preview' },
  'cf.state': { path: () => '/api/cloudflare' },
  'sync.now': { path: () => '/api/cloudflare/sync' },
  'resync.compare': { path: () => '/api/cloudflare/compare' },
  'resync.apply': { path: () => '/api/cloudflare/compare/apply' },
  'zones.list': { path: () => '/api/cloudflare/zones' },
  'dns.proposals': { path: () => '/api/cloudflare/proposals' },
  'dns.plan': { path: () => '/api/cloudflare/plan' },
  'dns.apply': { path: () => '/api/cloudflare/apply' },
  'hosts.fallback': { path: (host) => `/api/cloudflare/hosts/${encodeURIComponent(host)}/fallback` },
  'admin.security': { path: () => '/api/settings/security' },
  'admin.password': { path: () => '/api/settings/password', method: 'POST' },
  'admin.sessions_end': { path: () => '/api/settings/sessions/end', method: 'POST' },
  'admin.keys': { path: () => '/api/settings/keys' },
  'admin.key_create': { path: () => '/api/settings/keys', method: 'POST' },
  'admin.key_revoke': { path: (id) => `/api/settings/keys/${encodeURIComponent(id)}`, method: 'DELETE' },
  'admin.webhook': { path: () => '/api/settings/webhook' },
  'admin.webhook_save': { path: () => '/api/settings/webhook', method: 'PUT' },
  'admin.webhook_delete': { path: () => '/api/settings/webhook', method: 'DELETE' },
  'admin.webhook_test': { path: () => '/api/settings/webhook/test', method: 'POST' },
  'admin.cloudflare': { path: () => '/api/settings/cloudflare' },
  'admin.cf_token_set': { path: () => '/api/settings/cloudflare/token', method: 'PUT' },
  'admin.cf_token_clear': { path: () => '/api/settings/cloudflare/token', method: 'DELETE' },
  'admin.cf_item_limit': { path: () => '/api/settings/cloudflare/item-limit', method: 'PUT' },
}

// One action, through `call` (the shell's request, with the session's ways to renew its token). Throws what `call` throws,
// a taken path placed under its field.
export async function callAction(call, action, { method, query: params, json, id, signal } = {}) {
  if (!Object.hasOwn(ACTIONS, action)) throw new Error(`unknown action ${action}`)
  const route = ACTIONS[action]
  const body = json === undefined ? undefined : { ...json, ...route.body }
  try {
    const answer = await call(route.path(id), { method: method ?? route.method, query: { ...route.query, ...params }, json: body, signal })
    return route.shape ? route.shape(answer) : answer
  } catch (error) {
    throw placeTaken(error, route.taken)
  }
}

const TAKEN = { slug: 'redirect.slug_taken', name: 'redirect.name_taken' }

// A refusal of a path someone else holds, under the field that makes the path. A path taken on a Cloudflare host is said
// under the address, where the server put it.
export function placeTaken(error, field) {
  if (!field || error?.code !== 'redirect.slug_taken' || error.fields?.address) return error
  return { ...error, fields: { [field]: TAKEN[field] } }
}

// Addresses that moved, and the tab of Settings each now is. A bookmark the server has not sent on yet (a page kept in
// the history) reaches it here: its other flags stay.
const MOVED = { '/admin/cloudflare': 'cloudflare' }

// Where an address that moved now is, or null
export function movedTo(path, search) {
  return Object.hasOwn(MOVED, path) ? tabAddress(search, MOVED[path]) : null
}

// Which item of the menu an address is, or null
export function findRoute(path) {
  for (const section of [...NAV, FOOT]) {
    const item = section.items.find((entry) => entry.path === path)
    if (item) return { section, item }
  }
  return null
}

// The frame's status, from the count of every kind
export function statusText(t, count) {
  if (!Number.isInteger(count)) return t('redirect.status_running')
  return t(byCount(count, ...STATUS_TEXTS), { count: String(count) })
}

// Only the browser runs what follows
if (typeof document !== 'undefined') start()

function start() {
  const $ = (id) => document.getElementById(id)
  const t = (key, params) => makeT(strings, { showKeys: query().get('keys') === '1' })(key, params)
  const kit = createKit(t)
  const state = {
    generation: 0, // changes on every navigation: older results are stale
    controller: null,
    cleanups: [], // the page's, run on leaving
    address: null, // the address the page on screen belongs to, fragment left out
    count: null, // the last count of links the status said
  }

  function currentUrl() {
    return `${location.pathname}${location.search}`
  }

  function query() {
    return new URLSearchParams(location.search)
  }

  // --- Calls ------------------------------------------------------------------------------------------------------

  // The login is a page of the server: the whole document goes there, with this address to come back to
  function goToLogin() {
    location.assign(loginUrl(currentUrl(), { expired: true }))
  }

  // The session's token, read afresh into the meta and the logout form: a login in another tab replaced it
  async function renewToken() {
    const answer = await request('/api/session', { onExpired: goToLogin })
    if (typeof answer?.csrf !== 'string' || !answer.csrf) return false
    document.querySelector('meta[name="csrf-token"]')?.setAttribute('content', answer.csrf)
    for (const field of document.querySelectorAll('input[name="csrf"]')) field.value = answer.csrf
    return true
  }

  function call(path, options = {}) {
    return request(path, { ...options, onExpired: goToLogin, renewToken })
  }

  function api(action, options) {
    return callAction(call, action, options)
  }

  // --- Frame ------------------------------------------------------------------------------------------------------

  function renderNav(active) {
    const holder = $('nav-sections')
    // The links are rebuilt: the one holding the focus must not drop it to <body>
    const focused = holder.contains(document.activeElement) ? document.activeElement.getAttribute('href') : null
    holder.replaceChildren(
      ...NAV.map((section) =>
        h(
          'div',
          { class: 'nav-section' },
          h('span', { class: 'label nav-section-label' }, t(section.label)),
          section.items.map((item) =>
            h(
              'a',
              { class: 'nav-item', href: item.path, 'aria-current': item.path === active ? 'page' : null },
              iconNode(item.icon),
              h('span', {}, t(item.label)),
            ),
          ),
        ),
      ),
    )
    if (focused !== null) {
      const same = [...holder.querySelectorAll('.nav-item')].find((item) => item.getAttribute('href') === focused)
      ;(same ?? $('page')).focus({ preventScroll: true })
    }
    renderFoot(active)
  }

  // The foot's links are drawn once and kept, so the one holding the focus keeps it; only their state changes
  function renderFoot(active) {
    const holder = $('nav-foot-links')
    if (!holder.hasChildNodes()) {
      const links = FOOT.items.map((item) => h('a', { class: 'nav-icon', href: item.path }, glyphNode(item.glyph)))
      holder.replaceChildren(...links)
    }
    FOOT.items.forEach((item, index) => {
      const link = holder.children[index]
      link.setAttribute('aria-label', t(item.label))
      link.setAttribute('title', t(item.label))
      if (item.path === active) link.setAttribute('aria-current', 'page')
      else link.removeAttribute('aria-current')
    })
  }

  function renderStatus(count) {
    $('status').replaceChildren(h('span', { class: 'dot dot-success' }), statusText(t, count))
  }

  function renderFrame(route, count) {
    renderNav(route?.item.path)
    renderStatus(count)
    $('reload').replaceChildren(iconNode('reload', 16), t('common.reload'))
    const name = t('redirect.app_name')
    if (route) setHeading(route.section.label ? t(route.section.label) : '', t(route.item.label), name)
    else setHeading(t('notfound.code'), t('notfound.title'), name)
  }

  function setHeading(section, title, appName) {
    $('page-section').textContent = section
    $('page-title').textContent = title
    document.title = title ? `${title} · ${appName}` : appName
  }

  // --- Page states ------------------------------------------------------------------------------------------------

  function show(name, ...children) {
    const main = $('page')
    const active = document.activeElement
    const holdsFocus = active !== main && main.contains(active)
    main.dataset.state = name
    main.replaceChildren(...children)
    // What held the focus is gone: it stays with the page rather than falling to <body>
    if (holdsFocus) main.focus({ preventScroll: true })
  }

  function showLoading() {
    const bars = () => SKELETON_BARS.map((bar) => h('div', { class: `skeleton-bar skeleton-${bar}` }))
    show(
      'loading',
      h(
        'section',
        { class: 'card state-loading', 'aria-busy': 'true' },
        h('span', { class: 'label state-loading-label' }, t('common.loading')),
        bars(),
      ),
      h('section', { class: 'card state-loading', 'aria-hidden': 'true' }, bars()),
    )
  }

  function showError(error, retry) {
    const mark = errorMark()
    mark.classList.add('state-error-mark')
    const line = requestLine(error, t)
    show(
      'error',
      h(
        'section',
        { class: 'card state-card', role: 'alert' },
        mark,
        h('h2', { class: 'state-title' }, t('state.error_title')),
        h('p', { class: 'state-desc' }, t('state.error_desc')),
        line && h('span', { class: 'code state-request' }, line),
        h('button', { class: 'btn state-retry', type: 'button', onclick: retry }, t('common.retry')),
      ),
    )
  }

  function showNotFound() {
    show(
      'not-found',
      h(
        'section',
        { class: 'card state-card' },
        h('span', { class: 'state-hero' }, '404'),
        h('h2', { class: 'state-title' }, t('notfound.title')),
        h('p', { class: 'state-desc' }, t('notfound.desc')),
        h('span', { class: 'code state-path' }, safeDecode(location.pathname)),
        h('a', { class: 'btn btn-accent', href: HOME }, t('notfound.home')),
      ),
    )
  }

  // Text only: it reaches the page through a text node, whatever the address holds
  function safeDecode(path) {
    try {
      return decodeURI(path)
    } catch {
      return path
    }
  }

  // --- Pages ------------------------------------------------------------------------------------------------------

  function makeContext(generation, signal) {
    const stale = () => generation !== state.generation
    return {
      query: query(),
      t,
      api: (action, options = {}) => api(action, { ...options, signal }),
      // The page moves the address without leaving. The shell has to know, or Back would find nothing to do.
      address(path, { push = false } = {}) {
        if (stale() || !safeNext(path)) return
        if (push) history.pushState(null, '', path)
        else history.replaceState(null, '', path)
        state.address = currentUrl()
      },
      navigate(path) {
        if (!stale()) navigate(path)
      },
      reload: () => (stale() ? undefined : route()),
      ui: { ...kit, confirm: (options) => (stale() ? Promise.resolve(false) : kit.confirm(options)) },
    }
  }

  async function runPage(page, generation, signal) {
    const stale = () => generation !== state.generation
    const ctx = makeContext(generation, signal)
    try {
      const data = await page.load(ctx)
      if (stale()) return
      const host = h('div', { class: 'page-host' })
      show('loaded', host)
      const cleanup = page.render(host, data, ctx)
      if (typeof cleanup !== 'function') return
      // Render navigated away: the leave that should have run this has already happened
      if (stale()) runCleanup(cleanup)
      else state.cleanups.push(cleanup)
    } catch (error) {
      if (stale() || error?.name === 'AbortError') return
      if (error?.status === undefined) console.error(error)
      showError(error, () => route())
    }
  }

  // --- Routes -----------------------------------------------------------------------------------------------------

  function runCleanup(cleanup) {
    try {
      cleanup()
    } catch (error) {
      console.error(error)
    }
  }

  function leavePage() {
    state.generation += 1
    state.controller?.abort()
    state.controller = new AbortController()
    dismissDialogs()
    state.cleanups.splice(0).forEach(runCleanup)
    return { generation: state.generation, signal: state.controller.signal }
  }

  // The count of every kind, for the status. A status that cannot be read says the app runs, as 7.0.1 did with no count.
  async function readCount(signal) {
    try {
      const answer = await call('/api/status', { signal })
      return answer?.links
    } catch (error) {
      if (error?.name === 'AbortError') throw error
      return null
    }
  }

  async function route() {
    // In place of the old address, which Back must not find again
    const moved = movedTo(location.pathname, location.search)
    if (moved) history.replaceState(null, '', moved)
    state.address = currentUrl()
    const { generation, signal } = leavePage()
    const stale = () => generation !== state.generation
    const target = findRoute(location.pathname)
    // The old page goes at once, while the frame is read again
    showLoading()
    renderFrame(target, state.count)
    try {
      state.count = await readCount(signal)
    } catch {
      return
    }
    if (stale()) return
    renderFrame(target, state.count)
    if (!target) showNotFound()
    else await runPage(target.item.page, generation, signal)
  }

  function sameAddress(path) {
    return new URL(path, location.href).href === location.href
  }

  function navigate(path) {
    if (!safeNext(path)) return
    // The page's own link reads it again: an entry for the same address would make Back do nothing
    if (!sameAddress(path)) history.pushState(null, '', path)
    route()
  }

  // --- Frame controls ---------------------------------------------------------------------------------------------

  function isPlainClick(event) {
    return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey
  }

  function onClick(event) {
    const link = event.target instanceof Element ? event.target.closest('a[href]') : null
    if (!link || event.defaultPrevented || !isPlainClick(event) || link.target || link.hasAttribute('download')) return
    const path = link.getAttribute('href')
    if (!safeNext(path)) return
    // A place in this page is the browser's to scroll to
    const url = new URL(link.href)
    if (url.hash && `${url.pathname}${url.search}` === currentUrl()) return
    event.preventDefault()
    navigate(path)
  }

  document.addEventListener('click', onClick)
  // Moving between places of one page fires popstate too, and the page stays
  window.addEventListener('popstate', () => {
    if (currentUrl() !== state.address) route()
  })
  $('reload').addEventListener('click', () => route())
  $('logout').replaceChildren(glyphNode('logout'))
  route()
}
