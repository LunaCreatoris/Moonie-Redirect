// Source: Moonie Redirect 7.0.1 admin UI, ui/pages/webhook.js and ui/pages/keys.js, trimmed: replies
// routed to plugins, the incoming calls card, base events, keys made by keys (their parent and revoke_children), the
// saved-but-unread notice (a save answers the new state). Added: the deliveries waiting, the token file as a fixed key.
// The Webhook & API tab: n8n's connection, the events it gets, the last delivery, then the API keys. The signing secret is
// write-only: the page never receives it, and sends it only when something was typed.

import {
  byCount,
  clearFormErrors,
  formatTime,
  isLeaving,
  keepForNextDraw,
  noticeLine,
  showFormError,
  spokenCode,
  submitting,
} from './common.js'
import { crescentMark } from './icons.js'
import { sessionGone } from './lib.js'
import {
  CONFIGURE_FLAG,
  deliveryView,
  eventRows,
  isSuccess,
  keyCheck,
  keyRows,
  placeCode,
  scopesIn,
  statusText,
  suggestions,
  tabAddress,
  toggleScope,
  webhookBody,
} from './settings-logic.js'

const GRID = 'minmax(0, 1fr) 130px minmax(0, 1.6fr) 170px 104px'
const MIN_WIDTH = 800

// --- Dialogs ----------------------------------------------------------------------------------------------------------

// A modal over the page, which ends with the address it was opened on: the frame is inert under it, only the browser's
// own buttons can still navigate. Its `closed` handler runs when the user closes it, not when the address changes.
// `hold(true)` keeps it open until `hold(false)`: closedby="none" takes the ways out away, and in a browser that ignores
// the attribute `cancel` refuses the first Escape and the dialog opens again after the next.
export function openModal(h, label, { closed }) {
  const dialog = h('dialog', { class: 'card dialog keys-dialog', 'aria-label': label })
  let held = false
  const hold = (on) => {
    held = on
    if (on) dialog.setAttribute('closedby', 'none')
    else dialog.removeAttribute('closedby')
  }
  dialog.addEventListener('cancel', (event) => {
    if (held) event.preventDefault()
  })
  const remove = () => {
    window.removeEventListener('popstate', remove)
    dialog.remove()
  }
  window.addEventListener('popstate', remove)
  dialog.addEventListener('close', () => {
    if (held && dialog.isConnected) {
      dialog.showModal()
      return
    }
    remove()
    closed()
  })
  document.body.append(dialog)
  return { dialog, remove, hold }
}

// --- Webhook ----------------------------------------------------------------------------------------------------------

function eventList(data, ctx) {
  const { h, icon } = ctx.ui
  return eventRows(data.available, data.events).map((row) =>
    h(
      'label',
      { class: 'webhook-event' },
      h('input', { class: 'webhook-check', type: 'checkbox', name: 'event', value: row.name, 'data-event': row.name, checked: row.checked }),
      h('span', { class: 'webhook-box' }, icon('check', { size: 14 })),
      h('span', { class: 'webhook-event-name mono' }, row.name),
      h('span', { class: 'webhook-event-hint' }, row.key ? ctx.t(row.key) : row.label),
    ),
  )
}

function testNotice(answer, url, ctx) {
  const { h, chip, code } = ctx.ui
  const passed = isSuccess(answer.status)
  const answered = Number.isInteger(answer.status) ? answer.status : ctx.t('webhook.no_answer')
  const line = `${url} → ${answered} · ${ctx.t('webhook.duration', { ms: String(answer.duration_ms) })}`
  const reply = answer.reply_is_json ? ctx.t('webhook.test_reply_json') : ctx.t('webhook.test_reply_other')
  return h(
    'div',
    { class: 'webhook-result', role: 'status' },
    chip({ text: passed ? ctx.t('webhook.test_ok') : ctx.t('webhook.test_failed'), level: passed ? 'success' : 'danger' }),
    code(line),
    answer.error && code(answer.error),
    passed && h('span', { class: 'webhook-result-note' }, reply),
  )
}

function refusedNotice(error, ctx) {
  const { h, chip } = ctx.ui
  // 429 is this app's one test at a time, not Cloudflare's busy host
  const code = error.status === 429 ? 'webhook.test_busy' : error.code
  return h(
    'div',
    { class: 'webhook-result', role: 'status' },
    chip({ text: ctx.t('webhook.test_failed'), level: 'danger' }),
    h('span', { class: 'webhook-result-note' }, spokenCode(ctx.t, code, error.params)),
  )
}

async function runTest(button, slot, url, ctx) {
  const idle = button.textContent
  button.disabled = true
  button.textContent = ctx.t('webhook.test_running')
  slot.replaceChildren()
  try {
    slot.replaceChildren(testNotice(await ctx.api('admin.webhook_test', { json: {} }), url, ctx))
  } catch (error) {
    if (isLeaving(error)) return
    if (error?.status === undefined) throw error
    slot.replaceChildren(refusedNotice(error, ctx))
  } finally {
    button.disabled = false
    button.textContent = idle
    // Disabling the focused button sent the focus to <body>: bring it back where the user was
    if (document.activeElement === document.body) button.focus()
  }
}

function disabledBanner(ctx) {
  const { h, card } = ctx.ui
  return card(
    { class: 'webhook-disabled' },
    h('h2', { class: 'webhook-title webhook-disabled-title' }, h('span', { class: 'dot dot-warning' }), ctx.t('webhook.disabled_title')),
    h('p', { class: 'webhook-desc' }, ctx.t('webhook.disabled_desc')),
  )
}

const SECRET_CHIPS = {
  stored: { text: 'webhook.secret_is_set', level: 'success' },
  missing: { text: 'webhook.secret_not_set' },
  unreadable: { text: 'settings.origin_unreadable', level: 'warning' },
}

function secretLabel(data, ctx) {
  const { h, chip } = ctx.ui
  const state = Object.hasOwn(SECRET_CHIPS, data.secret) ? SECRET_CHIPS[data.secret] : SECRET_CHIPS.missing
  return h(
    'span',
    { class: 'webhook-field-label' },
    ctx.t('webhook.secret'),
    h('span', { class: 'webhook-secret-state' }, chip({ text: ctx.t(state.text), level: state.level })),
  )
}

function connectionCard(data, ctx) {
  const { h, card, field } = ctx.ui
  const kept = data.secret === 'stored'
  return card(
    {},
    h('h2', { class: 'webhook-title' }, ctx.t('webhook.title')),
    h('p', { class: 'webhook-desc' }, ctx.t('webhook.desc')),
    h('p', { class: 'form-error', role: 'alert', hidden: true }),
    h(
      'div',
      { class: 'webhook-fields' },
      field({
        label: h('span', { class: 'webhook-field-label' }, ctx.t('webhook.url')),
        name: 'url',
        value: data.url ?? '',
        mono: true,
        autocomplete: 'off',
        help: data.cleartext ? ctx.t('webhook.url_cleartext') : undefined,
      }),
      field({
        label: secretLabel(data, ctx),
        name: 'secret',
        type: 'password',
        mono: true,
        autocomplete: 'new-password',
        placeholder: kept ? ctx.t('webhook.secret_kept') : ctx.t('webhook.secret_placeholder'),
        help: data.secret === 'unreadable' ? ctx.t('webhook.secret_unreadable') : ctx.t('webhook.secret_help'),
      }),
    ),
  )
}

function eventsCard(data, ctx, { notice, onClear }) {
  const { h, card, button } = ctx.ui
  const slot = h('div', { class: 'webhook-result-slot' }, notice)
  const test = button({
    text: ctx.t('webhook.test'),
    class: 'webhook-test',
    disabled: !data.configured,
    onClick: () => runTest(test, slot, data.url, ctx),
  })
  return card(
    {},
    h('h2', { class: 'webhook-title' }, ctx.t('webhook.events')),
    h('p', { class: 'webhook-desc' }, ctx.t('webhook.events_desc')),
    h(
      'div',
      { class: 'field webhook-events', role: 'group', 'aria-label': ctx.t('webhook.events') },
      eventList(data, ctx),
      // Where a refusal of the events goes: the checkboxes share one name
      h('input', { type: 'hidden', name: 'events' }),
      h('span', { class: 'field-error', hidden: true }),
    ),
    slot,
    h(
      'div',
      { class: 'webhook-actions' },
      data.configured && button({ text: ctx.t('webhook.clear'), variant: 'danger', class: 'webhook-clear', onClick: onClear }),
      test,
      button({ text: ctx.t('common.save'), variant: 'accent', type: 'submit' }),
    ),
  )
}

function lastDelivery(last, ctx) {
  const { h, chip, code } = ctx.ui
  const view = deliveryView(last)
  if (!view) return h('p', { class: 'webhook-desc' }, ctx.t('webhook.last_none'))
  return h(
    'div',
    { class: 'webhook-delivery' },
    h(
      'div',
      { class: 'webhook-delivery-line' },
      code(view.event),
      chip({ text: statusText(view.status, ctx.t), level: isSuccess(view.status) ? 'success' : 'danger', mono: true }),
    ),
    view.at && h('span', { class: 'webhook-event-hint' }, formatTime(view.at)),
    view.id && h('span', { class: 'webhook-event-hint mono' }, view.id),
    view.error && code(view.error),
  )
}

function deliveryCard(data, ctx) {
  const { h, card, chip } = ctx.ui
  const waiting = Number.isInteger(data.waiting) ? data.waiting : 0
  return card(
    {},
    h('h2', { class: 'webhook-title' }, ctx.t('webhook.delivery_title')),
    h(
      'div',
      { class: 'webhook-facts' },
      h(
        'div',
        { class: 'webhook-fact webhook-last' },
        h('span', { class: 'webhook-fact-label' }, ctx.t('webhook.last_delivery')),
        lastDelivery(data.last_delivery, ctx),
        chip({
          text: ctx.t(byCount(waiting, 'webhook.waiting_none', 'webhook.waiting_one', 'webhook.waiting_many'), { count: String(waiting) }),
          level: waiting ? 'info' : undefined,
          class: 'webhook-waiting',
        }),
      ),
      h(
        'div',
        { class: 'webhook-fact webhook-reply' },
        h('span', { class: 'webhook-fact-label' }, ctx.t('webhook.reply_timeout')),
        h('span', { class: 'webhook-fact-value' }, ctx.t('webhook.timeout_value', { seconds: String(data.timeout_seconds) })),
        h('p', { class: 'webhook-desc' }, ctx.t('webhook.reply_help')),
      ),
    ),
  )
}

// No webhook yet: 7.0.1's empty card, in the place of the three webhook cards
function emptyCard(ctx, onConfigure) {
  const { h, button } = ctx.ui
  const mark = crescentMark()
  mark.classList.add('state-mark')
  return h(
    'section',
    { class: 'card state-card webhook-empty' },
    mark,
    h('h2', { class: 'state-title' }, ctx.t('webhook.empty_title')),
    h('p', { class: 'state-desc' }, ctx.t('webhook.empty_desc')),
    button({ text: ctx.t('webhook.configure'), variant: 'accent', class: 'webhook-configure', onClick: onConfigure }),
  )
}

function savedNotice(ctx) {
  const { h } = ctx.ui
  return h('div', { class: 'webhook-result', role: 'status' }, h('span', { class: 'dot dot-success' }), ctx.t('webhook.saved'))
}

// The webhook's cards. `host` holds them alone, so a save draws them again from its answer and the keys stay.
function drawHook(host, data, ctx, { configuring, notice = null }) {
  const { h, confirm } = ctx.ui

  if (!data.configured && !configuring) {
    host.replaceChildren(
      emptyCard(ctx, () => {
        // The address asks for the form, so Back returns to this card
        ctx.address(tabAddress(location.search, 'webhook', { configure: true }), { push: true })
        drawHook(host, data, ctx, { configuring: true })
        host.querySelector('input[name="url"]')?.focus()
      }),
    )
    return
  }

  async function clear() {
    const yes = await confirm({ title: ctx.t('webhook.clear_title'), text: ctx.t('webhook.clear_desc'), confirm: ctx.t('webhook.clear_confirm') })
    if (!yes) return
    clearFormErrors(form)
    try {
      await ctx.api('admin.webhook_delete')
    } catch (error) {
      if (isLeaving(error)) return
      if (error?.status === undefined) throw error
      showFormError(form, error, ctx.t)
      return
    }
    keepForNextDraw({ tab: 'webhook', notice: { key: 'webhook.deleted' } })
    ctx.navigate(tabAddress(location.search, 'webhook'))
  }

  async function save(event) {
    event.preventDefault()
    // The notice of an earlier save or test says nothing about this one
    form.querySelector('.webhook-result-slot').replaceChildren()
    await submitting(
      form,
      async () => {
        const events = [...form.querySelectorAll('input[data-event]:checked')].map((box) => box.dataset.event)
        const body = webhookBody({ url: form.elements.url.value, events, secret: form.elements.secret.value })
        let answer
        try {
          answer = await ctx.api('admin.webhook_save', { json: body })
        } catch (error) {
          throw placeCode(error, {
            'webhook.field_url_closed': { field: 'url' },
            'webhook.field_secret_required': { field: 'secret' },
          })
        }
        // Stored now: the flag that asked for the form has done its work
        ctx.address(tabAddress(location.search, 'webhook'))
        if (answer && Array.isArray(answer.available) && Array.isArray(answer.events)) {
          drawHook(host, answer, ctx, { configuring: false, notice: savedNotice(ctx) })
          host.querySelector('[type="submit"]')?.focus({ preventScroll: true })
        } else {
          // Stored, but the answer says nothing readable: only reading it again can tell what it now holds
          keepForNextDraw({ tab: 'webhook', notice: { key: 'webhook.saved' } })
          ctx.reload()
        }
      },
      ctx.t,
    )
  }

  const form = h(
    'form',
    { class: 'webhook-form', novalidate: true, onsubmit: save },
    connectionCard(data, ctx),
    eventsCard(data, ctx, { notice, onClear: clear }),
  )
  host.replaceChildren(...[data.disabled_reason ? disabledBanner(ctx) : null, form, deliveryCard(data, ctx)].filter(Boolean))
}

// --- API keys ---------------------------------------------------------------------------------------------------------

function scopeSuggestions(ctx, input, known) {
  const { h } = ctx.ui
  const buttons = suggestions(known).map((scope) =>
    h(
      'button',
      {
        class: 'chip mono keys-scope',
        type: 'button',
        'aria-pressed': 'false',
        onclick: () => {
          input.value = toggleScope(input.value, scope)
          sync()
        },
      },
      scope,
    ),
  )
  const sync = () => {
    const current = scopesIn(input.value)
    buttons.forEach((button) => button.setAttribute('aria-pressed', String(current.includes(button.textContent))))
  }
  input.addEventListener('input', sync)
  return h(
    'div',
    { class: 'keys-suggest-group' },
    h('span', { class: 'field-help' }, ctx.t('keys.known_scopes')),
    h('div', { class: 'keys-suggest', role: 'group', 'aria-label': ctx.t('keys.known_scopes') }, buttons),
  )
}

// The secret exists only in this answer, so this view leaves only by its own button: closing it brings the new row
function showSecret(ctx, dialog, answer, done) {
  const { h, code, copy, button } = ctx.ui
  const copyButton = copy({ text: answer.secret })
  dialog.setAttribute('aria-label', ctx.t('keys.secret_title'))
  dialog.replaceChildren(
    h(
      'div',
      { class: 'dialog-body' },
      h('h2', { class: 'card-title' }, ctx.t('keys.secret_title')),
      h('p', { class: 'keys-secret-text' }, ctx.t('keys.secret_text')),
      code(answer.secret, { class: 'keys-secret' }),
      h(
        'div',
        { class: 'dialog-actions' },
        copyButton,
        button({ text: ctx.t('keys.secret_done'), variant: 'accent', class: 'keys-done', onClick: done }),
      ),
    ),
  )
  copyButton.focus()
}

function openNewKey(ctx, known) {
  const { h, field, button } = ctx.ui
  let answer = null
  let busy = false
  const { dialog, remove, hold } = openModal(h, ctx.t('keys.new'), {
    closed() {
      if (!answer) return
      keepForNextDraw({ tab: 'webhook', notice: { key: 'keys.created', params: { name: answer.name } }, focus: '.keys-new' })
      ctx.reload()
    },
  })

  const name = field({ label: ctx.t('keys.field_name'), name: 'name', help: ctx.t('keys.field_name_help'), autocomplete: 'off' })
  const scopes = field({ label: ctx.t('keys.field_scopes'), name: 'scopes', help: ctx.t('keys.field_scopes_help'), mono: true, autocomplete: 'off' })
  const scopesInput = scopes.querySelector('input')
  // A key outlives the session that makes it, so the session gives the password first
  const password = field({
    label: ctx.t('keys.field_password'),
    name: 'password',
    type: 'password',
    help: ctx.t('keys.field_password_help'),
    autocomplete: 'current-password',
  })
  const passwordInput = password.querySelector('input')
  const cancel = button({ text: ctx.t('common.cancel'), class: 'keys-cancel', onClick: () => dialog.close() })

  const send = async () => {
    const json = { name: name.querySelector('input').value.trim(), scopes: scopesIn(scopesInput.value), password: passwordInput.value }
    const refused = keyCheck(json)
    if (refused) throw { status: 0, fields: refused }
    try {
      answer = await ctx.api('admin.key_create', { json })
    } catch (error) {
      // The login page has replaced this one
      if (sessionGone(error)) remove()
      if (error?.code === 'errors.login_failed') passwordInput.value = ''
      throw placeCode(error, { 'errors.login_failed': { field: 'password' }, 'errors.too_many_attempts': { field: 'password' } })
    }
  }

  const form = h(
    'form',
    {
      class: 'dialog-body keys-form',
      novalidate: true,
      onsubmit: async (event) => {
        event.preventDefault()
        if (busy) return
        busy = true
        hold(true)
        cancel.disabled = true
        await submitting(form, send, ctx.t)
        busy = false
        cancel.disabled = false
        if (answer) {
          showSecret(ctx, dialog, answer, () => {
            hold(false)
            dialog.close()
          })
        } else hold(false)
      },
    },
    h('h2', { class: 'card-title' }, ctx.t('keys.new')),
    h('p', { class: 'form-error', role: 'alert', hidden: true }),
    name,
    scopes,
    scopeSuggestions(ctx, scopesInput, known),
    password,
    h('div', { class: 'dialog-actions' }, cancel, button({ text: ctx.t('keys.create'), variant: 'accent', type: 'submit' })),
  )
  dialog.append(form)
  dialog.showModal()
}

async function revoke(ctx, key, alert) {
  const sure = await ctx.ui.confirm({
    title: ctx.t('keys.revoke_title', { name: key.name }),
    text: ctx.t('keys.revoke_text'),
    confirm: ctx.t('common.revoke'),
  })
  if (!sure) return
  alert.hidden = true
  try {
    await ctx.api('admin.key_revoke', { id: key.id })
  } catch (error) {
    // Left, or the login page has replaced this one
    if (isLeaving(error)) return
    // Already gone is what was asked for
    if (error?.status !== 404) {
      alert.textContent = spokenCode(ctx.t, error?.code, error?.params)
      alert.hidden = false
      return
    }
  }
  keepForNextDraw({ tab: 'webhook', notice: { key: 'keys.revoked', params: { name: key.name } }, focus: '.keys-new' })
  ctx.reload()
}

function keyRow(ctx, key, alert) {
  const { h, button } = ctx.ui
  const last = key.last_used_at ? formatTime(key.last_used_at) : ctx.t('keys.never')
  return [
    key.fixed ? h('span', { class: 'keys-file' }, ctx.t('keys.file_name')) : key.name,
    h('span', { class: 'keys-mono' }, typeof key.prefix === 'string' && key.prefix ? `${key.prefix}…` : '—'),
    h('span', { class: 'keys-mono' }, Array.isArray(key.scopes) ? key.scopes.join(', ') : ''),
    h('span', { class: 'keys-last' }, last),
    key.fixed
      ? h('span', { class: 'keys-last keys-fixed' }, ctx.t('keys.file_fixed'))
      : button({
          text: ctx.t('common.revoke'),
          variant: 'danger',
          label: ctx.t('keys.revoke_label', { name: key.name }),
          onClick: () => revoke(ctx, key, alert),
        }),
  ]
}

function keysCard(data, ctx) {
  const { h, button, card, table } = ctx.ui
  const alert = h('p', { class: 'form-error keys-alert', role: 'alert', hidden: true })
  const rows = keyRows(data.keys)
  const hasFile = rows.some((key) => key.fixed)
  const body = rows.length
    ? table({
        columns: [ctx.t('keys.col_name'), ctx.t('keys.col_prefix'), ctx.t('keys.col_scopes'), ctx.t('keys.col_last'), ''],
        rows: rows.map((key) => keyRow(ctx, key, alert)),
        grid: GRID,
        minWidth: MIN_WIDTH,
      })
    : h(
        'div',
        { class: 'keys-empty' },
        h('h3', { class: 'keys-empty-title' }, ctx.t('keys.empty_title')),
        h('p', { class: 'small' }, ctx.t('keys.empty_desc')),
      )
  return card(
    { class: 'keys-card', body: false },
    h(
      'div',
      { class: 'keys-head' },
      h('div', { class: 'keys-head-text' }, h('h2', { class: 'webhook-title' }, ctx.t('keys.title')), h('p', { class: 'keys-desc' }, ctx.t('keys.desc'))),
      button({ text: ctx.t('keys.new'), variant: 'accent', class: 'keys-new', onClick: () => openNewKey(ctx, data.known_scopes) }),
    ),
    alert,
    body,
    hasFile && h('p', { class: 'small keys-file-note' }, ctx.t('keys.file_note')),
  )
}

// --- The tab ----------------------------------------------------------------------------------------------------------

export function drawWebhook(el, { webhook, keys }, ctx, { kept } = {}) {
  const { h } = ctx.ui
  const mine = kept?.tab === 'webhook' ? kept : null
  const hook = h('div', { class: 'webhook-host' })
  el.append(noticeLine(ctx, mine?.notice ?? null), hook, keysCard(keys, ctx))
  drawHook(hook, webhook, ctx, { configuring: ctx.query.has(CONFIGURE_FLAG) })
  if (mine?.focus) el.querySelector(mine.focus)?.focus({ preventScroll: true })
}
