// Source: Moonie Redirect 7.0.1 admin UI, ui/pages/instance.js, trimmed: the Versions card (base
// image and system plugin; the frame already shows the version). Added: where the password comes from, and one line of facts
// about the sessions.
// The Security tab: the administrator's sign-in, its password and its sessions.

import { byCount, isLeaving, keepForNextDraw, noticeLine, spokenCode, submitting } from './common.js'
import { sessionGone } from './lib.js'
import { originView, passwordCheck, placeCode } from './settings-logic.js'
import { openModal } from './settings-webhook.js'

const LOGGED_OUT = '/login?out=1'

// Stays open until the answer: a closed dialog could not say the current password was wrong
function openPasswordChange(ctx) {
  const { t, ui } = ctx
  const { h, field, button } = ui
  let busy = false
  let changed = false
  const { dialog, remove, hold } = openModal(h, t('instance.password_change'), {
    closed() {
      if (!changed) return
      keepForNextDraw({ tab: 'security', notice: { key: 'instance.password_done' }, focus: '.instance-password' })
      ctx.reload()
    },
  })
  const secret = (name, label, autocomplete, help) => field({ label, name, type: 'password', autocomplete, help })
  const cancel = button({ text: t('common.cancel'), class: 'instance-cancel', onClick: () => dialog.close() })

  const send = async () => {
    const { password, new_password: next, new_password_confirm: confirm } = form.elements
    const refused = passwordCheck({ password: password.value, new_password: next.value, new_password_confirm: confirm.value })
    if (refused) throw { status: 0, fields: refused }
    try {
      await ctx.api('admin.password', { json: { password: password.value, new_password: next.value } })
      changed = true
    } catch (error) {
      // The login page has replaced this one
      if (sessionGone(error)) remove()
      if (error?.code === 'errors.login_failed') password.value = ''
      throw placeCode(error, { 'errors.login_failed': { field: 'password' }, 'errors.too_many_attempts': { field: 'password' } })
    }
  }

  const form = h(
    'form',
    {
      class: 'dialog-body instance-form',
      novalidate: true,
      onsubmit: async (event) => {
        event.preventDefault()
        if (busy) return
        busy = true
        hold(true)
        cancel.disabled = true
        await submitting(form, send, t)
        busy = false
        cancel.disabled = false
        hold(false)
        if (changed) dialog.close()
      },
    },
    h('h2', { class: 'card-title' }, t('instance.password_change')),
    h('p', { class: 'small' }, t('instance.password_text')),
    h('p', { class: 'form-error', role: 'alert', hidden: true }),
    secret('password', t('instance.password_current'), 'current-password'),
    secret('new_password', t('instance.password_new'), 'new-password', t('settings.password_help')),
    secret('new_password_confirm', t('instance.password_confirm'), 'new-password'),
    h(
      'div',
      { class: 'dialog-actions' },
      cancel,
      button({ text: t('instance.password_change'), variant: 'accent', type: 'submit' }),
    ),
  )
  dialog.append(form)
  dialog.showModal()
}

async function endSessions(ctx, alert) {
  const sure = await ctx.ui.confirm({
    title: ctx.t('instance.end_sessions_title'),
    text: ctx.t('instance.end_sessions_text'),
    confirm: ctx.t('instance.end_sessions'),
  })
  if (!sure) return
  alert.hidden = true
  try {
    await ctx.api('admin.sessions_end', { json: {} })
  } catch (error) {
    // Left, or the login page has replaced this one
    if (isLeaving(error)) return
    alert.textContent = spokenCode(ctx.t, error?.code, error?.params)
    alert.hidden = false
    return
  }
  // A whole new page: nothing of the shell's state outlives the session
  window.location.assign(LOGGED_OUT)
}

// The facts of the sign-in: how long a session lasts, how many are open, and the brake on a wrong password
function facts(ctx, data) {
  const { h } = ctx.ui
  const active = Number.isInteger(data.sessions.active) ? data.sessions.active : 0
  const parts = [
    ctx.t('instance.fact_hours', { hours: String(data.sessions.hours) }),
    ctx.t(byCount(active, 'instance.fact_active_none', 'instance.fact_active_one', 'instance.fact_active_many'), { count: String(active) }),
    ctx.t('instance.fact_brake', { seconds: String(data.login_brake_seconds) }),
  ]
  return h(
    'p',
    { class: 'small instance-facts' },
    parts.flatMap((part, index) => [index ? h('span', { class: 'instance-sep', 'aria-hidden': 'true' }, '·') : null, h('span', {}, part)]),
  )
}

export function drawSecurity(el, data, ctx, { kept } = {}) {
  const { t, ui } = ctx
  const { h } = ui
  const mine = kept?.tab === 'security' ? kept : null
  const origin = data.password.origin
  const chip = originView(origin)
  const alert = h('p', { class: 'form-error instance-alert', role: 'alert', hidden: true })
  el.append(
    noticeLine(ctx, mine?.notice ?? null),
    ui.card(
      { class: 'instance-signin' },
      h('h2', { class: 'card-title instance-title' }, t('instance.signin')),
      h('p', { class: 'small instance-desc' }, t('instance.signin_desc')),
      h(
        'div',
        { class: 'instance-origin' },
        h('span', { class: 'setting-label' }, t('instance.password_origin')),
        ui.chip({ text: t(chip.text), level: chip.level, class: 'instance-origin-chip' }),
      ),
      origin === 'file' && h('p', { class: 'small instance-file' }, t('instance.password_file')),
      facts(ctx, data),
      alert,
      h(
        'div',
        { class: 'instance-actions' },
        ui.button({
          text: t('instance.password_change'),
          class: 'instance-password',
          onClick: () => openPasswordChange(ctx),
        }),
        ui.button({
          text: t('instance.end_sessions'),
          variant: 'danger',
          class: 'instance-end',
          onClick: () => endSessions(ctx, alert),
        }),
      ),
    ),
  )
  if (mine?.focus) el.querySelector(mine.focus)?.focus({ preventScroll: true })
}
