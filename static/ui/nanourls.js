// Source: Moonie Redirect 7.0.1 admin UI, system/redirect/ui/nanourls.js, trimmed: the link address (IP or public URL), optimistic
// concurrency, drafts kept across a login. Added: the Cloudflare address (field and column).
// The NanoURL page: a list on the left, and on the right the form of the selected NanoURL or of a new one. As on the Links
// page, the address holds which one. The instance makes the path from the name, so the form has no slug.

import {
  addressCell,
  addressField,
  addressWith,
  askToDiscard,
  bringIntoView,
  clearFormErrors,
  clearNotice,
  confirmDelete,
  copyButton,
  drawsNew,
  deletedForGood,
  deleteOptions,
  focusPage,
  formatTime,
  formTitle,
  isGone,
  isLeaving,
  keepForNextDraw,
  linkCell,
  matchesSearch,
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

const COUNT_TEXTS = ['redirect.count_nanos_none', 'redirect.count_nanos_one', 'redirect.count_nanos_many']

// The first column holds a short link on one line on a public URL of usual length. The others make
// room: a target wraps anywhere, and a time at its space.
const GRID = 'minmax(310px, 1.9fr) minmax(130px, 1fr) 96px 92px'
const MIN_WIDTH = 690
// The path holds NanoURL on every row, and would answer a search for it on all of them
const SEARCHED = ['name', 'short_url', 'target']
// So does a short link hold this
const IN_EVERY_SHORT_LINK = '/links/'

// Which NanoURL the form was on, since an address with no `link` shows the first of the list
const memory = pageMemory()

// Whether a NanoURL answers a search. What every short link holds tells no row from another, as the path would not.
export function matchesNano(nano, search) {
  const fixed = IN_EVERY_SHORT_LINK.includes(search.trim().toLowerCase())
  return matchesSearch(nano, search, fixed ? SEARCHED.filter((field) => field !== 'short_url') : SEARCHED)
}

function nanoCells(ctx, nano, showAddress) {
  const { h } = ctx.ui
  const url = sharedUrl(nano, nano.short_url)
  const cell = linkCell(ctx, nano, url)
  // With Cloudflare on, where the NanoURL answers goes under its name: a column more would push Copy out of the card
  if (showAddress) cell.append(addressCell(ctx, nano))
  return [
    cell,
    h('span', { class: 'mono redirect-target' }, nano.target),
    h('span', { class: 'mono redirect-modified' }, formatTime(nano.updated_at)),
    h('div', { class: 'redirect-row-actions' }, copyButton(ctx, url, url)),
  ]
}

export default {
  async load(ctx) {
    const listed = await ctx.api('nanourls.list')
    return { nanos: listed.nanourls, addresses: listed.addresses, creating: ctx.query.get('new') === '1' }
  },
  render(el, data, ctx) {
    const { button, card, field, h, table } = ctx.ui
    const { nanos, addresses } = data
    const showAddress = Boolean(addressChoices(addresses))
    const carried = takeKept()
    let query = ctx.query
    let address = `${location.pathname}${location.search}`
    const before = memory.takeShown(address)
    // A new form stays one, even at an address that does not ask for it
    const creating = drawsNew(data.creating, before)
    const wanted = query.get('link') ?? before?.id
    let selected = creating ? null : (nanos.find((nano) => nano.id === wanted) ?? nanos[0])
    // The form this draw comes back to has gone, with what was typed on it: that text must not land on another NanoURL
    const cameFor = before?.id ?? carried?.on
    const formGone = Boolean(cameFor) && !creating && selected?.id !== cameFor
    // A save or a delete on its way, or its answer leaving for the next draw: the form on screen is the one it answers to
    let working = false
    let moved = false
    let left = false
    let editing = null
    const busy = () => working || moved
    const listRows = async () => (await ctx.api('nanourls.list'))?.nanourls

    const moveTo = (changes) => {
      query = new URLSearchParams(addressWith('', query, changes).slice(1))
      ctx.address(addressWith(location.pathname, query, {}))
      address = `${location.pathname}${location.search}`
    }

    // --- List

    const listHost = h('div', {})

    const search = h('input', {
      class: 'input redirect-search',
      name: 'search',
      value: carried?.search ?? '',
      placeholder: ctx.t('redirect.nano_search'),
      'aria-label': ctx.t('redirect.nano_search'),
      autocomplete: 'off',
      oninput: () => drawList(),
    })

    // The rows go and come back: the row holding the focus keeps it, and the table stays where it was scrolled
    const drawList = () => {
      const focused = document.activeElement?.getAttribute('role') === 'row' && listHost.contains(document.activeElement)
      const scrolled = listHost.querySelector('.table')?.scrollLeft ?? 0
      const shown = nanos.filter((nano) => matchesNano(nano, search.value))
      const drawn = table({
        columns: [ctx.t('redirect.nano_col_short'), ctx.t('redirect.col_target'), ctx.t('redirect.col_modified'), ''],
        rows: shown.map((nano) => ({
          cells: nanoCells(ctx, nano, showAddress),
          selected: nano.id === selected?.id,
          onClick: () => pressRow(nano),
        })),
        grid: GRID,
        minWidth: MIN_WIDTH,
      })
      const none = noRowsKey(nanos.length, 'redirect.nano_none_match', 'redirect.nano_none_yet')
      listHost.replaceChildren(drawn, ...(shown.length ? [] : [h('p', { class: 'small redirect-none' }, ctx.t(none))]))
      drawn.scrollLeft = scrolled
      if (focused) focusSelectedRow()
    }

    const focusSelectedRow = () => listHost.querySelector('[aria-current="true"]')?.focus()

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

    const drawForm = (nano) => {
      const nameField = field({
        label: ctx.t('redirect.f_name'),
        name: 'name',
        value: nano?.name ?? '',
        help: ctx.t('redirect.nano_name_help'),
        autocomplete: 'off',
      })
      // Text only while it holds, so a screen reader hears it when it comes. The old path goes free.
      const pathWarning = h('span', { class: 'redirect-slug-warning', 'aria-live': 'polite' })
      nameField.append(pathWarning)
      const followName = () => {
        const renamed = nano && nameField.querySelector('[name="name"]').value.trim() !== nano.name
        pathWarning.textContent = renamed ? ctx.t('redirect.nano_path_warning', { path: `/redirect/${nano.slug}` }) : ''
      }

      const deleteButton =
        nano && button({ text: ctx.t('redirect.delete'), variant: 'danger', class: 'redirect-delete', onClick: remove })
      const cancelButton = button({ text: ctx.t('common.cancel'), class: 'redirect-cancel', onClick: cancel })
      const saveButton = button({ text: ctx.t('common.save'), variant: 'accent', type: 'submit', class: 'redirect-save' })

      const form = h(
        'form',
        {
          class: 'redirect-form',
          novalidate: true,
          oninput: (event) => {
            if (event.target.name === 'name') followName()
          },
          onsubmit: (event) => {
            event.preventDefault()
            if (busy()) return undefined
            return submitting(form, save, ctx.t, saveButton)
          },
        },
        formTitle(ctx, nano ? ctx.t('redirect.form_edit', { path: `/links/${nano.id}` }) : ctx.t('redirect.nano_new')),
        h('p', { class: 'form-error', role: 'alert', hidden: true }),
        nameField,
        field({ label: ctx.t('redirect.f_target'), name: 'target', value: nano?.target ?? '', mono: true, autocomplete: 'off' }),
        addressField(ctx, {
          link: nano,
          addresses,
          path: () => nano?.id ?? ctx.t('redirect.address_code'),
          lanPath: () => `/links/${nano?.id ?? ctx.t('redirect.address_code')}`,
        }),
        h('div', { class: 'redirect-actions' }, deleteButton, h('span', { class: 'redirect-actions-gap' }), cancelButton, saveButton),
      )

      const opened = JSON.stringify(typedFields(form))
      const dirty = () => JSON.stringify(typedFields(form)) !== opened

      async function save() {
        clearNotice(noticeShown)
        const value = (name) => form.elements.namedItem(name).value
        const body = await withAddress(ctx, form, nano, { name: value('name'), target: value('target') })
        if (!body) return
        const sent = typedFields(form)
        working = true
        try {
          const answer = savedLink(
            nano
              ? await ctx.api('nanourls.update', { method: 'PATCH', id: nano.id, json: body })
              : await ctx.api('nanourls.create', { json: body }),
          )
          const said = nano
            ? { key: 'redirect.nano_notice_saved', params: { name: answer.name } }
            : { key: 'redirect.nano_notice_created', params: { name: answer.name, url: answer.short_url } }
          // A new one must show, and the search may hide it
          const kept = { said, search: nano ? search.value : '', focus: 'save', typed: typedSince(form, sent) }
          leaveWith(kept, { link: answer.id, new: null })
        } catch (error) {
          if (!nano || !isGone(error)) throw error
          leaveGone()
        } finally {
          working = false
        }
      }

      function leaveGone() {
        leaveWith({ said: { key: 'redirect.nano_notice_gone', error: true }, search: search.value }, { link: null, new: null })
      }

      async function remove() {
        if (busy() || !(await confirmDelete(ctx, nano, sharedUrl(nano, nano.short_url))) || busy()) return
        clearNotice(noticeShown)
        const sent = typedFields(form)
        working = true
        deleteButton.disabled = true
        clearFormErrors(form)
        try {
          await deletedForGood(() => ctx.api('nanourls.delete', deleteOptions(nano, nano.id)), listRows, nano.id)
          const said = { key: 'redirect.nano_notice_deleted', params: { name: nano.name } }
          // Typed while it went: no other NanoURL's form takes that text, and a new one does
          const typed = typedSince(form, sent)
          const kept = { said, search: search.value, focus: typed ? null : 'row', typed }
          leaveWith(kept, { link: null, new: typed ? '1' : null })
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
        if (busy()) return
        clearNotice(noticeShown)
        if (nano) {
          drawForm(nano)
          editing.cancelButton.focus()
        } else if (nanos.length) {
          selectNano(nanos[0])
          editing.cancelButton.focus()
        } else {
          // Nothing to go back to: the form of a new one stays, emptied, and the address no longer asks for it
          moveTo({ link: null, new: null })
          drawForm(null)
          editing.cancelButton.focus()
        }
      }

      formHost.replaceChildren(card({ class: 'redirect-form-card' }, form))
      followName()
      editing = {
        nano,
        form,
        saveButton,
        cancelButton,
        dirty,
      }
      return editing
    }

    const selectNano = (nano) => {
      selected = nano
      clearNotice(noticeShown)
      moveTo({ link: nano.id, new: null })
      drawList()
      drawForm(nano)
    }

    const pressRow = async (nano) => {
      if (busy() || nano.id === editing?.nano?.id) return
      if (editing?.dirty() && !(await askToDiscard(ctx))) return
      if (left || busy()) return
      selectNano(nano)
      bringIntoView(editing.form)
    }

    const startNew = async () => {
      if (busy() || (editing?.dirty() && !(await askToDiscard(ctx))) || left || busy()) return
      selected = null
      clearNotice(noticeShown)
      moveTo({ link: null, new: '1' })
      drawList()
      drawForm(null).form.elements.namedItem('name').focus()
    }

    // --- Page

    const toolbar = h(
      'div',
      { class: 'redirect-toolbar' },
      search,
      button({ text: ctx.t('redirect.nano_new'), variant: 'accent', class: 'redirect-new', onClick: startNew }),
    )
    const said = carried?.said ?? (formGone ? { key: 'redirect.nano_notice_gone', error: true } : undefined)
    const noticeShown = noticeLine(ctx, said)
    el.append(
      pageHead(ctx, 'redirect.nano_desc', nanos.length, COUNT_TEXTS),
      noticeShown,
      h(
        'div',
        { class: 'redirect-layout' },
        card({ body: false, class: 'redirect-list-card' }, toolbar, listHost),
        formHost,
      ),
    )
    drawList()

    const opened = drawForm(selected ?? null)
    if (carried?.typed) restoreTypedFields(opened.form, carried.typed)
    // Back on the press that moved the page, or on the row that stands in for a row gone
    if (carried?.focus === 'save') opened.saveButton.focus()
    else if (carried?.focus === 'row') {
      if (selected) focusSelectedRow()
      else focusPage()
    }

    return () => {
      left = true
      if (moved || !editing) return
      memory.leaving({ address, id: editing.nano?.id, isNew: !editing.nano })
    }
  },
}
