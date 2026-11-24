// Source: Moonie Redirect 7.0.1 admin UI, system/redirect/ui/qrcodes.js, trimmed: the link address (IP or public URL), optimistic
// concurrency, drafts kept across a login or a language change. Changed: the thumbnail and the download read this app's
// `qr.svg` route. Added: the Cloudflare address (field and column), which the preview draws.
// The QR page: a list on the left, and on the right the designer of the selected QR code or of a new one, with its preview.
// The instance draws the preview with the code that draws the file. Its answer reaches the page only as the address of an
// <img>, where an image runs nothing and fetches nothing, whatever logo a user put in it. It never joins the document.

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
  spokenCode,
  submitting,
  takeKept,
  typedFields,
  typedSince,
  withAddress,
} from './common.js'
import { addressChoices } from './cloudflare-logic.js'

const COUNT_TEXTS = ['redirect.count_qrcodes_none', 'redirect.count_qrcodes_one', 'redirect.count_qrcodes_many']

const GRID = ['52px', 'minmax(150px, 1.3fr)', 'minmax(150px, 1.3fr)', '100px', '160px'].join(' ')
const MIN_WIDTH = 720
const LOGO_TYPES = 'image/png,image/jpeg,image/webp,image/svg+xml'
const LOGO_REFUSALS = ['redirect.design_logo', 'redirect.design_logo_size']
// The API's default for each field left out (README, JSON API): a new QR code starts from what the instance would store
const NEW_DESIGN = {
  color: '#1b1f24',
  eye_color: '#1b1f24',
  background: '#ffffff',
  module_style: 'square',
  eye_style: 'square',
  logo: null,
  logo_size: 0.22,
  margin: 4,
}
// What the colour control of the background holds while the background is transparent: it must hold some colour
const BACKGROUND_WHEN_TRANSPARENT = '#ffffff'
// An answer that is no answer, as something in front of the instance gives, or a drawing no image can show
const NO_ANSWER = { status: 200, code: null, params: {}, fields: {} }
const MODULE_STYLES = [
  ['square', 'redirect.qr_style_square'],
  ['rounded', 'redirect.qr_style_rounded'],
  ['dots', 'redirect.qr_style_dots'],
]
const EYE_STYLES = [
  ['square', 'redirect.qr_style_square'],
  ['rounded', 'redirect.qr_style_rounded'],
  ['circle', 'redirect.qr_style_circle'],
]

// --- Pure -----------------------------------------------------------------------------------------------------------

// Every code holds these in its addresses, and would answer a search for them on every row
const SEARCHED = {
  name: [],
  slug: ['QRcodes/'],
  target: [],
  public_url: ['/redirect/QRcodes/'],
  short_url: ['/links/'],
}

export function matchesQr(qr, search) {
  return matchesTelling(qr, search, SEARCHED)
}

// The API's logo limit, 256 KiB (README, JSON API), kept here too so that a file past it is not read, sent and refused: the instance still decides
export const LOGO_MAX_BYTES = 256 * 1024

// The key to show for a chosen file before it is read, or null. What its bytes are is the instance's to say.
export function logoProblem(file) {
  return file.size > LOGO_MAX_BYTES ? 'redirect.design_logo_size' : null
}

// The design the controls of the form stand for. A percentage goes back to a share, and a logo is not a control's value.
export function designFrom(fields, logo) {
  return {
    color: fields.color,
    eye_color: fields.eye_color,
    background: fields.transparent ? 'transparent' : fields.background,
    module_style: fields.module_style,
    eye_style: fields.eye_style,
    logo,
    logo_size: Number(fields.logo_size) / 100,
    margin: Number(fields.margin),
  }
}

// The share of the side a stored logo takes, as the whole percentage its control holds
export function percentOf(share) {
  return Math.round(share * 100)
}

// What an <img> shows the instance's drawing through. Percent-encoded, since the drawing may hold any character.
export function imageAddress(svg) {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

// The address of a code's file, as this app serves it
export function svgAddress(qr) {
  return `/api/links/${encodeURIComponent(qr.id)}/qr.svg`
}

// What the row's <img> asks for. A page keeps an image by its address for as long as it stands, whatever the answer's headers
// say, so what changes the drawing changes the address: a save changes the time, and the address the code holds is the
// base URL's or a Cloudflare host's.
export function thumbnailAddress(qr) {
  return `${svgAddress(qr)}?v=${encodeURIComponent(qr.updated_at)}&to=${encodeURIComponent(qr.address_url ?? qr.short_url)}`
}

// What the download link asks for: the same file, as an attachment
export function downloadAddress(qr) {
  return `${svgAddress(qr)}?download=1`
}

// Why a code has no drawing, as a key, or null. This app answers a design it cannot read as null.
export function drawingProblem(qr) {
  return qr.design ? null : 'redirect.design_unreadable'
}

// The file name the instance gives the same file
export function downloadName(qr) {
  return `${qr.slug.split('/').pop()}.svg`
}

// A call that takes the latest state whenever it runs, one at a time. Asked while it runs, it runs once more when it ends,
// however many times it was asked: an old answer can never land on a newer one. No timer, so a capture has nothing to wait
// for. `settled` runs when nothing is left to do. A run that throws gives its throw to the call it belongs to, and what was
// asked meanwhile still runs.
export function latestOnly(run, settled) {
  let running = false
  let again = false
  const ask = async () => {
    if (running) {
      again = true
      return
    }
    running = true
    try {
      do {
        again = false
        await run()
      } while (again)
    } finally {
      running = false
      if (again) ask()
      else settled?.()
    }
  }
  return ask
}

// --- What the next draw comes back to ------------------------------------------------------------------------------------

// Which code the form was on, since an address with no `qr` shows the first of the list. A reload comes back with what is
// stored, as every field does.
const memory = pageMemory()

function here() {
  return location.pathname + location.search
}

// --- Parts ------------------------------------------------------------------------------------------------------------

function thumbnail(ctx, qr) {
  const { h } = ctx.ui
  // No image at all where the instance has no drawing: it would show broken, and log a failed call
  const problem = drawingProblem(qr)
  if (problem) {
    return h(
      'span',
      { class: 'redirect-qr-thumb redirect-qr-none', role: 'img', 'aria-label': ctx.t(problem), title: ctx.t(problem) },
      '—',
    )
  }
  return h(
    'span',
    { class: 'redirect-qr-thumb redirect-qr-paper' },
    h('img', { src: thumbnailAddress(qr), alt: ctx.t('redirect.qr_image_alt', { name: qr.name }), width: 40, height: 40 }),
  )
}

function downloadCell(ctx, qr) {
  const { h } = ctx.ui
  // The link still works and its row stays, with nothing to download: the same place, the same word, and why
  const problem = drawingProblem(qr)
  if (problem) {
    return h(
      'button',
      {
        class: 'btn redirect-download',
        type: 'button',
        disabled: true,
        title: ctx.t(problem),
        'aria-label': ctx.t('redirect.qr_download_none', { name: qr.name }),
      },
      ctx.t('redirect.qr_download'),
    )
  }
  return h(
    'a',
    {
      class: 'btn redirect-download',
      href: downloadAddress(qr),
      download: downloadName(qr),
      'aria-label': ctx.t('redirect.qr_download_label', { name: qr.name }),
    },
    ctx.t('redirect.qr_download'),
  )
}

function qrCells(ctx, qr, showAddress) {
  const { h } = ctx.ui
  const link = linkCell(ctx, qr)
  if (drawingProblem(qr)) link.append(h('span', { class: 'redirect-qr-problem' }, ctx.t('redirect.qr_no_drawing')))
  // With Cloudflare on, where the code answers goes under its name: a column more would push Copy out of the card
  if (showAddress) link.append(addressCell(ctx, qr))
  const url = sharedUrl(qr, qr.short_url)
  return [
    thumbnail(ctx, qr),
    link,
    h('span', { class: 'mono redirect-target' }, qr.target),
    h('span', { class: 'mono redirect-modified' }, formatTime(qr.updated_at)),
    h('div', { class: 'redirect-row-actions' }, copyButton(ctx, url, url), downloadCell(ctx, qr)),
  ]
}

function styleOptions(ctx, styles) {
  return styles.map(([value, key]) => ({ value, text: ctx.t(key) }))
}

function colorField(ctx, { label, name, value, disabled }) {
  const { h } = ctx.ui
  return h(
    'label',
    { class: 'field' },
    label,
    h('input', { class: 'redirect-color', type: 'color', name, value, disabled }),
    h('span', { class: 'mono redirect-color-value' }),
  )
}

function rangeField(ctx, { label, id, name, min, max, value, disabled }) {
  const { h } = ctx.ui
  // The bounds come first: a value set before them is cut to the default range
  return h(
    'label',
    { class: 'field' },
    label,
    h(
      'span',
      { class: 'redirect-range' },
      h('input', { id, type: 'range', name, min, max, step: 1, value, disabled }),
      h('output', { for: id, class: 'mono' }),
    ),
  )
}

function readFile(file) {
  return new Promise((done, failed) => {
    const reader = new FileReader()
    reader.addEventListener('load', () => done(reader.result))
    reader.addEventListener('error', () => failed(reader.error))
    reader.readAsDataURL(file)
  })
}

// --- Page -------------------------------------------------------------------------------------------------------------

export default {
  async load(ctx) {
    const listed = await ctx.api('qrcodes.list')
    return { qrcodes: listed.qrcodes, addresses: listed.addresses, creating: ctx.query.get('new') === '1' }
  },
  render(el, data, ctx) {
    const { button, card, field, h, select, table } = ctx.ui
    const { qrcodes, addresses } = data
    const showAddress = Boolean(addressChoices(addresses))
    const carried = takeKept()
    let query = ctx.query
    let address = here()
    const before = memory.takeShown(address)
    // A new form stays one, even at an address that does not ask for it
    const creating = drawsNew(data.creating, before)
    const wanted = query.get('qr') ?? before?.id
    let selected = creating ? null : (qrcodes.find((qr) => qr.id === wanted) ?? qrcodes[0])
    // The form this draw comes back to has gone, with what was typed on it: that text must not land on another code
    const cameFor = before?.id ?? carried?.on
    const formGone = Boolean(cameFor) && !creating && selected?.id !== cameFor
    // A save or a delete on its way, or its answer leaving for the next draw: the form on screen is the one it answers to
    let working = false
    let moved = false
    let left = false
    let editing = null
    const busy = () => working || moved
    const listRows = async () => (await ctx.api('qrcodes.list'))?.qrcodes

    const moveTo = (changes) => {
      query = new URLSearchParams(addressWith('', query, changes).slice(1))
      ctx.address(addressWith(location.pathname, query, {}))
      address = here()
    }

    // --- List

    const listHost = h('div', {})

    const search = h('input', {
      class: 'input redirect-search',
      name: 'search',
      value: carried?.search ?? '',
      placeholder: ctx.t('redirect.qr_search'),
      'aria-label': ctx.t('redirect.qr_search'),
      autocomplete: 'off',
      oninput: () => drawList(),
    })

    // The rows go and come back: the row holding the focus keeps it, and the table stays where it was scrolled
    const drawList = () => {
      const focused = document.activeElement?.getAttribute('role') === 'row' && listHost.contains(document.activeElement)
      const scrolled = listHost.querySelector('.table')?.scrollLeft ?? 0
      const shown = qrcodes.filter((qr) => matchesQr(qr, search.value))
      const drawn = table({
        columns: [
          ctx.t('redirect.qr_col_image'),
          ctx.t('redirect.col_link'),
          ctx.t('redirect.col_target'),
          ctx.t('redirect.col_modified'),
          '',
        ],
        rows: shown.map((qr) => ({
          cells: qrCells(ctx, qr, showAddress),
          selected: qr.id === selected?.id,
          onClick: () => pressRow(qr),
        })),
        grid: GRID,
        minWidth: MIN_WIDTH,
      })
      const none = noRowsKey(qrcodes.length, 'redirect.qr_none_match', 'redirect.qr_none_yet')
      listHost.replaceChildren(drawn, ...(shown.length ? [] : [h('p', { class: 'small redirect-none' }, ctx.t(none))]))
      drawn.scrollLeft = scrolled
      if (focused) focusSelectedRow()
    }

    const focusSelectedRow = () => listHost.querySelector('[aria-current="true"]')?.focus()

    // --- Designer

    const formHost = h('div', { class: 'redirect-form-host' })

    // Goes nowhere once the page has been left: the page on screen is another one, and what is kept would wait for a later visit
    const leaveWith = (said, changes) => {
      if (left) return
      moved = true
      keepForNextDraw(said)
      moveTo(changes)
      ctx.reload()
    }

    const drawForm = (qr, startingLogo) => {
      const design = qr?.design ?? NEW_DESIGN
      const transparent = design.background === 'transparent'
      // What the preview last accepted: a refused file gives way to it
      let accepted = design.logo
      let logo = startingLogo === undefined ? design.logo : startingLogo
      // The form of a design nobody can read stands on the default: saying so holds until the user has chosen something
      let unreadable = Boolean(qr) && !qr.design

      // --- Preview

      const image = h('img', { alt: ctx.t('redirect.qr_preview_alt'), width: 216, height: 216, hidden: true })
      const noDrawing = h('span', { class: 'redirect-qr-none', hidden: true }, ctx.t('redirect.qr_no_drawing'))
      const frame = h('div', { class: 'redirect-qr-frame redirect-qr-paper', 'aria-busy': true }, image, noDrawing)
      const designError = h('span', { class: 'field-error redirect-design-error', id: 'qr-design-error', role: 'alert', hidden: true })

      const showDesignError = (key, params) => {
        designError.textContent = spokenCode(ctx.t, key, params)
        designError.hidden = false
      }
      const hideDesignError = () => {
        designError.textContent = ''
        designError.hidden = true
      }
      const fieldset = () => form.elements.namedItem('design')

      const refused = (error, sent) => {
        const key = isGone(error) ? 'redirect.qr_notice_gone' : (error.fields?.design ?? error.code ?? 'state.form_no_response')
        showDesignError(key, error.params)
        noDrawing.hidden = !image.hidden
        // Only the logo it refused gives way: another may have been chosen or removed since it was sent
        if (LOGO_REFUSALS.includes(key) && sent.logo !== accepted && logo === sent.logo) {
          // The image on screen is the one of the logo before: nothing there is out of date
          logo = accepted
          followLogo()
          return
        }
        frame.setAttribute('data-stale', 'true')
      }

      // The address the form has chosen, for the preview to draw; none while there is nothing to choose
      const chosenAddress = () => {
        const control = form.elements.namedItem('address')
        return control ? { address: control.value } : {}
      }

      const preview = latestOnly(async () => {
        const sent = read()
        try {
          const answer = await ctx.api('qrcodes.preview', {
            json: { id: qr?.id, design: sent, ...chosenAddress() },
          })
          if (!form.isConnected) return
          if (typeof answer?.svg !== 'string') throw NO_ANSWER
          image.src = imageAddress(answer.svg)
          await image.decode().catch(() => {
            throw NO_ANSWER
          })
          image.hidden = false
          noDrawing.hidden = true
          frame.removeAttribute('data-stale')
          accepted = sent.logo
          fieldset().removeAttribute('aria-invalid')
          if (unreadable) showDesignError('redirect.design_unreadable')
          else hideDesignError()
        } catch (error) {
          if (isLeaving(error) || !form.isConnected) return
          if (error?.status === undefined) throw error
          refused(error, sent)
        }
      }, () => frame.setAttribute('aria-busy', 'false'))

      const refresh = () => {
        frame.setAttribute('aria-busy', 'true')
        preview()
      }

      // --- Logo

      const logoState = h('span', { class: 'small redirect-logo-state' })
      const logoInput = h('input', {
        type: 'file',
        accept: LOGO_TYPES,
        'aria-describedby': 'qr-logo-help qr-design-error',
        onchange: () => pickLogo(),
      })
      const chooser = h('label', { class: 'btn redirect-file' }, logoInput, ctx.t('redirect.qr_logo_choose'))
      const logoActions = h('span', { class: 'redirect-logo-actions' }, chooser)
      const removeButton = button({ text: ctx.t('redirect.qr_logo_remove'), class: 'redirect-logo-remove', onClick: removeLogo })

      // The chooser and Remove stay in the document while they are of use: an element taken out loses the focus to the body
      const followLogo = () => {
        logoState.textContent = ctx.t(logo ? 'redirect.qr_logo_set' : 'redirect.qr_logo_none')
        if (logo) {
          if (!removeButton.parentNode) logoActions.append(removeButton)
        } else if (removeButton.parentNode) {
          const held = document.activeElement === removeButton
          removeButton.remove()
          if (held) logoInput.focus()
        }
        form.elements.namedItem('logo_size').disabled = !logo
      }

      async function pickLogo() {
        const [file] = logoInput.files
        if (!file) return
        // Emptied now: the same file chosen again still counts as a choice
        const problem = logoProblem(file)
        if (problem) {
          logoInput.value = ''
          showDesignError(problem)
          return
        }
        frame.setAttribute('aria-busy', 'true')
        let content
        try {
          content = await readFile(file)
        } catch {
          showDesignError('redirect.design_logo')
          frame.setAttribute('aria-busy', 'false')
          return
        } finally {
          logoInput.value = ''
        }
        if (!form.isConnected) return
        logo = content
        unreadable = false
        followLogo()
        refresh()
      }

      function removeLogo() {
        logo = null
        unreadable = false
        followLogo()
        logoInput.focus()
        refresh()
      }

      // --- Fields

      const deleteButton =
        qr && button({ text: ctx.t('redirect.delete'), variant: 'danger', class: 'redirect-delete', onClick: remove })
      const cancelButton = button({ text: ctx.t('common.cancel'), class: 'redirect-cancel', onClick: cancel })
      const saveButton = button({ text: ctx.t('common.save'), variant: 'accent', type: 'submit', class: 'redirect-save' })
      const form = h(
        'form',
        {
          class: 'redirect-form',
          novalidate: true,
          oninput: (event) => {
            // Nothing of the name or the target is in the image, since the code holds the short link. A file has its own
            // way in, once it is read.
            if (!event.target.name || ['name', 'target'].includes(event.target.name)) return
            unreadable = false
            followControls()
            refresh()
          },
          onsubmit: (event) => {
            event.preventDefault()
            if (busy()) return undefined
            return submitting(form, save, ctx.t, saveButton)
          },
        },
        formTitle(ctx, qr ? ctx.t('redirect.form_edit', { path: `/redirect/${qr.slug}` }) : ctx.t('redirect.qr_new')),
        h('p', { class: 'form-error', role: 'alert', hidden: true }),
        field({
          label: ctx.t('redirect.f_name'),
          name: 'name',
          value: qr?.name ?? '',
          autocomplete: 'off',
          help: ctx.t('redirect.qr_name_help'),
        }),
        field({ label: ctx.t('redirect.f_target'), name: 'target', value: qr?.target ?? '', mono: true, autocomplete: 'off' }),
        // A code moved to another address is another image: the preview draws the one chosen before it is saved
        addressField(ctx, {
          link: qr,
          addresses,
          path: () => qr?.id ?? ctx.t('redirect.address_code'),
          lanPath: () => `/links/${qr?.id ?? ctx.t('redirect.address_code')}`,
          onChange: () => refresh(),
        }),
        // A refusal of the design lands in the first error slot of this field: the one under the preview
        h(
          'div',
          { class: 'field redirect-design' },
          h(
            'fieldset',
            { name: 'design', tabindex: -1, 'aria-describedby': 'qr-design-error' },
            h('legend', { class: 'label' }, ctx.t('redirect.qr_design')),
            frame,
            designError,
            h(
              'div',
              { class: 'redirect-colors' },
              colorField(ctx, { label: ctx.t('redirect.qr_color'), name: 'color', value: design.color }),
              colorField(ctx, { label: ctx.t('redirect.qr_eye_color'), name: 'eye_color', value: design.eye_color }),
              colorField(ctx, {
                label: ctx.t('redirect.qr_background'),
                name: 'background',
                value: transparent ? BACKGROUND_WHEN_TRANSPARENT : design.background,
                disabled: transparent,
              }),
            ),
            h(
              'label',
              { class: 'redirect-check' },
              h('input', { type: 'checkbox', name: 'transparent', checked: transparent }),
              ctx.t('redirect.qr_transparent'),
            ),
            h(
              'div',
              { class: 'redirect-pair' },
              select({
                label: ctx.t('redirect.qr_module_style'),
                name: 'module_style',
                value: design.module_style,
                options: styleOptions(ctx, MODULE_STYLES),
              }),
              select({
                label: ctx.t('redirect.qr_eye_style'),
                name: 'eye_style',
                value: design.eye_style,
                options: styleOptions(ctx, EYE_STYLES),
              }),
            ),
            h(
              'div',
              { class: 'field' },
              h('span', {}, ctx.t('redirect.qr_logo')),
              h('div', { class: 'redirect-logo-line' }, logoActions, logoState),
              h('span', { class: 'field-help', id: 'qr-logo-help' }, ctx.t('redirect.qr_logo_help')),
            ),
            h(
              'div',
              { class: 'redirect-pair' },
              rangeField(ctx, {
                label: ctx.t('redirect.qr_logo_size'),
                id: 'qr-logo-size',
                name: 'logo_size',
                min: 10,
                max: 30,
                value: percentOf(design.logo_size),
                disabled: !logo,
              }),
              rangeField(ctx, { label: ctx.t('redirect.qr_margin'), id: 'qr-margin', name: 'margin', min: 0, max: 10, value: design.margin }),
            ),
          ),
        ),
        h('div', { class: 'redirect-actions' }, deleteButton, h('span', { class: 'redirect-actions-gap' }), cancelButton, saveButton),
      )

      const value = (name) => form.elements.namedItem(name)
      const openedShare = value('logo_size').value

      function read() {
        const drawn = designFrom(
          {
            color: value('color').value,
            eye_color: value('eye_color').value,
            background: value('background').value,
            transparent: value('transparent').checked,
            module_style: value('module_style').value,
            eye_style: value('eye_style').value,
            logo_size: value('logo_size').value,
            margin: value('margin').value,
          },
          logo,
        )
        // The control holds whole percents: while nobody has moved it, the design keeps the share it has
        if (value('logo_size').value === openedShare) drawn.logo_size = design.logo_size
        return drawn
      }

      // What shows the value of a control, and what one control allows of another
      function followControls() {
        value('background').disabled = value('transparent').checked
        for (const name of ['color', 'eye_color', 'background']) {
          value(name).closest('.field').querySelector('.redirect-color-value').textContent = value('transparent').checked && name === 'background' ? '' : value(name).value
        }
        form.querySelector('output[for="qr-logo-size"]').textContent = ctx.t('redirect.qr_percent', { value: value('logo_size').value })
        form.querySelector('output[for="qr-margin"]').textContent = value('margin').value
      }

      async function save() {
        clearNotice(noticeShown)
        const body = await withAddress(ctx, form, qr, {
          name: value('name').value,
          target: value('target').value,
          design: read(),
        })
        if (!body) return
        const sent = typedFields(form)
        const sentLogo = logo
        working = true
        try {
          const answer = savedLink(
            qr
              ? await ctx.api('qrcodes.update', { method: 'PATCH', id: qr.id, json: body })
              : await ctx.api('qrcodes.create', { json: body }),
          )
          const said = { key: qr ? 'redirect.qr_notice_saved' : 'redirect.qr_notice_created', params: { name: answer.name } }
          // A new code must show, and the search may hide it
          const kept = { said, search: qr ? search.value : '', focus: 'save', typed: typedSince(form, sent), logo: logoSince(sentLogo) }
          leaveWith(kept, { qr: answer.id, new: null })
        } catch (error) {
          if (!qr || !isGone(error)) throw error
          leaveGone()
        } finally {
          working = false
        }
      }

      // The logo held now, if it is no longer the one it was: a logo is in no field, and comes back like what was typed meanwhile.
      // Undefined when it did not change, since null is a logo removed.
      const logoSince = (then) => (logo === then ? undefined : logo)

      function leaveGone() {
        leaveWith({ said: { key: 'redirect.qr_notice_gone', error: true }, search: search.value }, { qr: null, new: null })
      }

      async function remove() {
        if (busy() || !(await confirmDelete(ctx, qr, sharedUrl(qr, qr.short_url))) || busy()) return
        clearNotice(noticeShown)
        const sent = typedFields(form)
        const sentLogo = logo
        working = true
        deleteButton.disabled = true
        clearFormErrors(form)
        try {
          await deletedForGood(() => ctx.api('qrcodes.delete', deleteOptions(qr, qr.id)), listRows, qr.id)
          const said = { key: 'redirect.qr_notice_deleted', params: { name: qr.name } }
          // Typed while it went: no other code's form takes that text, and a new one does
          const typed = typedSince(form, sent)
          const chosen = logoSince(sentLogo)
          const again = Boolean(typed) || chosen !== undefined
          leaveWith({ said, search: search.value, focus: again ? null : 'row', typed, logo: chosen }, { qr: null, new: again ? '1' : null })
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
        if (qr) {
          drawForm(qr)
          editing.cancelButton.focus()
        } else if (qrcodes.length) {
          selectQr(qrcodes[0])
          editing.cancelButton.focus()
        } else {
          // Nothing to go back to: the form of a new one stays, back to the default design, and the address no longer asks
          // for it
          moveTo({ qr: null, new: null })
          drawForm(null)
          editing.cancelButton.focus()
        }
      }

      formHost.replaceChildren(card({ class: 'redirect-form-card' }, form))
      followControls()
      followLogo()
      const opened = JSON.stringify(typedFields(form))
      refresh()
      editing = {
        qr,
        form,
        saveButton,
        cancelButton,
        // A form with a design nobody can read holds nothing typed until something is typed: it stands on the default
        dirty: () => JSON.stringify(typedFields(form)) !== opened || logo !== design.logo,
      }
      return editing
    }

    const selectQr = (qr) => {
      selected = qr
      clearNotice(noticeShown)
      moveTo({ qr: qr.id, new: null })
      drawList()
      drawForm(qr)
    }

    const pressRow = async (qr) => {
      if (busy() || qr.id === editing?.qr?.id) return
      if (editing?.dirty() && !(await askToDiscard(ctx))) return
      if (left || busy()) return
      selectQr(qr)
      bringIntoView(editing.form)
    }

    const startNew = async () => {
      if (busy() || (editing?.dirty() && !(await askToDiscard(ctx))) || left || busy()) return
      selected = null
      clearNotice(noticeShown)
      moveTo({ qr: null, new: '1' })
      drawList()
      drawForm(null).form.elements.namedItem('name').focus()
    }

    // --- Page

    const toolbar = h(
      'div',
      { class: 'redirect-toolbar' },
      search,
      button({ text: ctx.t('redirect.qr_new'), variant: 'accent', class: 'redirect-new', onClick: startNew }),
    )
    const said = carried?.said ?? (formGone ? { key: 'redirect.qr_notice_gone', error: true } : undefined)
    const noticeShown = noticeLine(ctx, said)
    el.append(
      pageHead(ctx, 'redirect.qr_desc', qrcodes.length, COUNT_TEXTS),
      noticeShown,
      h(
        'div',
        { class: 'redirect-layout' },
        card({ body: false, class: 'redirect-list-card' }, toolbar, listHost),
        formHost,
      ),
    )
    drawList()

    const opened = drawForm(selected ?? null, carried?.logo)
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
      memory.leaving({ address, id: editing.qr?.id, isNew: !editing.qr })
    }
  },
}
