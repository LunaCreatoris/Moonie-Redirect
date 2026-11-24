// Source: Moonie Redirect 7.0.1 admin UI, system/redirect/ui/common.js, trimmed: zones, the link address (IP or public URL),
// optimistic concurrency, drafts kept across a login. Added: a link's Cloudflare address, at the end. What the pages
// share. The first part is pure, and tested under node. The second draws on the kit.

import { addressChoices, breaksAddress, errorText, linkStateView } from './cloudflare-logic.js'

// --- Pure -----------------------------------------------------------------------------------------------------------

// YYYY-MM-DD HH:mm:ss in the browser's zone, as the base's contract has every time. A value that is no time shows as it came.
export function formatTime(value) {
  const date = new Date(value)
  if (value === null || value === undefined || Number.isNaN(date.getTime())) return value ?? ''
  const pad = (number, width = 2) => String(number).padStart(width, '0')
  const day = `${pad(date.getFullYear(), 4)}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  return `${day} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

// One form of a text for a search: any case, and an accent however it is encoded, as a macOS file name decomposes it
function searchForm(text) {
  return text.normalize('NFC').toLowerCase()
}

// Whether a link answers a search on these fields. An empty search keeps everything.
export function matchesSearch(link, search, fields = ['name', 'slug', 'target', 'public_url']) {
  const needle = searchForm(search.trim())
  if (!needle) return true
  return fields.some((field) => {
    const value = link[field]
    return typeof value === 'string' && searchForm(value).includes(needle)
  })
}

// Whether a row answers a search on the fields of `heldBy`, which gives for each field what it holds on every row. A search
// that is all part of such a text tells no row from another, so that field does not answer it.
export function matchesTelling(row, search, heldBy) {
  const needle = searchForm(search.trim())
  const telling = Object.keys(heldBy).filter((field) => !heldBy[field].some((held) => searchForm(held).includes(needle)))
  return matchesSearch(row, search, telling)
}

// An address of this page with other parameters: null removes one. The rest of the query stays, debug flags included.
export function addressWith(path, query, changes) {
  const next = new URLSearchParams(query)
  for (const [name, value] of Object.entries(changes)) {
    if (value === null) next.delete(name)
    else next.set(name, value)
  }
  const text = next.toString()
  return text ? `${path}?${text}` : path
}

// Something in front of the instance may answer 200 with its own page, which comes as null: that saved nothing
export function savedLink(answer) {
  if (typeof answer?.id !== 'string') throw { status: 200, code: null, params: {}, fields: {} }
  return answer
}

// What a call that said nothing readable counts as, for what a form then says
const NOT_ANSWERED = { status: 200, code: null, params: {}, fields: {} }

// A delete answers 204, which a page gets as null. A 200 with the page of something in front comes as null too and deleted
// nothing, so only the list can say whether the row went. `call` deletes, `listRows` answers the rows.
export async function deletedForGood(call, listRows, id) {
  if ((await call()) !== null) throw NOT_ANSWERED
  const rows = await listRows()
  if (!Array.isArray(rows) || rows.some((row) => row?.id === id)) throw NOT_ANSWERED
}

// Whether a call failed because the page is leaving or the login page has replaced it, so there is nothing to tell
export function isLeaving(error) {
  return error?.name === 'AbortError' || (error?.status === 401 && error.code === 'errors.unauthorized')
}

// Whether the instance itself says that the row is gone. Something in front of it may answer 404 with its own page, which
// says nothing of the row and must leave the form and what was typed.
export function isGone(error) {
  return error?.status === 404 && error.code === 'errors.not_found'
}

// --- What a reload keeps ----------------------------------------------------------------------------------------------

// A reload runs the page anew, the only way to read the frame's status again, and the module stays. What a page wants its
// next draw to know waits here, and is read once.
// It belongs to the page that kept it: another page reached before that draw drops it and shows nothing of it.
let kept = null

const pagePath = () => globalThis.location?.pathname

export function keepForNextDraw(value) {
  kept = { path: pagePath(), value }
}

export function takeKept() {
  const held = kept
  kept = null
  return held && held.path === pagePath() ? held.value : null
}

// What a page's form was on when the page ran again at the same address, for the draw that follows. Memory only, as the
// shell's own. Each page has its own.
export function pageMemory() {
  let shown = null
  return {
    takeShown(address) {
      const held = shown
      shown = null
      return held?.address === address ? held : null
    },
    // The page is being left, from a form at `address`. The shell has already moved: at the same address the page runs again.
    leaving(held) {
      if (`${location.pathname}${location.search}` === held.address) shown = held
    },
  }
}

// Whether a draw opens the form of a new one: the address asks for it, or the form this draw comes back to at the same
// address was one. An empty list opens that form on the bare address, so the address alone cannot say it, and
// a row another tab added since would take the form, with the draft of the new one poured onto it.
export function drawsNew(asked, before) {
  return asked === true || before?.isNew === true
}

// --- Forms ------------------------------------------------------------------------------------------------------------

// A form's own properties give way to a field of the same name, and a contribution names its fields as it likes: only
// these reach the form itself, whatever it holds.
function inForm(form, selector) {
  return [...Element.prototype.querySelectorAll.call(form, selector)]
}

export function clearFormErrors(form) {
  for (const control of inForm(form, 'input, select, textarea, button, fieldset')) control.removeAttribute('aria-invalid')
  for (const slot of inForm(form, '.field-error, .form-error')) {
    slot.textContent = ''
    slot.hidden = true
  }
}

// The line at the form's top alone: what a field was refused for stays until the next save
export function clearFormTop(form) {
  const slot = inForm(form, '.form-error')[0]
  slot.textContent = ''
  slot.hidden = true
}

const NO_RESPONSE_KEY = 'state.form_no_response'

// What a code from an answer says. Something in front may answer with a code of its own, which is no text of this instance and
// comes back from `t` as it is: that is a failed call. With `?keys=1` every key comes back as it is, on purpose.
export function spokenCode(t, code, params) {
  if (typeof code !== 'string') return t(NO_RESPONSE_KEY)
  const said = t(code, params)
  return said === code && t(NO_RESPONSE_KEY) !== NO_RESPONSE_KEY ? t(NO_RESPONSE_KEY) : said
}

// Under its field when the answer names one this form has, otherwise at the form's top
export function showFormError(form, error, t) {
  const refused = []
  for (const [name, code] of Object.entries(error.fields ?? {})) {
    const input = inForm(form, `[name="${CSS.escape(name)}"]`)[0]
    const slot = input?.closest('.field')?.querySelector('.field-error')
    if (!slot) continue
    input.setAttribute('aria-invalid', 'true')
    slot.textContent = spokenCode(t, code)
    slot.hidden = false
    refused.push(input)
  }
  if (refused.length) {
    // The first one on the screen, whatever order the answer gave them in
    inForm(form, '[name]').find((control) => refused.includes(control)).focus()
    return
  }
  const slot = inForm(form, '.form-error')[0]
  slot.textContent = spokenCode(t, error.code ?? NO_RESPONSE_KEY, error.params)
  slot.hidden = false
  // A form can be taller than the window, and this line stands at its top, far from the Save just pressed
  slot.scrollIntoView({ block: 'nearest' })
}

const submittingForms = new WeakSet()

// Runs a form's action. Its submit button waits, old errors go, and what the instance refused goes on the form. A form that
// holds another submit button says which one is its own, and a press on any of them starts nothing while the action runs.
export async function submitting(form, action, t, submit = inForm(form, '[type="submit"]')[0]) {
  if (submittingForms.has(form)) return
  submittingForms.add(form)
  submit.disabled = true
  clearFormErrors(form)
  try {
    await action()
  } catch (error) {
    if (isLeaving(error)) return
    if (error?.status === undefined) throw error
    showFormError(form, error, t)
  } finally {
    submittingForms.delete(form)
    submit.disabled = false
    // Disabling the focused button sent the focus to <body>: bring it back where the user was, as the base's own does, with
    // no scrolling back away from a refusal just brought into view
    if (document.activeElement === document.body) submit.focus({ preventScroll: true })
  }
}

// What a form's named fields hold, in the order of the page: memory only, for a draw of the same form further on
export function typedFields(form) {
  return inForm(form, 'input, select, textarea')
    .filter((control) => control.name && !['file', 'hidden', 'submit', 'button', 'image', 'reset'].includes(control.type))
    .map((control) => ({
      name: control.name,
      value: control.type === 'checkbox' || control.type === 'radio' ? control.checked : control.value,
    }))
}

// Back into the fields of the same name. What follows a field by its input event hears the change.
export function restoreTypedFields(form, fields) {
  const left = [...fields]
  for (const control of inForm(form, 'input, select, textarea')) {
    const index = left.findIndex((field) => field.name === control.name)
    if (index < 0) continue
    const [{ value }] = left.splice(index, 1)
    if (control.type === 'checkbox' || control.type === 'radio') control.checked = value
    else control.value = value
    control.dispatchEvent(new Event('input', { bubbles: true }))
  }
}

// What a form holds now, if it is no longer what it held then: what was typed while its save or its delete was on its way
export function typedSince(form, then) {
  const now = typedFields(form)
  return JSON.stringify(now) === JSON.stringify(then) ? null : now
}

// Typed text never goes in silence, and only a press away from the form asks: Cancel says what it does
export function askToDiscard(ctx) {
  return ctx.ui.confirm({
    title: ctx.t('redirect.discard_title'),
    text: ctx.t('redirect.discard_text'),
    confirm: ctx.t('redirect.discard_confirm'),
    cancel: ctx.t('redirect.discard_keep'),
  })
}

// How much of a form must fit under its top for that top to count as in view: about its title. Less shows nothing of the press
const TOP_IN_VIEW = 48

// A press on a row changes a form that may lie out of the window: below the list on a phone, above a long list elsewhere
export function bringIntoView(el) {
  const { top } = el.getBoundingClientRect()
  if (top < 0 || top > window.innerHeight - TOP_IN_VIEW) el.scrollIntoView({ block: 'start' })
}

// A field with a button at the end of its line. The kit's field is a label, which cannot hold a second control. Its parts
// have the classes of the kit's field, so errors find their place the same way.
export function fieldWithAction(ctx, { label, id, name, value, placeholder, mono, action, help }) {
  const { h } = ctx.ui
  const errorId = `${id}-error`
  const input = h('input', {
    id,
    name,
    value,
    placeholder,
    class: mono ? 'input mono' : 'input',
    autocomplete: 'off',
    'aria-describedby': help?.id ? `${help.id} ${errorId}` : errorId,
  })
  return h(
    'div',
    { class: 'field' },
    h('label', { for: id }, label),
    h('div', { class: 'redirect-field-line' }, input, action),
    help,
    h('span', { class: 'field-error', id: errorId, hidden: true }),
  )
}

// --- Parts of a page --------------------------------------------------------------------------------------------------

// The form's title. The kit gives it a width to share a line with actions: here it has the line to itself.
export function formTitle(ctx, text) {
  return ctx.ui.h('h2', { class: 'card-title redirect-form-title' }, text)
}

// The text for a count. A page has no plural rule, so each language says its forms in its own texts, as the status does
export function byCount(count, none, one, many) {
  if (count === 0) return none
  return count === 1 ? one : many
}

// What the page is about, with how many of its own kind there are. The frame's status holds the total of every kind, so
// a page's own count lives here. The rows a search or a filter hides still count.
export function pageHead(ctx, intro, count, [none, one, many]) {
  const { chip, h } = ctx.ui
  return h(
    'div',
    { class: 'redirect-head' },
    h('p', { class: 'redirect-intro' }, ctx.t(intro)),
    chip({ text: ctx.t(byCount(count, none, one, many), { count: String(count) }), level: 'success', class: 'redirect-count' }),
  )
}

// What the list says under its headers when it shows no row: none answers the search, or there is none yet and the form
// beside it, open on a new one, makes the first. The page keeps its list and its form whatever the count.
export function noRowsKey(total, noneMatch, noneYet) {
  return total ? noneMatch : noneYet
}

// Where the focus goes when it was meant for a row and the list has none: the page, where the shell's frame would keep it.
export function focusPage() {
  document.getElementById('page')?.focus({ preventScroll: true })
}

// The line above the list that says what a change did. It is hidden until it has something to say.
export function noticeLine(ctx, said) {
  const { h } = ctx.ui
  return h(
    'p',
    { class: said?.error ? 'redirect-notice redirect-notice-error' : 'redirect-notice', role: 'status', hidden: !said },
    said ? ctx.t(said.key, said.params) : '',
  )
}

// What the line said belongs to a moment now over, once a press on a row, Cancel, New, Save or a confirmed Delete moves on from it
export function clearNotice(line) {
  line.hidden = true
  line.textContent = ''
  line.classList.remove('redirect-notice-error')
}

// A link's address, its path unless told otherwise, and its name, in the first column of a list
export function linkCell(ctx, link, address = `/redirect/${link.slug}`) {
  const { h } = ctx.ui
  return h(
    'div',
    { class: 'redirect-link' },
    h('span', { class: 'mono redirect-path' }, address),
    h('span', { class: 'redirect-name' }, link.name),
  )
}

// Copy on a row, which a screen reader tells from the Copy of the other rows. A name given by hand hides what the kit then
// writes in the button, so while the button says how a copy went, that is its name. Followed from the first press alone: a
// list may hold thousands of these.
export function copyButton(ctx, url, address) {
  const el = ctx.ui.copy({ text: url, class: 'redirect-copy' })
  const rest = el.textContent
  const named = ctx.t('redirect.copy_named', { address })
  el.setAttribute('aria-label', named)
  let following = false
  el.addEventListener('click', () => {
    if (following) return
    following = true
    new MutationObserver(() => {
      el.setAttribute('aria-label', el.textContent === rest ? named : el.textContent)
    }).observe(el, { childList: true })
  })
  return el
}

// Every kind is deleted the same way, and what the question names is the address that stops working
export function confirmDelete(ctx, link, url) {
  return ctx.ui.confirm({
    title: ctx.t('redirect.delete_title', { name: link.name }),
    text: ctx.t('redirect.delete_text', { url }),
    confirm: ctx.t('redirect.delete'),
  })
}

// --- A link's address -------------------------------------------------------------------------------------------------
// Added in 9.1.0, with the look of 7.0.1's link address select: a link answers on the LAN, or also at a Cloudflare host.
// Shown only while Cloudflare is on and a host is set up, so a LAN-only instance looks as it did.

// What a row shows and copies: its Cloudflare address when it has one, else the LAN address the page always showed
export function sharedUrl(link, lanUrl) {
  return link?.cloudflare ? link.address_url : lanUrl
}

// The Address select of a form, with what the chosen address means under it and, on an edit, the Cloudflare state.
// `path` is the path on a host, `lanPath` the one on the public URL (7.0.1's hint). `onChange` hears a new choice. Null
// when there is nothing to choose.
export function addressField(ctx, { link, addresses, path, lanPath, onChange }) {
  const choices = addressChoices(addresses)
  if (!choices) return null
  const { chip, h, select } = ctx.ui
  const help = h('span', { class: 'redirect-host-help' })
  const el = select({
    label: ctx.t('redirect.f_address'),
    name: 'address',
    value: link?.address ?? 'lan',
    help,
    options: choices.map((choice) => ({
      value: choice.address,
      text:
        choice.address === 'lan'
          ? ctx.t('redirect.address_lan', { url: choice.url })
          : ctx.t(choice.adopted ? 'redirect.address_adopted' : 'redirect.address_host', { host: choice.address }),
    })),
  })
  const control = el.querySelector('select')
  const lan = choices.find((choice) => choice.address === 'lan')
  const follow = () => {
    help.textContent =
      control.value === 'lan'
        ? ctx.t('redirect.address_lan_help', { url: `${String(lan?.url ?? '').replace(/\/+$/, '')}${lanPath()}` })
        : ctx.t('redirect.address_host_help', { url: `https://${control.value}/${path()}` })
  }
  control.addEventListener('input', () => {
    follow()
    onChange?.(control.value)
  })
  follow()
  const view = linkStateView(link)
  if (view) {
    const fault = link.cloudflare.state === 'error' ? errorText(link.cloudflare.error) : null
    el.append(
      h(
        'span',
        { class: 'redirect-address-state' },
        chip({ text: ctx.t(view.key), level: view.level }),
        fault ? h('span', { class: 'redirect-address-error' }, ctx.t(fault.key)) : null,
        fault?.detail ? h('span', { class: 'mono redirect-address-detail' }, fault.detail) : null,
      ),
    )
  }
  return el
}

// The line under a row's name in a list: where the link answers, and its Cloudflare state
export function addressCell(ctx, link) {
  const { chip, h } = ctx.ui
  const view = linkStateView(link)
  return h(
    'div',
    { class: 'redirect-address' },
    h('span', { class: 'mono redirect-address-host' }, link.cloudflare ? link.address : ctx.t('redirect.address_lan_short')),
    view ? chip({ text: ctx.t(view.key), level: view.level }) : null,
  )
}

// A change that stops a Cloudflare address is asked first: what was printed or shared with it stops working
export function confirmBreak(ctx, link) {
  return ctx.ui.confirm({
    title: ctx.t('redirect.break_title'),
    text: ctx.t('redirect.break_text', { url: link.address_url }),
    confirm: ctx.t('redirect.break_confirm'),
  })
}

// The body a save sends for the address chosen, asking first when it stops a Cloudflare address. Null: the user kept it.
export async function withAddress(ctx, form, link, body) {
  const control = form.elements.namedItem('address')
  if (!control) return body
  const address = control.value
  if (!breaksAddress(link, address, body.slug)) return { ...body, address }
  if (!(await confirmBreak(ctx, link))) return null
  return { ...body, address, confirm_break: true }
}

// What a delete sends: a link with a Cloudflare address says it was asked, as the question named that address
export function deleteOptions(link, id) {
  return link?.cloudflare ? { method: 'DELETE', id, json: { confirm_break: true } } : { method: 'DELETE', id }
}
