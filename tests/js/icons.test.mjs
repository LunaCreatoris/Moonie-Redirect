// The glyphs: the stroked icons of the kit and the filled glyphs of Material Symbols, drawn into a fake document.
import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'

import { GLYPH, ICON, glyphNode, iconNode } from '../../static/ui/icons.js'

const SVG = 'http://www.w3.org/2000/svg'

// Just what icons.js asks of a document: SVG elements with attributes and children
function fakeDocument() {
  return {
    createElementNS(namespace, tag) {
      return {
        namespace,
        tag,
        attributes: {},
        children: [],
        setAttribute(name, value) {
          this.attributes[name] = value
        },
        append(...nodes) {
          this.children.push(...nodes)
        },
      }
    },
  }
}

let saved
before(() => {
  saved = globalThis.document
  globalThis.document = fakeDocument()
})
after(() => {
  globalThis.document = saved
})

test('a glyph is filled with the text colour, with no stroke, in the box of Material Symbols', () => {
  const node = glyphNode('settings')
  assert.equal(node.namespace, SVG)
  assert.equal(node.tag, 'svg')
  assert.deepEqual(node.attributes, {
    width: '20',
    height: '20',
    viewBox: '0 -960 960 960',
    fill: 'currentColor',
    'aria-hidden': 'true',
  })
  assert.equal(node.children.length, 1)
  assert.equal(node.children[0].tag, 'path')
  assert.deepEqual(node.children[0].attributes, { d: GLYPH.settings })
})

test('a glyph is drawn 2 px over the stroked icons, at their visual weight, and at any size asked', () => {
  const icon = iconNode('instance')
  const glyph = glyphNode('logout')
  assert.equal(Number(glyph.attributes.width), Number(icon.attributes.width) + 2)
  assert.equal(Number(glyph.attributes.height), Number(icon.attributes.height) + 2)
  assert.equal(glyphNode('logout', 24).attributes.width, '24')
  assert.equal(glyphNode('logout', 24).attributes.height, '24')
})

test('the vendored glyphs are Settings and Log out, closed shapes inside their box', () => {
  assert.deepEqual(Object.keys(GLYPH).sort(), ['logout', 'settings'])
  for (const [name, data] of Object.entries(GLYPH)) {
    assert.match(data, /^[Mm][-0-9.,A-Za-z ]+$/, name)
    assert.match(data, /Z$/, name)
    // The box is x 0..960, y -960..0: the first point lands inside it
    const [x, y] = data.slice(1).match(/-?[0-9.]+/g).slice(0, 2).map(Number)
    assert.ok(x >= 0 && x <= 960 && y >= -960 && y <= 0, `${name} starts at ${x},${y}`)
  }
})

test('an unknown glyph throws, and never stands in for another', () => {
  assert.throws(() => glyphNode('nope'), /unknown glyph nope/)
  assert.throws(() => glyphNode('toString'), /unknown glyph toString/)
  assert.throws(() => glyphNode('page'), /unknown glyph page/)
})

test('the stroked icons are unchanged: outlined, no fill, in the 24 box', () => {
  const node = iconNode('links')
  assert.equal(node.attributes.viewBox, '0 0 24 24')
  assert.equal(node.attributes.fill, 'none')
  assert.equal(node.attributes.stroke, 'currentColor')
  assert.equal(node.attributes['stroke-width'], '1.8')
  assert.deepEqual(node.children[0].attributes, { d: ICON.links })
  assert.equal(iconNode('unknown').children[0].attributes.d, ICON.page)
})
