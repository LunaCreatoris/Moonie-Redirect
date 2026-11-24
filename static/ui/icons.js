// Source: Moonie Redirect 7.0.1 admin UI, ui/icons.js, verbatim. Added: the filled glyphs of Material
// Symbols (GLYPH, glyphNode), for the sidebar's Settings and Log out (D30).
// The interface's glyphs. Path data is copied from 7.0.1's icon set as it is: never draw a new one here.

const SVG = 'http://www.w3.org/2000/svg'

export const ICON = {
  overview: 'M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 9h8V3h-8z',
  commands: 'M4 17l6-6-6-6M12 19h8',
  profile: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0',
  links:
    'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
  page: 'M5 4h14v16H5zM9 9h6M9 13h6M9 17h3',
  plugins: 'M4 7h4V4h4v3h4v4h3v4h-3v4H4z',
  keys: 'M15 7a4 4 0 1 1-3.9 4.9L4 19v2h3v-2h2v-2h2l1.1-1.1A4 4 0 0 1 15 7z',
  webhook: 'M8 9l-4 3 4 3M16 9l4 3-4 3M14 5l-4 14',
  logs: 'M4 6h16M4 12h16M4 18h10',
  instance: 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6',
  reload: 'M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6',
  check: 'M5 12l5 5 9-10',
}

// Glyphs drawn filled, copied as they are from the package's outlined SVGs (weight 400, fill 0, grade 0, its one optical
// size, 48), in its 0 -960 960 960 box.
// Source: @material-symbols/svg-400 0.48.3 (outlined/settings.svg, outlined/logout.svg), Apache-2.0, licence in
// LICENSE-material-symbols.txt
export const GLYPH = {
  settings:
    'm388-80-20-126q-19-7-40-19t-37-25l-118 54-93-164 108-79q-2-9-2.5-20.5T185-480q0-9 .5-20.5T188-521L80-600l93-164 118 54q16-13 37-25t40-18l20-127h184l20 126q19 7 40.5 18.5T669-710l118-54 93 164-108 77q2 10 2.5 21.5t.5 21.5q0 10-.5 21t-2.5 21l108 78-93 164-118-54q-16 13-36.5 25.5T592-206L572-80H388Zm48-60h88l14-112q33-8 62.5-25t53.5-41l106 46 40-72-94-69q4-17 6.5-33.5T715-480q0-17-2-33.5t-7-33.5l94-69-40-72-106 46q-23-26-52-43.5T538-708l-14-112h-88l-14 112q-34 7-63.5 24T306-642l-106-46-40 72 94 69q-4 17-6.5 33.5T245-480q0 17 2.5 33.5T254-413l-94 69 40 72 106-46q24 24 53.5 41t62.5 25l14 112Zm44-210q54 0 92-38t38-92q0-54-38-92t-92-38q-54 0-92 38t-38 92q0 54 38 92t92 38Zm0-130Z',
  logout:
    'M180-120q-24 0-42-18t-18-42v-600q0-24 18-42t42-18h299v60H180v600h299v60H180Zm486-185-43-43 102-102H360v-60h363L621-612l43-43 176 176-174 174Z',
}

const CRESCENT = 'M21 7a11 11 0 1 0 6 16A9 9 0 0 1 21 7z'
const ERROR_MARK = 'M12 7.5v5.5M12 16.2v.1'

function svg(tag, attributes, ...children) {
  const el = document.createElementNS(SVG, tag)
  for (const [name, value] of Object.entries(attributes)) el.setAttribute(name, String(value))
  el.append(...children)
  return el
}

function frame(size, viewBox, strokeWidth, ...children) {
  return svg(
    'svg',
    {
      width: size,
      height: size,
      viewBox,
      fill: 'none',
      stroke: 'currentColor',
      'stroke-width': strokeWidth,
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      'aria-hidden': 'true',
    },
    ...children,
  )
}

// A stroked icon of the map. An unknown name draws `page`.
export function iconNode(name, size = 18) {
  const data = Object.hasOwn(ICON, name) ? ICON[name] : ICON.page
  return frame(size, '0 0 24 24', name === 'check' ? 3 : 1.8, svg('path', { d: data }))
}

// A filled glyph of Material Symbols, at the visual weight of the 18 px stroked icons: its thin optical size 48 is drawn
// at 20 px, which brings its strokes and its shape to theirs. An unknown name throws: there is no stand-in for a glyph
// that was never vendored.
export function glyphNode(name, size = 20) {
  if (!Object.hasOwn(GLYPH, name)) throw new Error(`unknown glyph ${name}`)
  return svg(
    'svg',
    { width: size, height: size, viewBox: '0 -960 960 960', fill: 'currentColor', 'aria-hidden': 'true' },
    svg('path', { d: GLYPH[name] }),
  )
}

// The danger circle of the error state
export function errorMark(size = 44) {
  return frame(size, '0 0 24 24', 1.6, svg('circle', { cx: 12, cy: 12, r: 9 }), svg('path', { d: ERROR_MARK }))
}

// The crescent as a line, for empty states
export function crescentMark(size = 48) {
  return frame(size, '0 0 34 34', 1.5, svg('circle', { cx: 17, cy: 17, r: 15 }), svg('path', { d: CRESCENT }))
}

// The logo in the interface: the disc, and the crescent in the application's accent, both coloured by class
export function logoMark(size = 34) {
  return svg(
    'svg',
    { width: size, height: size, viewBox: '0 0 34 34', 'aria-hidden': 'true' },
    svg('circle', { class: 'logo-disc', cx: 17, cy: 17, r: 15, 'stroke-width': 1.5 }),
    svg('path', { class: 'logo-moon', d: CRESCENT }),
  )
}
