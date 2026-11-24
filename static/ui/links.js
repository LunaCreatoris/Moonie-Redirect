// Source: Moonie Redirect 7.0.1 admin UI, system/redirect/ui/links.js, trimmed: zones (filters, columns, row actions, form),
// optimistic concurrency, drafts kept across a login. Added: the Cloudflare address (field and column).
// The Links page: a list on the left, and on the right the form of the selected link or of a new one. The address holds
// which one, so that a reload comes back to the link that was typed on.

import {
  addressCell,
  addressField,
  addressWith,
  askToDiscard,
  bringIntoView,
  clearFormErrors,
  clearNotice,
  clearFormTop,
  confirmDelete,
  deletedForGood,
  deleteOptions,
  copyButton,
  drawsNew,
  fieldWithAction,
  formatTime,
  formTitle,
  focusPage,
  isGone,
  isLeaving,
  keepForNextDraw,
  linkCell,
  matchesTelling,
  noRowsKey,
  noticeLine,
  pageHead,
  pageMemory,
  restoreTypedFields,
  savedLink,
  sharedUrl,
  showFormError,
  submitting,
  takeKept,
  typedFields,
  typedSince,
  withAddress,
} from './common.js'
import { addressChoices } from './cloudflare-logic.js'

const COUNT_TEXTS = ['redirect.count_links_none', 'redirect.count_links_one', 'redirect.count_links_many']

// Wide enough for every column at a 1440 px window, Copy included: the time takes two lines there, and one when the table has room.
// The pages offer no status code (decision D20), so the list has no Code column.
const GRID = ['minmax(146px, 1.3fr)', 'minmax(170px, 1.6fr)', '84px', 'minmax(92px, 160px)', '84px'].join(' ')
const MIN_WIDTH = 656
const OWN_FIELDS = ['name', 'slug', 'target', 'address', 'expires_on']
// Every public address holds this, and would answer a search for it on every row
const SEARCHED = { name: [], slug: [], target: [], public_url: ['/redirect/'] }

// Which link the form was on, since an address with no `link` shows the first of the list, and a slug the instance
// suggested, which is nobody's typing.
const memory = pageMemory()

export function matchesLink(link, search) {
  return matchesTelling(link, search, SEARCHED)
}

async function suggestedSlug(ctx) {
  try {
    const { slug } = await ctx.api('links.suggest')
    return typeof slug === 'string' ? slug : ''
  } catch {
    return ''
  }
}

// What a save sends. Never `http_status`: a new link takes the server's 302, and an edit keeps the stored code, a 301
// set through the API included (decision D20).
export function linkBody(form) {
  const value = (name) => form.querySelector(`[name="${name}"]`).value
  return {
    name: value('name'),
    slug: value('slug'),
    target: value('target'),
    expires_on: value('expires_on').trim() || null,
  }
}

// The note an edit form shows when the link answers something other than the pages' 302, so a save never changes it
// unseen: the text's key, or null
export function statusNoteKey(link) {
  return link && link.http_status !== 302 ? 'redirect.status_kept' : null
}

function linkCells(ctx, link, showAddress) {
  const { h } = ctx.ui
  const cell = linkCell(ctx, link)
  // With Cloudflare on, where the link answers goes under its name: a column more would push Copy out of the card
  if (showAddress) cell.append(addressCell(ctx, link))
  return [
    cell,
    h('span', { class: 'mono redirect-target' }, link.target),
    h('span', { class: 'mono redirect-expires' }, link.expires_on ?? '—'),
    h('span', { class: 'mono redirect-modified' }, formatTime(link.updated_at)),
    h('div', { class: 'redirect-row-actions' }, copyButton(ctx, sharedUrl(link, link.public_url), `/redirect/${link.slug}`)),
  ]
}

export default {
  async load(ctx) {
    const listed = await ctx.api('links.list')
    return { links: listed.links, addresses: listed.addresses, creating: ctx.query.get('new') === '1' }
  },
  render(el, data, ctx) {
    const { button, card, field, h, table } = ctx.ui
    const { links, addresses } = data
    const showAddress = Boolean(addressChoices(addresses))
    const carried = takeKept()
    let query = ctx.query
    let address = `${location.pathname}${location.search}`
    const before = memory.takeShown(address)
    // A new form stays one, even at an address that does not ask for it
    const creating = drawsNew(data.creating, before)
    const wanted = query.get('link') ?? before?.id
    let selected = creating ? null : (links.find((link) => link.id === wanted) ?? links[0])
    // The form this draw comes back to has gone, with what was typed on it: that text must not land on another link
    const cameFor = before?.id ?? carried?.on
    const formGone = Boolean(cameFor) && !creating && selected?.id !== cameFor
    // A save or a delete on its way: the form on screen is the one it answers to, so nothing moves away from it
    let working = false
    let moved = false
    let left = false
    let editing = null
    const listRows = async () => (await ctx.api('links.list'))?.links

    const moveTo = (changes) => {
      query = new URLSearchParams(addressWith('', query, changes).slice(1))
      ctx.address(addressWith(location.pathname, query, {}))
      address = `${location.pathname}${location.search}`
    }

    // --- List

    const listHost = h('div', {})
    const noMatch = h('p', { class: 'small redirect-none' })

    const search = h('input', {
      class: 'input redirect-search',
      name: 'search',
      value: carried?.search ?? '',
      placeholder: ctx.t('redirect.search'),
      'aria-label': ctx.t('redirect.search'),
      autocomplete: 'off',
      oninput: () => applySearch(),
    })

    // The rows a full draw made, by link. A key in the search only takes rows out and puts them back, so that the cost of
    // drawing never comes at each key, however long the list is.
    let rowOf = new Map()
    let rowsParent = null

    const applySearch = () => {
      const shown = links.filter((link) => matchesLink(link, search.value))
      const wantedRows = new Set(shown.map((link) => rowOf.get(link.id)))
      for (const row of rowOf.values()) {
        if (!wantedRows.has(row)) row.remove()
      }
      // The rows keep the order of the list: only those coming back are placed
      let next = rowsParent.firstElementChild.nextElementSibling
      for (const link of shown) {
        const row = rowOf.get(link.id)
        if (row === next) next = next.nextElementSibling
        else rowsParent.insertBefore(row, next)
      }
      noMatch.textContent = shown.length ? '' : ctx.t(noRowsKey(links.length, 'redirect.none_match', 'redirect.none_yet'))
      if (shown.length) noMatch.remove()
      else listHost.append(noMatch)
    }

    // Which link's row holds the focus, and whether on its Copy
    const focusInList = () => {
      const active = document.activeElement
      if (!active || !listHost.contains(active)) return null
      const row = active.closest('[role="row"]')
      for (const [id, drawn] of rowOf) {
        if (drawn === row) return { id, copy: active.classList.contains('redirect-copy') }
      }
      return null
    }

    // The rows go and come back: the row holding the focus keeps it, and the table stays where it was scrolled
    const drawList = () => {
      const focused = focusInList()
      const scrolled = listHost.querySelector('.table')?.scrollLeft ?? 0
      const drawn = table({
        columns: [
          ctx.t('redirect.col_link'),
          ctx.t('redirect.col_target'),
          ctx.t('redirect.col_expires'),
          ctx.t('redirect.col_modified'),
          '',
        ],
        rows: links.map((link) => ({
          cells: linkCells(ctx, link, showAddress),
          selected: link.id === selected?.id,
          onClick: () => pressRow(link),
        })),
        grid: GRID,
        minWidth: MIN_WIDTH,
      })
      rowsParent = drawn.querySelector('[role="table"]')
      const drawnRows = [...rowsParent.children].slice(1)
      rowOf = new Map(links.map((link, index) => [link.id, drawnRows[index]]))
      listHost.replaceChildren(drawn)
      applySearch()
      drawn.scrollLeft = scrolled
      if (focused) focusRow(focused.id, focused.copy)
    }

    const focusRow = (id, onCopy = false) => {
      const row = rowOf.get(id)
      if (!row?.isConnected) return
      ;(onCopy ? row.querySelector('.redirect-copy') : row).focus({ preventScroll: true })
    }

    // --- Form

    const formHost = h('div', { class: 'redirect-form-host' })

    // Goes nowhere once the page has been left: the page on screen is another one, and what is kept would wait for a later visit
    const leaveWith = (said, changes) => {
      if (left) return
      moved = true
      keepForNextDraw(said)
      moveTo(changes)
      ctx.reload()
    }

    const drawForm = (link) => {
      const original = link?.slug
      // A slug nobody typed is nothing to lose on a new form: the instance suggests one, and Random draws another
      let givenSlug = null
      const nameField = field({ label: ctx.t('redirect.f_name'), name: 'name', value: link?.name ?? '', autocomplete: 'off' })
      const preview = h('span', { class: 'mono field-help redirect-slug-preview', id: 'redirect-slug-preview' })
      const warning = h('span', { class: 'redirect-slug-warning', 'aria-live': 'polite' })

      const random = button({
        text: ctx.t('redirect.random'),
        class: 'redirect-random',
        onClick: async () => {
          if (working) return
          clearFormTop(form)
          try {
            const { slug } = await ctx.api('links.suggest')
            // A save on its way would read it as typed meanwhile, and a form gone has nothing to show it on
            if (working || !form.isConnected) return
            if (typeof slug !== 'string') throw { status: 200, code: null }
            slugInput().value = slug
            if (!link) givenSlug = slug
            followSlug()
          } catch (error) {
            if (!isLeaving(error) && !working && form.isConnected) showFormError(form, error, ctx.t)
          }
        },
      })
      const slugField = fieldWithAction(ctx, {
        label: ctx.t('redirect.f_slug'),
        id: 'redirect-slug',
        name: 'slug',
        value: link?.slug ?? '',
        mono: true,
        action: random,
        help: preview,
      })
      slugField.append(warning)
      const slugInput = () => form.querySelector('[name="slug"]')
      const followSlug = () => {
        const slug = slugInput().value.trim()
        preview.textContent = `/redirect/${slug}`
        // Text only while it holds, so a screen reader hears it when it comes
        warning.textContent = link && slug !== original ? ctx.t('redirect.slug_warning') : ''
      }

      const deleteButton =
        link && button({ text: ctx.t('redirect.delete'), variant: 'danger', class: 'redirect-delete', onClick: remove })
      const cancelButton = button({ text: ctx.t('common.cancel'), class: 'redirect-cancel', onClick: cancel })
      const saveButton = button({ text: ctx.t('common.save'), variant: 'accent', type: 'submit', class: 'redirect-save' })

      const form = h(
        'form',
        {
          class: 'redirect-form',
          novalidate: true,
          oninput: (event) => {
            if (event.target.name !== 'slug') return
            followSlug()
            // The address's help names the path, which the slug makes
            form.querySelector('[name="address"]')?.dispatchEvent(new Event('input'))
          },
          onsubmit: (event) => {
            event.preventDefault()
            if (working) return undefined
            return submitting(form, save, ctx.t, saveButton)
          },
        },
        formTitle(ctx, link ? ctx.t('redirect.form_edit', { path: `/redirect/${link.slug}` }) : ctx.t('redirect.new')),
        h('p', { class: 'form-error', role: 'alert', hidden: true }),
        nameField,
        slugField,
        field({ label: ctx.t('redirect.f_target'), name: 'target', value: link?.target ?? '', mono: true, autocomplete: 'off' }),
        addressField(ctx, {
          link,
          addresses,
          path: () => slugField.querySelector('[name="slug"]').value.trim(),
          lanPath: () => `/redirect/${slugField.querySelector('[name="slug"]').value.trim()}`,
        }),
        field({
          label: ctx.t('redirect.f_expires'),
          name: 'expires_on',
          value: link?.expires_on ?? '',
          placeholder: ctx.t('redirect.expires_placeholder'),
          mono: true,
          autocomplete: 'off',
        }),
        h('span', { class: 'field-help' }, ctx.t('redirect.f_help')),
        statusNoteKey(link) &&
          h('p', { class: 'field-help redirect-status-kept' }, ctx.t(statusNoteKey(link), { code: String(link.http_status) })),
        h('div', { class: 'redirect-actions' }, deleteButton, h('span', { class: 'redirect-actions-gap' }), cancelButton, saveButton),
      )

      const ownValues = () => OWN_FIELDS.map((name) => form.querySelector(`[name="${name}"]`)?.value)
      const opened = ownValues()
      const dirty = ({ slugCounts = true } = {}) => {
        const slug = OWN_FIELDS.indexOf('slug')
        return ownValues().some(
          (value, index) => value !== opened[index] && !(index === slug && (!slugCounts || value === givenSlug)),
        )
      }

      async function save() {
        clearNotice(noticeShown)
        const body = await withAddress(ctx, form, link, linkBody(form))
        if (!body) return
        const sent = typedFields(form)
        working = true
        try {
          const answer = savedLink(
            link
              ? await ctx.api('links.update', { method: 'PATCH', id: link.id, json: body })
              : await ctx.api('links.create', { json: body }),
          )
          const said = { key: link ? 'redirect.notice_saved' : 'redirect.notice_created', params: { name: answer.name } }
          // A new link must show, and the search may hide it
          const kept = { said, search: link ? search.value : '', focus: 'save', typed: typedSince(form, sent) }
          leaveWith(kept, { link: answer.id, new: null })
        } catch (error) {
          if (!link || !isGone(error)) throw error
          leaveGone()
        } finally {
          working = false
        }
      }

      function leaveGone() {
        leaveWith({ said: { key: 'redirect.notice_gone', error: true }, search: search.value }, { link: null, new: null })
      }

      async function remove() {
        if (working || !(await confirmDelete(ctx, link, sharedUrl(link, link.public_url))) || working) return
        clearNotice(noticeShown)
        const sent = typedFields(form)
        working = true
        deleteButton.disabled = true
        clearFormErrors(form)
        try {
          await deletedForGood(() => ctx.api('links.delete', deleteOptions(link, link.id)), listRows, link.id)
          const said = { key: 'redirect.notice_deleted', params: { name: link.name } }
          // Typed while it went: no other link's form takes that text, and a new one does
          const typed = typedSince(form, sent)
          leaveWith({ said, search: search.value, focus: typed ? null : 'row', typed }, { link: null, new: typed ? '1' : null })
        } catch (error) {
          if (isLeaving(error)) return
          if (isGone(error)) leaveGone()
          else showFormError(form, error, ctx.t)
        } finally {
          working = false
          deleteButton.disabled = false
          if (document.activeElement === document.body) deleteButton.focus({ preventScroll: true })
        }
      }

      function cancel() {
        if (working) return
        clearNotice(noticeShown)
        if (link) {
          drawForm(link)
          editing.cancelButton.focus()
        } else if (links.length) {
          selectLink(links[0])
          editing.cancelButton.focus()
        } else {
          // Nothing to go back to: the form of a new one stays, emptied with a slug suggested anew, and the address no longer
          // asks for it
          moveTo({ link: null, new: null })
          const opened = drawForm(null)
          opened.cancelButton.focus()
          fillSuggestion(opened)
        }
      }

      formHost.replaceChildren(card({ class: 'redirect-form-card' }, form))
      followSlug()
      editing = {
        link,
        form,
        saveButton,
        cancelButton,
        dirty,
        givenSlug: () => givenSlug,
        giveSlug: (slug) => {
          givenSlug = slug
        },
      }
      return editing
    }

    const selectLink = (link) => {
      selected = link
      clearNotice(noticeShown)
      moveTo({ link: link.id, new: null })
      drawList()
      drawForm(link)
    }

    const mayLeaveForm = (asked) => !editing?.dirty(asked) || askToDiscard(ctx)

    const pressRow = async (link) => {
      if (working || link.id === editing?.link?.id) return
      if (!(await mayLeaveForm()) || left) return
      selectLink(link)
      bringIntoView(editing.form)
    }

    const fillSuggestion = async ({ form, giveSlug }) => {
      const slug = await suggestedSlug(ctx)
      const input = form.querySelector('[name="slug"]')
      // A suggestion landing during a save would read as text typed meanwhile
      if (form.isConnected && !input.value && !working) {
        giveSlug(slug)
        input.value = slug
        input.dispatchEvent(new Event('input', { bubbles: true }))
      }
    }

    const startNew = async () => {
      // A new form for a new form, where a slug alone is all it would lose
      if (working || !(await mayLeaveForm({ slugCounts: Boolean(editing?.link) })) || left) return
      selected = null
      clearNotice(noticeShown)
      moveTo({ link: null, new: '1' })
      drawList()
      const opened = drawForm(null)
      opened.form.querySelector('[name="name"]').focus()
      await fillSuggestion(opened)
    }

    // --- Page

    const toolbar = h(
      'div',
      { class: 'redirect-toolbar' },
      search,
      button({ text: ctx.t('redirect.new'), variant: 'accent', class: 'redirect-new', onClick: startNew }),
    )
    const said = carried?.said ?? (formGone ? { key: 'redirect.notice_gone', error: true } : undefined)
    const noticeShown = noticeLine(ctx, said)
    el.append(
      pageHead(ctx, 'redirect.desc', links.length, COUNT_TEXTS),
      noticeShown,
      h(
        'div',
        { class: 'redirect-layout' },
        card({ body: false, class: 'redirect-list-card' }, toolbar, listHost),
        formHost,
      ),
    )
    drawList()

    const opened = drawForm(selected)
    if (before?.givenSlug) opened.giveSlug(before.givenSlug)
    if (carried?.typed) restoreTypedFields(opened.form, carried.typed)
    // A new form, asked for or the only one an empty list has, starts with a slug
    if (!selected) fillSuggestion(opened)
    // Back on the press that moved the page, or on the row that stands in for a row gone
    if (carried?.focus === 'save') opened.saveButton.focus()
    else if (carried?.focus === 'row') {
      if (selected) focusRow(selected.id)
      else focusPage()
    }

    return () => {
      left = true
      if (moved || !editing) return
      memory.leaving({ address, id: editing.link?.id, isNew: !editing.link, givenSlug: editing.givenSlug() })
    }
  },
}
