// Source: Moonie Redirect 7.0.1 admin UI, ui/pages/plugins.js, its settings tab for the Cloudflare
// plugin: renderCredential and an integer row, trimmed: other plugins' settings, the settings key under each
// cell, the footer's Cancel. Added: Clear (the token file takes over), the token's check as the Cloudflare page says it,
// the four permissions of the plugin's README, where each value comes from, and the Cloudflare page's domains under them
// (D29), in the place of the plugin's own page.
// The Cloudflare tab: the API token and the list item limit, then the domains.

import { isLeaving, keepForNextDraw, noticeLine, spokenCode, submitting } from './common.js'
import { TOKEN_ANCHOR, loadDomains, mountDomains } from './cloudflare.js'
import { tokenView } from './cloudflare-logic.js'
import { credentialView, limitValue, originView, placeCode, readable, tokenChecked } from './settings-logic.js'

const TOKEN_FILE = 'MOONIE_REDIRECT_CLOUDFLARE_TOKEN_FILE'
const LIMIT_ENV = 'MOONIE_REDIRECT_CLOUDFLARE_ITEM_LIMIT'
// The token row's control: its field, or Replace while a token is in force
const TOKEN_CONTROL = '.settings-token input, .settings-token .token-replace'

// What the token needs, as the plugin's README says it: the policy, the permission, and why
const PERMISSIONS = [
  ['settings.cf_perm_lists', 'settings.cf_perm_lists_why'],
  ['settings.cf_perm_rulesets', 'settings.cf_perm_rulesets_why'],
  ['settings.cf_perm_zone', 'settings.cf_perm_zone_why'],
  ['settings.cf_perm_dns', 'settings.cf_perm_dns_why'],
]

function chipOf(ctx, origin, extra) {
  const view = originView(origin)
  return ctx.ui.chip({ text: ctx.t(view.text), level: view.level, class: extra })
}

function settingLabel(ctx, text, { secret = false } = {}, ...after) {
  const { h, chip } = ctx.ui
  return h('span', { class: 'setting-label' }, text, secret && chip({ text: ctx.t('settings.secret'), mono: true, class: 'setting-secret' }), after)
}

// What the instance answered draws the tab again, with a line that says what was done. The domains are read again with
// it: a new token or limit changes what they show.
async function redrawWith(el, ctx, answer, notice, focus) {
  let domains = null
  try {
    domains = await loadDomains(ctx)
  } catch (error) {
    if (isLeaving(error)) return
  }
  const data = { settings: answer, domains }
  if (readable('cloudflare', data)) {
    el.replaceChildren()
    drawCloudflare(el, data, ctx, { kept: { tab: 'cloudflare', notice, focus } })
    return
  }
  // Stored, but an answer says nothing readable: only reading the tab again can tell what it now holds
  keepForNextDraw({ tab: 'cloudflare', notice, focus })
  ctx.reload()
}

// The domains' way to the token: its control takes the focus, which brings it into view
function toToken(el) {
  el.querySelector(TOKEN_CONTROL)?.focus()
}

// The token's check: the Cloudflare page's chip and the lines under it
function tokenCheck(ctx, token) {
  const { h, chip } = ctx.ui
  const view = tokenView(token)
  return h(
    'div',
    { class: 'settings-check' },
    h('div', { class: 'setting-fixed' }, chip({ text: ctx.t(view.chip), level: view.level, class: 'cf-token' })),
    view.banners.map((line) =>
      h(
        'div',
        { class: `cf-banner cf-banner-${line.level}`, role: line.level === 'danger' ? 'alert' : null },
        h('span', { class: `dot dot-${line.level}` }),
        h('p', {}, ctx.t(line.key, line.params ?? {})),
      ),
    ),
  )
}

function permissions(ctx) {
  const { h } = ctx.ui
  return h(
    'div',
    { class: 'settings-perms' },
    h('span', { class: 'field-help' }, ctx.t('settings.cf_token_help')),
    h(
      'ul',
      { class: 'settings-perms-list' },
      PERMISSIONS.map(([permission, why]) =>
        h('li', { class: 'settings-perm' }, h('span', { class: 'settings-perm-name' }, ctx.t(permission)), h('span', { class: 'settings-perm-why' }, ctx.t(why))),
      ),
    ),
  )
}

// A credential: its value goes in and never comes back, so all there is to show is where it comes from
function tokenCell(el, data, ctx) {
  const { t, ui } = ctx
  const { h } = ui
  const { origin } = data.token
  const view = credentialView(origin)
  const host = h('div', { class: 'setting settings-token', id: TOKEN_ANCHOR, 'data-key': 'token' })
  const alert = h('p', { class: 'form-error settings-alert', role: 'alert', hidden: true })

  function save(form, input) {
    return submitting(
      form,
      async () => {
        if (!input.value.trim()) throw { status: 0, fields: { token: 'settings.field_required' } }
        let answer
        try {
          answer = await ctx.api('admin.cf_token_set', { json: { token: input.value.trim() } })
        } catch (error) {
          throw placeCode(error, { 'cloudflare.token_invalid': { field: 'token', text: 'settings.cf_token_refused' } })
        }
        await redrawWith(el, ctx, answer, { key: 'settings.cf_token_saved' }, '.token-replace')
      },
      t,
    )
  }

  async function clear() {
    const sure = await ui.confirm({ title: t('settings.cf_clear_title'), text: t('settings.cf_clear_text'), confirm: t('settings.cf_clear') })
    if (!sure) return
    alert.hidden = true
    let answer
    try {
      answer = await ctx.api('admin.cf_token_clear')
    } catch (error) {
      if (isLeaving(error)) return
      alert.textContent = spokenCode(t, error?.code, error?.params)
      alert.hidden = false
      return
    }
    await redrawWith(el, ctx, answer, { key: 'settings.cf_token_cleared' }, '.settings-token button, .settings-token input')
  }

  function draw(replacing) {
    const state = chipOf(ctx, origin, 'setting-origin token-state')
    let body
    if (view.control === 'replace' && !replacing) {
      body = h(
        'div',
        { class: 'setting-fixed' },
        state,
        ui.button({ text: t('settings.replace'), class: 'token-replace', onClick: () => draw(true).querySelector('input').focus() }),
        view.clear && ui.button({ text: t('settings.cf_clear'), variant: 'danger', class: 'token-clear', onClick: clear }),
      )
    } else {
      // The cell's own label names the field
      const field = ui.field({ name: 'token', type: 'password', mono: true, autocomplete: 'new-password' })
      const input = field.querySelector('input')
      input.setAttribute('aria-label', t('settings.cf_token'))
      const form = h(
        'form',
        {
          class: 'token-form',
          novalidate: true,
          onsubmit: (event) => {
            event.preventDefault()
            save(form, input)
          },
        },
        h('p', { class: 'form-error', role: 'alert', hidden: true }),
        field,
        h(
          'div',
          { class: 'token-buttons' },
          ui.button({ text: t('common.save'), type: 'submit', class: 'token-save' }),
          replacing &&
            ui.button({ text: t('common.cancel'), class: 'token-cancel', onClick: () => draw(false).querySelector('.token-replace').focus() }),
        ),
      )
      body = h('div', { class: 'token-body' }, h('div', { class: 'setting-fixed' }, state), form)
    }
    // The parts that are not there go: the DOM would write `false` as text
    host.replaceChildren(
      ...[
        settingLabel(ctx, t('settings.cf_token'), { secret: true }),
        body,
        alert,
        origin === 'file' && h('span', { class: 'mono setting-env' }, TOKEN_FILE),
        origin === 'unreadable' && h('span', { class: 'field-help' }, t('settings.cf_token_unreadable')),
        tokenChecked(origin) && tokenCheck(ctx, data.token),
        permissions(ctx),
      ].filter(Boolean),
    )
    return host
  }

  return draw(false)
}

function limitCell(el, data, ctx) {
  const { t, ui } = ctx
  const { h } = ui
  const limit = data.item_limit
  const field = ui.field({
    label: settingLabel(ctx, t('settings.cf_limit'), {}, chipOf(ctx, limit.origin, 'setting-origin')),
    name: 'value',
    value: limit.origin === 'stored' && limit.value !== null && limit.value !== undefined ? String(limit.value) : '',
    placeholder: limit.origin === 'stored' ? undefined : String(limit.value ?? ''),
    help: t('settings.cf_limit_help'),
    autocomplete: 'off',
  })
  const input = field.querySelector('input')
  input.setAttribute('inputmode', 'numeric')
  const form = h(
    'form',
    {
      class: 'token-form settings-limit-form',
      novalidate: true,
      onsubmit: (event) => {
        event.preventDefault()
        submitting(
          form,
          async () => {
            const typed = limitValue(input.value)
            if (typed.error) throw { status: 0, fields: { value: typed.error } }
            const answer = await ctx.api('admin.cf_item_limit', { json: { value: typed.value } })
            await redrawWith(el, ctx, answer, { key: 'settings.cf_limit_saved' }, '.settings-limit-form input')
          },
          t,
        )
      },
    },
    h('p', { class: 'form-error', role: 'alert', hidden: true }),
    field,
    h('div', { class: 'token-buttons settings-limit-buttons' }, ui.button({ text: t('common.save'), type: 'submit', class: 'settings-limit-save' })),
  )
  return h(
    'div',
    { class: 'setting settings-limit', 'data-key': 'item_limit' },
    form,
    limit.origin === 'env' && h('span', { class: 'mono setting-env' }, LIMIT_ENV),
  )
}

// `data`: the settings answer and the domains' state, as the tab's load reads them
export function drawCloudflare(el, data, ctx, { kept } = {}) {
  const { h, card } = ctx.ui
  const mine = kept?.tab === 'cloudflare' ? kept : null
  const domains = h('div', { class: 'settings-cf-domains' })
  el.append(
    noticeLine(ctx, mine?.notice ?? null),
    card({ class: 'settings-cf', body: false }, h('div', { class: 'settings-grid' }, tokenCell(el, data.settings, ctx), limitCell(el, data.settings, ctx))),
    domains,
  )
  // The token's row says its check whenever it has one: the domains' head leaves it out then
  mountDomains(domains, data.domains, ctx, { tokenShown: tokenChecked(data.settings.token.origin), toToken: () => toToken(el) })
  if (mine?.focus) el.querySelector(mine.focus)?.focus({ preventScroll: true })
}
