// Source: Moonie Redirect 7.0.1 Cloudflare plugin, ui/cloudflare.js, trimmed: the Links, NanoURLs and QR codes tabs
// and their forms (a link carries its address in the Redirect pages), the tab bar left with one tab, held hosts and their removal, the
// settings page (the token is set in the same tab). Added: what Cloudflare off shows, and the mount into the Cloudflare
// tab of Settings, under the token's row, which then says the token's check in the head's place (D29).
// The domains of Settings > Cloudflare: the quota state at the top, then the hosts, each set up through a plan the user
// reads before confirming. Compare lists the gaps with Cloudflare and fixes only what the user ticks.
// What the domains decide lives in cloudflare-logic.js; this file draws it.

import {
  FALLBACK_CHOICES,
  applyBody,
  blockedKey,
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
  liveHosts,
  planConfirmable,
  proposalOpen,
  quotaBanner,
  quotaChipAccounts,
  quotaLevel,
  refusalText,
  resyncBody,
  resyncLabel,
  stateReadable,
  stepText,
  tokenView,
  verdictView,
  visibleUrl,
} from './cloudflare-logic.js'
import { byCount, formatTime, isLeaving } from './common.js'
import { crescentMark } from './icons.js'

const MARK = new URL('./moonie-mark-cloudflare.svg', import.meta.url).href
// The token's row of the same tab, where the plugin's banners pointed at its settings
export const TOKEN_ANCHOR = 'settings-cf-token'

// The state of the domains: what the tab reads beside its settings, and again on each refresh
export async function loadDomains(ctx) {
  const state = await ctx.api('cf.state')
  // What no draw can read is a load that failed
  if (!stateReadable(state)) throw new Error('the state came back unreadable')
  return { state, hosts: state.hosts }
}

class Page {
  // `tokenShown`: the token's row above says its check, so the head leaves it out. `toToken` takes the user to that row.
  constructor(el, data, ctx, { tokenShown = false, toToken = () => {} } = {}) {
    this.el = el
    this.data = data
    this.ctx = ctx
    this.tokenShown = tokenShown
    this.toToken = toToken
    this.notice = null
    this.refreshes = 0 // the last reload asked for
    this.drawnRefresh = 0 // the latest reload on screen
    this.fallbackCalls = new Map() // host: the choice its running call sends, whatever redraws the page
    this.fallbackAnswers = new Map() // host: the row the call answered, and the first reload that can know it
    this.lastFallback = null // the host changed last, which keeps the focus
    this.fallbackTyping = new Map() // host: the address typed in its row's field, chosen but not saved yet
    this.fallbackRefused = new Set() // hosts whose typed address the server refused, until the next try
  }

  t(key, params) {
    return this.ctx.t(key, params)
  }

  // --- The data -------------------------------------------------------------------------------------------------------

  // Reloads the state and draws it. A failed reload keeps the page on screen, says so in the notice and still draws, so
  // the button that asked for it is given back rather than left disabled.
  // Reloads can overlap and answer in any order: one older than what is on screen is dropped, so a snapshot never
  // replaces a newer one, and the newer one's draw has given the button back
  async refresh() {
    const turn = ++this.refreshes
    let data = null
    try {
      data = await loadDomains(this.ctx)
    } catch (error) {
      if (isLeaving(error)) return
      if (turn < this.drawnRefresh) return
      this.sayRefusal(error)
    }
    if (turn < this.drawnRefresh) return
    this.drawnRefresh = turn
    if (data) this.data = this.withFallbackAnswers(data, turn)
    this.draw()
  }

  // A row the call answered is newer than a snapshot asked for before that answer
  withFallbackAnswers(data, turn) {
    const hosts = data.hosts.map((host) => {
      const answer = this.fallbackAnswers.get(host.host)
      return answer && turn < answer.firstReload ? { ...host, ...answer.row } : host
    })
    for (const [name, answer] of this.fallbackAnswers) if (turn >= answer.firstReload) this.fallbackAnswers.delete(name)
    return { ...data, hosts }
  }

  say(key, params = {}, error = false) {
    this.notice = { key, params, error }
  }

  // Drops the notice and hides it in place, without a redraw that would give a held button back
  clearNotice() {
    this.notice = null
    const shown = this.el.querySelector('.cf-notice')
    if (shown) {
      shown.hidden = true
      shown.textContent = ''
    }
  }

  sayRefusal(error) {
    const { key, params } = refusalText(error)
    this.say(key, params, true)
  }

  // --- The whole page -------------------------------------------------------------------------------------------------

  // What a row's address field holds is read nowhere until it is saved, and a redraw would wipe it
  keepTyping() {
    for (const host of this.fallbackTyping.keys()) {
      const input = this.el.querySelector(`.cf-fallback-address[data-host="${CSS.escape(host)}"]`)
      if (input) this.fallbackTyping.set(host, input.value)
    }
  }

  draw() {
    this.keepTyping()
    const { h } = this.ctx.ui
    this.el.replaceChildren(
      this.head(),
      ...this.banners(),
      h(
        'p',
        { class: this.notice?.error ? 'cf-notice cf-notice-error' : 'cf-notice', role: 'status', hidden: !this.notice },
        this.notice ? this.t(this.notice.key, this.notice.params) : '',
      ),
      this.domains(),
    )
  }

  head() {
    const { h, chip, button } = this.ctx.ui
    const { state } = this.data
    const token = tokenView(state.token)
    const chips = this.tokenShown ? [] : [chip({ text: this.t(token.chip), level: token.level, class: 'cf-token' })]
    for (const account of quotaChipAccounts(state)) {
      const quota = account.quota
      chips.push(
        chip({
          text: this.t('cloudflare.quota_chip', { account: account.name, used: this.count(quota.used), limit: this.count(quota.limit) }),
          level: quotaLevel(quota),
          class: 'cf-quota',
        }),
      )
    }
    const counts = state.counts
    if (counts.pending) chips.push(chip({ text: this.t(byCount(counts.pending, '', 'cloudflare.count_pending_one', 'cloudflare.count_pending_many'), { count: String(counts.pending) }), level: 'info' }))
    if (counts.error) chips.push(chip({ text: this.t(byCount(counts.error, '', 'cloudflare.count_error_one', 'cloudflare.count_error_many'), { count: String(counts.error) }), level: 'danger' }))
    const usable = state.token.state === 'ok'
    return h(
      'div',
      { class: 'cf-head' },
      h('img', { class: 'cf-mark', src: MARK, alt: '', width: 40, height: 40 }),
      h('div', { class: 'cf-head-text' }, h('p', { class: 'cf-intro' }, this.t('cloudflare.intro')), h('div', { class: 'cf-chips' }, chips)),
      h(
        'div',
        { class: 'cf-head-actions' },
        button({ text: this.t('cloudflare.sync_now'), disabled: !usable, class: 'cf-sync', onClick: (event) => this.syncNow(event.currentTarget) }),
        button({ text: this.t('cloudflare.resync'), disabled: !usable, class: 'cf-resync', onClick: (event) => this.resync(event.currentTarget) }),
      ),
    )
  }

  banners() {
    const { h } = this.ctx.ui
    const { state } = this.data
    const lines = this.tokenShown ? [] : [...tokenView(state.token).banners]
    const live = liveHosts(this.data.hosts)
    if (live.length) lines.push({ level: 'warning', key: 'cloudflare.hosts_live_text', params: { hosts: live.join(', ') } })
    for (const account of state.accounts) {
      const quota = account.list ? quotaBanner(account, this.t('cloudflare.digit_group')) : null
      if (quota) lines.push(quota)
      const reason = errorText(account.last_error)
      if (reason) {
        lines.push({ level: 'danger', key: 'cloudflare.account_error', params: { account: account.name }, reason })
      }
    }
    return lines.map((line) =>
      h(
        'div',
        { class: `cf-banner cf-banner-${line.level}`, role: line.level === 'danger' ? 'alert' : null },
        h('span', { class: `dot dot-${line.level}` }),
        h(
          'p',
          {},
          this.t(line.key, line.params ?? {}),
          line.reason ? [' ', this.t(line.reason.key, line.reason.params)] : null,
          line.reason?.detail ? h('span', { class: 'cf-error-detail' }, line.reason.detail) : null,
          line.settings ? [' ', this.tokenLink()] : null,
        ),
      ),
    )
  }

  // A link to the token's row of the same tab: it focuses the row's control, so the address never changes
  tokenLink() {
    const { h } = this.ctx.ui
    return h(
      'a',
      {
        href: `#${TOKEN_ANCHOR}`,
        class: 'cf-settings-link',
        onclick: (event) => {
          event.preventDefault()
          this.toToken()
        },
      },
      this.t('cloudflare.to_token'),
    )
  }

  // A number of list items as this language writes it
  count(value) {
    return groupDigits(value, this.t('cloudflare.digit_group'))
  }

  // --- Sync now and Compare -----------------------------------------------------------------------------------------

  async syncNow(control) {
    control.disabled = true
    try {
      await this.ctx.api('sync.now', { json: {} })
      this.say('cloudflare.notice_sync')
    } catch (error) {
      if (isLeaving(error)) return
      this.sayRefusal(error)
    }
    await this.refresh()
  }

  async resync(control) {
    control.disabled = true
    let compare
    try {
      compare = await this.ctx.api('resync.compare')
    } catch (error) {
      if (isLeaving(error)) return
      this.sayRefusal(error)
      this.draw()
      return
    }
    if (gapCount(compare) === 0) {
      this.say('cloudflare.resync_clean')
      this.draw()
      return
    }
    // An earlier notice, such as "in sync", no longer holds once this compare found gaps, even if the dialog is cancelled
    this.clearNotice()
    const ticks = defaultTicks(compare)
    const go = await this.ctx.ui.confirm({
      title: this.t('cloudflare.resync_title'),
      text: this.t('cloudflare.resync_text'),
      body: () => this.resyncBody(compare, ticks),
      confirm: this.t('cloudflare.resync_apply'),
      danger: false,
    })
    if (!go || (!ticks.push.size && !ticks.remove.size)) {
      this.draw()
      return
    }
    if (ticks.remove.size) {
      const count = String(ticks.remove.size)
      const sure = await this.ctx.ui.confirm({
        title: this.t(byCount(ticks.remove.size, '', 'cloudflare.remove_title_one', 'cloudflare.remove_title_many'), { count }),
        text: this.t('cloudflare.remove_text', { count }),
        confirm: this.t(byCount(ticks.remove.size, '', 'cloudflare.remove_confirm_one', 'cloudflare.remove_confirm_many'), { count }),
      })
      if (!sure) {
        this.draw()
        return
      }
    }
    try {
      const done = await this.ctx.api('resync.apply', { json: resyncBody(compare, ticks) })
      this.say('cloudflare.resync_done', { pushed: String(done.pushed), removed: String(done.queued_removals) })
    } catch (error) {
      if (isLeaving(error)) return
      this.sayRefusal(error)
    }
    await this.refresh()
  }

  resyncBody(compare, ticks) {
    const { h } = this.ctx.ui
    const accounts = new Map(this.data.state.accounts.map((account) => [account.id, account.name]))
    const tick = (set, id, label, extra) =>
      h(
        'label',
        { class: 'cf-tick' },
        h('input', {
          type: 'checkbox',
          checked: set.has(id),
          onchange: (event) => (event.target.checked ? set.add(id) : set.delete(id)),
        }),
        h('span', { class: 'cf-tick-text' }, h('span', { class: 'mono cf-tick-main' }, label), extra),
      )
    const groups = []
    for (const account of compare.accounts) {
      const rows = []
      for (const id of account.missing) {
        rows.push(tick(ticks.push, id, resyncLabel(account.sources, id), h('span', { class: 'cf-tick-note' }, this.t('cloudflare.gap_missing'))))
      }
      for (const row of account.differs) {
        const note = this.t('cloudflare.gap_differs', { remote: `${row.remote.status_code} ${visibleUrl(row.remote.target_url)}` })
        rows.push(tick(ticks.push, row.id, resyncLabel(account.sources, row.id), h('span', { class: 'cf-tick-note' }, note)))
      }
      for (const row of account.extra) {
        const note = h(
          'span',
          { class: 'cf-tick-note' },
          this.ctx.ui.chip({ text: this.t(row.ours ? 'cloudflare.gap_ours' : 'cloudflare.gap_foreign'), level: row.ours ? 'info' : 'warning' }),
          ' ',
          this.t('cloudflare.gap_extra', { target: `${row.status_code} ${visibleUrl(row.target_url)}` }),
        )
        rows.push(tick(ticks.remove, row.remote_id, visibleUrl(row.source_url), note))
      }
      if (!rows.length) continue
      groups.push(h('section', { class: 'cf-gap-group' }, h('h3', { class: 'label' }, accounts.get(account.account_id) ?? account.account_id), rows))
    }
    return h('div', { class: 'cf-gaps' }, groups)
  }

  // --- Domains --------------------------------------------------------------------------------------------------------

  domains() {
    const { h, card, table, button, chip } = this.ctx.ui
    const accounts = new Map(this.data.state.accounts.map((account) => [account.id, account.name]))
    const usable = this.data.state.token.state === 'ok'
    const add = button({ text: this.t('cloudflare.new_host'), variant: 'accent', disabled: !usable, class: 'cf-new-host', onClick: () => this.newHost() })
    const hosts = this.data.hosts
    const content = hosts.length
      ? table({
          columns: [this.t('cloudflare.col_host'), this.t('cloudflare.col_fallback'), this.t('cloudflare.col_zone'), this.t('cloudflare.col_account'), this.t('cloudflare.col_record'), this.t('cloudflare.col_added')],
          grid: 'minmax(0, 1.3fr) 210px minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.2fr) minmax(0, 1fr)',
          // No minWidth here: cloudflare.css holds it, as a phone stacks each row instead of scrolling
          rows: hosts.map((host) => [
            h('span', { class: 'mono cf-url' }, host.host),
            this.fallbackSelect(host, usable),
            h('span', { class: 'cf-small' }, host.zone_name),
            h('span', { class: 'cf-small' }, accounts.get(host.account_id) ?? host.account_id),
            chip({ text: this.t(host.created_by_us ? 'cloudflare.record_created' : 'cloudflare.record_existing'), level: host.created_by_us ? 'info' : 'success' }),
            h('span', { class: 'mono cf-small cf-muted' }, formatTime(host.created_at)),
          ]),
        })
      : h('p', { class: 'cf-none' }, this.t('cloudflare.hosts_none'))
    return h(
      'div',
      { class: 'cf-tab' },
      h('p', { class: 'cf-intro cf-tab-intro' }, this.t('cloudflare.domains_intro')),
      card({ title: this.t('cloudflare.hosts_title'), actions: [add], body: false, class: 'cf-list-card cf-hosts' }, content),
    )
  }

  // A host's page for unknown paths, and what stops it from being there. Its label shows only where a phone hides the head
  // of the table. Held on the choice being sent while that host's own call runs, through any redraw
  fallbackSelect(host, usable) {
    const { h, select } = this.ctx.ui
    if (!fallbackOffered(host)) {
      return h(
        'div',
        { class: 'cf-fallback' },
        h('span', { class: 'cf-fallback-label' }, this.t('cloudflare.col_fallback')),
        h('p', { class: 'cf-fallback-none' }, this.t('cloudflare.fallback_none')),
      )
    }
    const sending = this.fallbackCalls.get(host.host)
    const blocked = fallbackBlockedKey(host)
    const label = this.t('cloudflare.col_fallback')
    const shown = sending ?? (this.fallbackTyping.has(host.host) ? 'other' : fallbackOf(host.fallback))
    const box = select({
      label: h('span', { class: 'cf-fallback-label' }, label),
      name: 'fallback',
      value: shown,
      disabled: !usable || sending !== undefined,
      options: FALLBACK_CHOICES.map((choice) => ({ value: choice.id, text: this.t(choice.key) })),
      onChange: (event) => this.pickFallback(host, event.currentTarget),
    })
    const control = box.querySelector('select')
    control.setAttribute('aria-label', this.t('cloudflare.fallback_label', { host: host.host }))
    control.dataset.host = host.host
    return h(
      'div',
      { class: 'cf-fallback' },
      box,
      shown === 'other' ? this.fallbackOther(host, usable && sending === undefined) : null,
      blocked ? h('p', { class: 'cf-fallback-blocked' }, this.t(blocked)) : null,
    )
  }

  // The field for an address of the user's own, on the row that chose it: it goes when saved, never as it is typed
  fallbackOther(host, usable) {
    const { h, button } = this.ctx.ui
    const known = this.fallbackTyping.get(host.host) ?? (fallbackOf(host.fallback) === 'other' ? host.fallback : '')
    const input = h('input', {
      class: 'input mono cf-fallback-address',
      type: 'url',
      name: 'fallback_address',
      value: known,
      placeholder: 'https://',
      disabled: !usable,
      'aria-label': this.t('cloudflare.fallback_address_label', { host: host.host }),
      'aria-invalid': this.fallbackRefused.has(host.host) ? 'true' : null,
      oninput: () => this.fallbackTyping.set(host.host, input.value),
    })
    input.dataset.host = host.host
    const save = button({
      text: this.t('cloudflare.fallback_save'),
      class: 'cf-fallback-save',
      disabled: !usable,
      onClick: () => {
        this.fallbackTyping.set(host.host, input.value)
        this.changeFallback(host, 'other', input.value.trim())
      },
    })
    save.dataset.host = host.host
    return h('div', { class: 'cf-fallback-other' }, input, save)
  }

  pickFallback(host, control) {
    const id = control.value
    if (id === 'other') {
      this.fallbackTyping.set(host.host, '')
      this.draw()
      // The redraw took the select away: the focus goes on to the field it just showed
      this.el.querySelector(`.cf-fallback-address[data-host="${CSS.escape(host.host)}"]`)?.focus()
      return
    }
    this.fallbackTyping.delete(host.host)
    this.changeFallback(host, id, fallbackTarget(id))
  }

  // A call holds its row from the moment it starts, with no redraw, as nothing else would until one comes
  holdFallback(name) {
    const host = `[data-host="${CSS.escape(name)}"]`
    for (const control of [`.cf-fallback select${host}`, `.cf-fallback-address${host}`, `.cf-fallback-save${host}`]) {
      const found = this.el.querySelector(control)
      if (found) found.disabled = true
    }
  }

  // Held until the call has answered. The redraw shows what the server holds, so a refused choice goes back by itself. An
  // accepted one holds even if the reload after it fails, from the call's own answer. Every redraw drops the focus, which
  // goes back to the host changed last: an answer that comes late for another host does not take it, and neither does one
  // that comes after the user moved on to the shell around the page, whose focus the redraw leaves alone. One call per row:
  // a second would be freed by the first one's answer, and that answer would wipe what is typed meanwhile
  async changeFallback(host, id, target) {
    if (this.fallbackCalls.has(host.host)) return
    this.fallbackCalls.set(host.host, id)
    this.holdFallback(host.host)
    this.lastFallback = host.host
    this.fallbackRefused.delete(host.host)
    try {
      const row = await this.ctx.api('hosts.fallback', { id: host.host, json: fallbackBody(target) })
      // An answer that names no row says nothing was kept: it goes as a failed call, which leaves the typed address alone
      if (row?.host !== host.host) throw new Error('the answer names no row')
      this.fallbackTyping.delete(host.host)
      this.fallbackAnswers.set(host.host, { row, firstReload: this.refreshes + 1 })
      this.data = { ...this.data, hosts: this.data.hosts.map((known) => (known.host === host.host ? { ...known, ...row } : known)) }
      this.say(fallbackNoticeKey(row), { host: host.host, choice: this.fallbackWords(row.fallback) })
    } catch (error) {
      if (isLeaving(error)) return
      const { key, params } = fallbackRefusalText(error)
      this.say(key, params, true)
      // Only a refusal of the address itself calls it invalid: an outage or a host gone says nothing about it
      if (id === 'other' && (error?.fields?.fallback || error?.fields?.target)) this.fallbackRefused.add(host.host)
    } finally {
      this.fallbackCalls.delete(host.host)
    }
    await this.refresh()
    const active = document.activeElement
    if (active && active !== document.body && !this.el.contains(active)) return
    // A refused address is there to be corrected, so the focus goes to its field
    const name = CSS.escape(this.lastFallback)
    const field = this.fallbackRefused.has(this.lastFallback) ? `.cf-fallback-address[data-host="${name}"]` : `.cf-fallback select[data-host="${name}"]`
    this.el.querySelector(field)?.focus()
  }

  fallbackWords(target) {
    if (!target) return ''
    const { key, text } = fallbackName(target)
    return key ? this.t(key) : text
  }

  // The New host dialog: a zone, a name among the proposals or typed, then the plan, which alone can be confirmed
  async newHost() {
    let zones
    try {
      zones = (await this.ctx.api('zones.list')).zones
    } catch (error) {
      if (isLeaving(error)) return
      this.sayRefusal(error)
      this.draw()
      return
    }
    let plan = null
    let chosen = null
    const go = await this.ctx.ui.confirm({
      title: this.t('cloudflare.new_host_title'),
      text: this.t('cloudflare.new_host_text'),
      held: true,
      danger: false,
      confirm: this.t('cloudflare.new_host_confirm'),
      body: (allow) =>
        this.hostDialog(zones, (found, request, liveTicked = false) => {
          plan = found
          chosen = request
          allow(planConfirmable(found, liveTicked))
        }),
    })
    if (!go || !plan) return
    try {
      const made = await this.ctx.api('dns.apply', { json: applyBody(chosen, plan) })
      this.say('cloudflare.notice_host', { host: made.host.host })
    } catch (error) {
      if (isLeaving(error)) return
      this.sayRefusal(error)
    }
    await this.refresh()
  }

  hostDialog(zones, planned) {
    const { h, select, button, chip, field } = this.ctx.ui
    const proposalsBox = h('div', { class: 'cf-proposals' })
    const planBox = h('div', { class: 'cf-plan', hidden: true })
    const errorBox = h('p', { class: 'form-error', hidden: true })
    let zoneId = zones[0]?.id ?? ''
    // Each request for proposals or a plan takes a turn; an answer whose turn has passed is dropped, so the dialog only
    // shows, and Confirm only sends, what the last request asked for, whatever order the answers come back in
    let proposalTurn = 0
    let planTurn = 0
    const fail = (error) => {
      if (isLeaving(error)) return
      const { key, params } = refusalText(error)
      errorBox.textContent = this.t(key, params)
      errorBox.hidden = false
    }
    const typed = field({ label: this.t('cloudflare.f_label'), name: 'label', mono: true, placeholder: 'go', help: this.t('cloudflare.f_label_help') })
    const labelInput = typed.querySelector('input')
    // Nothing by default: what the plan is asked for is what the user chose here, sent with it and bound to its confirmation
    const pageField = select({
      label: this.t('cloudflare.col_fallback'),
      name: 'fallback',
      value: 'none',
      options: FALLBACK_CHOICES.map((choice) => ({ value: choice.id, text: this.t(choice.key) })),
      onChange: () => {
        const other = pageChoice() === 'other'
        addressBox.hidden = !other
        if (!other && lastLabel) {
          showPlan(lastLabel)
          return
        }
        // The plan shown is for another page: nothing can be confirmed until one is asked for this address, once typed
        planTurn += 1
        planned(null, null)
        planBox.hidden = true
      },
    })
    const pageChoice = () => pageField.querySelector('select').value
    const addressInput = h('input', {
      class: 'input mono cf-fallback-address',
      type: 'url',
      name: 'fallback_address',
      placeholder: 'https://',
      'aria-label': this.t('cloudflare.fallback_address_new'),
      onchange: () => {
        if (lastLabel) showPlan(lastLabel)
      },
    })
    const addressBox = h('div', { class: 'cf-fallback-other', hidden: true }, addressInput)
    let lastLabel = null
    const showPlan = async (label) => {
      lastLabel = label
      const turn = ++planTurn
      errorBox.hidden = true
      planned(null, null)
      planBox.hidden = true
      for (const radio of proposalsBox.querySelectorAll('input')) radio.checked = radio.value === label
      // The zone and the name are bound to this request, never read again once it answers
      const request = { zone_id: zoneId, label, fallback: fallbackTarget(pageChoice(), addressInput.value.trim()) }
      try {
        const found = await this.ctx.api('dns.plan', { json: { ...request } })
        if (turn !== planTurn) return
        planBox.replaceChildren(...this.planLines(found, (ticked) => planned(found, request, ticked)))
        planBox.hidden = false
        planned(found, request)
      } catch (error) {
        if (turn !== planTurn) return
        if (error?.fields?.label) {
          labelInput.setAttribute('aria-invalid', 'true')
          const slot = typed.querySelector('.field-error')
          slot.textContent = this.t(error.fields.label)
          slot.hidden = false
          return
        }
        const reason = error?.fields?.fallback ?? error?.fields?.target
        if (reason) {
          errorBox.textContent = this.t(reason)
          errorBox.hidden = false
          return
        }
        fail(error)
      }
    }
    const loadProposals = async () => {
      // A new zone ends whatever was asked for the previous one, its plan included
      const turn = ++proposalTurn
      planTurn += 1
      planned(null, null)
      planBox.hidden = true
      errorBox.hidden = true
      proposalsBox.replaceChildren()
      if (!zoneId) return
      try {
        const found = await this.ctx.api('dns.proposals', { query: { zone: zoneId } })
        if (turn !== proposalTurn) return
        proposalsBox.replaceChildren(
          ...found.proposals.map((proposal) => {
            const view = verdictView(proposal.verdict)
            const open = proposalOpen(proposal)
            return h(
              'label',
              { class: open ? 'cf-proposal' : 'cf-proposal cf-proposal-off' },
              h('input', { type: 'radio', name: 'proposal', value: proposal.label, disabled: !open, onchange: () => showPlan(proposal.label) }),
              h('span', { class: 'mono cf-proposal-name' }, proposal.fqdn),
              chip({ text: this.t(view.key), level: view.level }),
            )
          }),
        )
      } catch (error) {
        if (turn !== proposalTurn) return
        fail(error)
      }
    }
    const zoneField = select({
      label: this.t('cloudflare.f_zone'),
      name: 'zone',
      value: zoneId,
      options: zones.map((zone) => ({ value: zone.id, text: `${zone.name} · ${zone.account_name}` })),
      onChange: (event) => {
        zoneId = event.target.value
        loadProposals()
      },
    })
    const typedLine = h(
      'div',
      { class: 'cf-typed' },
      typed,
      button({
        text: this.t('cloudflare.show_plan'),
        class: 'cf-show-plan',
        onClick: () => {
          labelInput.removeAttribute('aria-invalid')
          typed.querySelector('.field-error').hidden = true
          showPlan(labelInput.value.trim().toLowerCase())
        },
      }),
    )
    loadProposals()
    return h(
      'div',
      { class: 'cf-host-dialog' },
      zones.length ? zoneField : h('p', { class: 'cf-muted' }, this.t('cloudflare.zones_none')),
      h('p', { class: 'label' }, this.t('cloudflare.proposals')),
      proposalsBox,
      typedLine,
      pageField,
      addressBox,
      errorBox,
      planBox,
    )
  }

  planLines(plan, liveTicked) {
    const { h } = this.ctx.ui
    const lines = [h('h3', { class: 'label' }, this.t('cloudflare.plan_title', { host: plan.fqdn }))]
    if (plan.steps.length) {
      lines.push(
        h(
          'ol',
          { class: 'cf-steps' },
          plan.steps.map((step) => {
            const { key, params } = stepText(step)
            return h('li', {}, this.t(key, params))
          }),
        ),
      )
    }
    const blocked = blockedKey(plan.blocked)
    if (blocked) lines.push(h('p', { class: 'cf-plan-blocked', role: 'alert' }, this.t(blocked, { host: plan.fqdn })))
    else if (plan.live) {
      lines.push(
        h('p', { class: 'cf-plan-live', role: 'alert' }, this.t('cloudflare.plan_live', { host: plan.fqdn })),
        h(
          'label',
          { class: 'cf-tick cf-plan-live-tick' },
          h('input', { type: 'checkbox', name: 'confirm_live', onchange: (event) => liveTicked(event.target.checked) }),
          h('span', { class: 'cf-tick-text' }, this.t('cloudflare.plan_live_confirm')),
        ),
      )
    }
    return lines
  }
}

// Cloudflare off: what turns it on, in the place of the domains, as the base said a plugin waits for its settings
function drawOff(el, ctx, toToken) {
  const { h, button } = ctx.ui
  const mark = crescentMark()
  mark.classList.add('state-mark')
  el.replaceChildren(
    h(
      'section',
      { class: 'card state-card cf-off' },
      mark,
      h('h2', { class: 'state-title' }, ctx.t('cloudflare.off_title')),
      h('p', { class: 'state-desc' }, ctx.t('cloudflare.off_desc')),
      button({ text: ctx.t('cloudflare.to_token'), variant: 'accent', class: 'cf-to-token', onClick: toToken }),
    ),
  )
}

// Draws the domains in `el`, from what loadDomains read. `options` go to the Page.
export function mountDomains(el, data, ctx, options = {}) {
  if (!data.state.enabled) drawOff(el, ctx, options.toToken)
  else new Page(el, data, ctx, options).draw()
}
