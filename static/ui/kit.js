// Source: Moonie Redirect 7.0.1 admin UI, ui/kit.js, verbatim but for one comment.
// The shared components, handed to every page as `ctx.ui`. Text is always inserted as text.

import { copyText } from './lib.js'
import { iconNode } from './icons.js'

const COPIED_MS = 2000
const STATE_LEVELS = ['success', 'warning', 'danger', 'info']
const ADDRESS_ATTRIBUTES = ['href', 'src', 'action', 'formaction', 'xlink:href']
const SCRIPT_PROTOCOLS = ['javascript:', 'vbscript:']
// What keeps its own click inside a row that has one: native controls, what a page builds with a role, what can be
// typed in, and a segmented's padding, which sits a pixel from what the user aims at
const ROW_CONTROL_ROLES = [
  'button',
  'checkbox',
  'combobox',
  'link',
  'listbox',
  'menu',
  'menuitem',
  'menuitemcheckbox',
  'menuitemradio',
  'option',
  'radio',
  'radiogroup',
  'searchbox',
  'slider',
  'spinbutton',
  'switch',
  'tab',
  'tablist',
  'textbox',
  'toolbar',
  'tree',
  'treeitem',
]
const ROW_CONTROLS = [
  'a',
  'button',
  'input',
  'select',
  'textarea',
  'label',
  'summary',
  '[tabindex]',
  '[contenteditable]:not([contenteditable="false"])',
  '.segmented',
  ...ROW_CONTROL_ROLES.map((role) => `[role="${role}"]`),
].join(', ')
// Enter acts when pressed and Space when released, and a repeat of either would answer what a press just opened
const ACTIVATING_KEYS = ['Enter', ' ']
const openDialogs = new Set()
let nextId = 0

function uniqueId() {
  nextId += 1
  return `kit-${nextId}`
}

// Read as the browser reads it, so case, spaces and line breaks hide nothing
function isScriptAddress(value) {
  try {
    return SCRIPT_PROTOCOLS.includes(new URL(String(value), location.href).protocol)
  } catch {
    return false
  }
}

// Answers false to every open dialog: what it asks about has gone with its page. The shell calls this on leaving a page.
export function dismissDialogs() {
  for (const close of [...openDialogs]) close(false)
}

// An element from a tag, properties and children. A string child is a text node. Events are on<name> functions,
// `class`, `aria-*` and `data-*` are attributes, and an `aria-*` boolean is written as the word; a script address is
// dropped; a `style` is refused, the policy would drop it anyway.
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag)
  for (const [name, value] of Object.entries(props ?? {})) {
    if (value === undefined || value === null) continue
    if (name.startsWith('aria-') && typeof value === 'boolean') {
      el.setAttribute(name, String(value))
      continue
    }
    if (value === false) continue
    if (name === 'style') throw new Error('the policy refuses a style attribute: use a class')
    if (ADDRESS_ATTRIBUTES.includes(name.toLowerCase()) && isScriptAddress(value)) continue
    if (name.startsWith('on')) {
      if (typeof value === 'function') el.addEventListener(name.slice(2).toLowerCase(), value)
    } else if (name === 'value') el.value = value
    else if (value === true) el.setAttribute(name, '')
    else el.setAttribute(name, String(value))
  }
  el.append(...children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false))
  return el
}

// Whether a control's handler lets its value change. A handler that is no function is none. A call cut by leaving the
// page changes nothing and is no page error, and any other failure stays the page's.
async function accepted(onChange, value) {
  if (typeof onChange !== 'function') return true
  try {
    return (await onChange(value)) !== false
  } catch (error) {
    if (error?.name === 'AbortError') return false
    throw error
  }
}

// NaN equals itself here, so a control always knows which option holds its value
function sameValue(left, right) {
  return [left].includes(right)
}

export function createKit(t) {
  function icon(name, { size = 18 } = {}) {
    return iconNode(name, size)
  }

  // variant: 'accent' or 'danger'. With no visible text, `label` names the button.
  function button({ text, icon: glyph, variant, onClick, type = 'button', disabled, label, class: extra } = {}) {
    const classes = ['btn', variant === 'accent' && 'btn-accent', variant === 'danger' && 'btn-danger', extra]
    return h(
      'button',
      { class: classes.filter(Boolean).join(' '), type, disabled, 'aria-label': label, onclick: onClick },
      glyph && icon(glyph, { size: 16 }),
      text,
    )
  }

  // level draws a state dot, always beside a word; accent marks a highlighted chip. With onClick or pressed it is a
  // button, and pressed makes it a filter. Which chips are pressed stays the page's to say: draw again or set aria-pressed.
  function chip({ text, level, mono, accent, pressed, onClick, class: extra } = {}) {
    const hasPressed = pressed !== undefined && pressed !== null
    const action = hasPressed || typeof onClick === 'function'
    const classes = ['chip', mono && 'mono', accent && 'chip-accent', action && 'chip-action', extra]
    return h(
      action ? 'button' : 'span',
      {
        class: classes.filter(Boolean).join(' '),
        type: action ? 'button' : null,
        'aria-pressed': hasPressed ? Boolean(pressed) : null,
        onclick: onClick,
      },
      STATE_LEVELS.includes(level) && h('span', { class: `dot dot-${level}` }),
      text,
    )
  }

  function card({ title, actions, body = true, class: extra } = {}, ...children) {
    const head =
      title || actions?.length
        ? h('div', { class: 'card-head' }, title && h('h2', { class: 'card-title' }, title), actions?.length ? h('div', { class: 'card-actions' }, actions) : null)
        : null
    const content = body ? h('div', { class: 'card-body' }, children) : children
    return h('section', { class: extra ? `card ${extra}` : 'card' }, head, content)
  }

  // A click or a key on the row, not on a control inside it, and not the end of selecting its text. The browser sends a
  // click to what both ends of a press share, so a press from a control to the row's other cell reaches the row: each
  // end is read on its own. A click with no press behind it has a detail of 0 and owes nothing to the last press.
  function tableRow(row) {
    const { cells, selected, onClick } = Array.isArray(row) ? { cells: row } : row
    const action = typeof onClick === 'function'
    const classes = ['table-row', selected && 'table-row-selected', action && 'table-row-action']
    let pressTouchedControl = false
    const onControl = (event) => {
      const control = event.target.closest(ROW_CONTROLS)
      return control !== null && control !== el
    }
    const el = h(
      'div',
      {
        class: classes.filter(Boolean).join(' '),
        role: 'row',
        'aria-current': selected ? 'true' : null,
        tabindex: action ? '0' : null,
        onclick: action
          ? (event) => {
              if (onControl(event) || (event.detail > 0 && pressTouchedControl)) return
              if (!window.getSelection().isCollapsed) return
              onClick(event)
            }
          : null,
        onkeydown: action
          ? (event) => {
              if (event.target !== el || event.repeat || (event.key !== 'Enter' && event.key !== ' ')) return
              // Space would scroll the page
              event.preventDefault()
              onClick(event)
            }
          : null,
      },
      cells.map((cell) => h('div', { class: 'table-cell', role: 'cell' }, cell)),
    )
    if (action) {
      // While capturing, so that a control stopping its own events still counts
      const pressStarts = (event) => {
        pressTouchedControl = onControl(event)
      }
      const pressEnds = (event) => {
        pressTouchedControl ||= onControl(event)
      }
      el.addEventListener('pointerdown', pressStarts, true)
      el.addEventListener('pointerup', pressEnds, true)
    }
    return el
  }

  // Drawing a table again removes the row holding the focus, which would send a keyboard user back to the start of the
  // document. If the table built now replaces that row's table, with the same head, the row at the same place takes the
  // focus back, or the last one that can hold it. Run once the page has put the new table in, and only if nothing else
  // has the focus by then.
  function keepRowFocus(inner) {
    const held = document.activeElement
    if (!held?.matches?.('.table-row-action')) return
    const oldRows = [...held.parentElement.children]
    if (oldRows[0].textContent !== inner.firstElementChild.textContent) return
    const place = oldRows.indexOf(held)
    queueMicrotask(() => {
      if (held.isConnected || !inner.isConnected || document.activeElement !== document.body) return
      const same = inner.children[place]
      const target = same?.matches('.table-row-action') ? same : [...inner.querySelectorAll(':scope > .table-row-action')].at(-1)
      target?.focus({ preventScroll: true })
    })
  }

  // grid is the columns' fixed grid; a cell is a string or a node. Scrolls sideways inside its card on a small screen.
  // A row is a list of cells or {cells, selected, onClick}: selected is the row the page is showing, onClick makes the
  // whole row a control. Which row is selected stays the page's to say: draw the table again, and the focus stays.
  function table({ columns, rows, grid, minWidth } = {}) {
    const inner = h(
      'div',
      { role: 'table' },
      h(
        'div',
        { class: 'table-row', role: 'row' },
        columns.map((column) => h('span', { class: 'label table-cell', role: 'columnheader' }, column)),
      ),
      rows.map(tableRow),
    )
    inner.style.setProperty('--table-grid', grid ?? `repeat(${columns.length}, minmax(0, 1fr))`)
    if (minWidth) inner.style.minWidth = `${minWidth}px`
    keepRowFocus(inner)
    const hasControls = rows.some((row) => typeof row.onClick === 'function')
    return h('div', { class: hasControls ? 'table table-with-controls' : 'table' }, inner)
  }

  function described(control, help, error) {
    const helpId = help ? uniqueId() : null
    const errorId = uniqueId()
    control.setAttribute('aria-describedby', helpId ? `${helpId} ${errorId}` : errorId)
    if (error) control.setAttribute('aria-invalid', 'true')
    return [
      help && h('span', { class: 'field-help', id: helpId }, help),
      h('span', { class: 'field-error', id: errorId, hidden: !error }, error ?? ''),
    ]
  }

  function field({ label, name, value, type = 'text', help, error, placeholder, mono, disabled, required, autocomplete } = {}) {
    const input = h('input', {
      class: mono ? 'input mono' : 'input',
      name,
      type,
      value,
      placeholder,
      disabled,
      required,
      autocomplete,
    })
    const after = described(input, help, error)
    return h('label', { class: error ? 'field field-invalid' : 'field' }, label, input, after)
  }

  // options: [{value, text}]
  function select({ label, name, options, value, help, error, disabled, onChange } = {}) {
    const control = h(
      'select',
      { class: 'input', name, disabled, onchange: onChange },
      options.map((option) => h('option', { value: option.value }, option.text)),
    )
    if (value !== undefined) control.value = value
    const after = described(control, help, error)
    return h('label', { class: error ? 'field field-invalid' : 'field' }, label, control, after)
  }

  // label says the action. onChange receives the new value; returning false keeps the old one.
  function toggle({ label, on = false, onChange, disabled } = {}) {
    const el = h(
      'button',
      {
        class: 'toggle',
        type: 'button',
        'aria-label': label,
        'aria-pressed': String(Boolean(on)),
        disabled,
        onclick: async () => {
          const next = el.getAttribute('aria-pressed') !== 'true'
          if (await accepted(onChange, next)) el.setAttribute('aria-pressed', String(next))
        },
      },
      h('span', { class: 'toggle-knob' }),
    )
    return el
  }

  // items: [{id, text}]
  function tabs({ items, active, onSelect, label } = {}) {
    const buttons = items.map((item) =>
      h(
        'button',
        {
          class: 'tab',
          type: 'button',
          role: 'tab',
          'aria-selected': String(item.id === active),
          onclick: () => {
            buttons.forEach((other, index) => other.setAttribute('aria-selected', String(items[index].id === item.id)))
            onSelect?.(item.id)
          },
        },
        item.text,
      ),
    )
    return h('div', { class: 'tabs', role: 'tablist', 'aria-label': label }, buttons)
  }

  // options: [{value, text}]; label names the group. onChange receives the new value; returning false keeps the old
  // one, and clicks wait for its answer. To change the value from outside, draw it again. The values are read once, as
  // the page may reuse its list for its next draw, and of two equal values only the first says it is chosen.
  function segmented({ label, options, value, onChange, disabled, class: extra } = {}) {
    const values = options.map((option) => option.value)
    const pressedAt = (chosen) => values.findIndex((other) => sameValue(other, chosen))
    let current = value
    let waiting = false
    const choose = async (next) => {
      if (waiting || sameValue(next, current)) return
      waiting = true
      try {
        if (!(await accepted(onChange, next))) return
      } finally {
        waiting = false
      }
      current = next
      buttons.forEach((el, index) => el.setAttribute('aria-pressed', String(index === pressedAt(next))))
    }
    const buttons = options.map((option, index) =>
      h(
        'button',
        {
          class: 'segment',
          type: 'button',
          disabled,
          'aria-pressed': index === pressedAt(value),
          onclick: () => choose(values[index]),
        },
        option.text,
      ),
    )
    return h('div', { class: extra ? `segmented ${extra}` : 'segmented', role: 'group', 'aria-label': label }, buttons)
  }

  // block keeps line breaks and scrolls sideways
  function code(text, { block = false, class: extra } = {}) {
    const classes = ['code', block && 'code-block', extra]
    return h(block ? 'pre' : 'code', { class: classes.filter(Boolean).join(' ') }, text)
  }

  // Resolves to true or false. Escape counts as Cancel, and so does leaving the page. `body` is drawn under the text, and
  // with `held` the answer waits until the function it receives is called with true. `other`, {text, value}, adds a third
  // button between the two, which resolves to its value and is never held.
  function confirm({ title, text, body, held = false, confirm: yes, cancel: no, danger = true, other } = {}) {
    return new Promise((resolve) => {
      const close = (answer) => {
        if (!openDialogs.delete(close)) return
        dialog.close()
        dialog.remove()
        resolve(answer)
      }
      const answer = button({
        text: yes ?? t('common.confirm'),
        variant: danger ? 'danger' : 'accent',
        onClick: () => close(true),
      })
      answer.disabled = held
      const dialog = h(
        'dialog',
        { class: 'card dialog', 'aria-label': title ?? text },
        h(
          'div',
          { class: 'dialog-body' },
          title && h('h2', { class: 'card-title' }, title),
          text && h('p', {}, text),
          typeof body === 'function' ? body((allowed) => (answer.disabled = !allowed)) : body,
          h(
            'div',
            { class: 'dialog-actions' },
            button({ text: no ?? t('common.cancel'), onClick: () => close(false) }),
            other && button({ text: other.text, class: 'dialog-other', onClick: () => close(other.value) }),
            answer,
          ),
        ),
      )
      // A key held since before the dialog opened must not answer it unread
      dialog.addEventListener('keydown', (event) => {
        if (event.repeat && ACTIVATING_KEYS.includes(event.key)) event.preventDefault()
      })
      dialog.addEventListener('cancel', (event) => {
        event.preventDefault()
        close(false)
      })
      document.body.append(dialog)
      openDialogs.add(close)
      dialog.showModal()
    })
  }

  // A button that copies `text` and says how it went for a moment
  function copy({ text, label, class: extra } = {}) {
    const rest = label ?? t('common.copy')
    let timer = null
    const el = h(
      'button',
      {
        class: extra ? `btn ${extra}` : 'btn',
        type: 'button',
        onclick: async () => {
          const copied = await copyText(text, el)
          el.textContent = copied ? t('common.copied') : t('common.copy_failed')
          clearTimeout(timer)
          timer = setTimeout(() => {
            el.textContent = rest
          }, COPIED_MS)
        },
      },
      rest,
    )
    return el
  }

  return { h, button, chip, card, table, field, select, toggle, segmented, tabs, code, icon, confirm, copy }
}
