// Source: Moonie Redirect 7.0.1 admin UI, ui/pages/plugins.js, its detail tabs: the tab in the address,
// so Back and a reload keep it. Added: the three tabs of this app's settings, each read when it is shown.
// The Settings page: Security, Webhook & API, Cloudflare (its settings and its domains, D29).

import { takeKept } from './common.js'
import { drawCloudflare } from './settings-cloudflare.js'
import { TABS, readable, tabAddress, tabFrom } from './settings-logic.js'
import { drawSecurity } from './settings-security.js'
import { drawWebhook } from './settings-webhook.js'

// What each tab reads before it is drawn
const LOADS = {
  security: (ctx) => ctx.api('admin.security'),
  webhook: async (ctx) => {
    const [webhook, keys] = await Promise.all([ctx.api('admin.webhook'), ctx.api('admin.keys')])
    return { webhook, keys }
  },
  // The token and limit, and the domains under them (D29)
  cloudflare: async (ctx) => {
    const [settings, state] = await Promise.all([ctx.api('admin.cloudflare'), ctx.api('cf.state')])
    return { settings, domains: { state, hosts: state?.hosts } }
  },
}

const DRAWS = { security: drawSecurity, webhook: drawWebhook, cloudflare: drawCloudflare }

// The tab chosen by a press: the next draw gives it the focus back, which the page's loading took
let focusTab = null

async function load(ctx) {
  const tab = tabFrom(ctx.query)
  const data = await LOADS[tab](ctx)
  // A proxy's page answered 200 reaches here as null or as anything else: what no draw can read is a load that failed
  if (!readable(tab, data)) throw new Error(`the ${tab} settings came back unreadable`)
  return { tab, data }
}

function render(el, { tab, data }, ctx) {
  const { h, tabs } = ctx.ui
  const kept = takeKept()
  const panel = h('div', { class: 'settings-panel', role: 'tabpanel', 'aria-label': ctx.t(TABS.find((item) => item.id === tab).label) })
  const bar = tabs({
    items: TABS.map((item) => ({ id: item.id, text: ctx.t(item.label) })),
    active: tab,
    label: ctx.t('settings.page'),
    onSelect: (id) => {
      if (id === tab) return
      focusTab = id
      ctx.navigate(tabAddress(location.search, id))
    },
  })
  el.append(h('div', { class: 'settings-page' }, bar, panel))
  DRAWS[tab](panel, data, ctx, { kept })
  if (focusTab === tab) bar.querySelector('[aria-selected="true"]')?.focus({ preventScroll: true })
  focusTab = null
}

export default { load, render }
