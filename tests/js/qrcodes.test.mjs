// Ported from moonie-redirect 7.0.1 tests/js/qrcodes.test.mjs; the thumbnail reads this app's route. The pure part of the QR page, and what keeps a logo from ever joining the document.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  designFrom,
  downloadAddress,
  downloadName,
  drawingProblem,
  imageAddress,
  latestOnly,
  LOGO_MAX_BYTES,
  logoProblem,
  matchesQr,
  percentOf,
  thumbnailAddress,
} from '../../static/ui/qrcodes.js'

const FIELDS = {
  color: '#0b3d91',
  eye_color: '#c2185b',
  background: '#ffffff',
  transparent: false,
  module_style: 'dots',
  eye_style: 'circle',
  logo_size: '22',
  margin: '4',
}

test('a design holds what the controls hold, as the numbers the instance takes', () => {
  assert.deepEqual(designFrom(FIELDS, null), {
    color: '#0b3d91',
    eye_color: '#c2185b',
    background: '#ffffff',
    module_style: 'dots',
    eye_style: 'circle',
    logo: null,
    logo_size: 0.22,
    margin: 4,
  })
})

test('transparent wins over the colour the control still holds', () => {
  assert.equal(designFrom({ ...FIELDS, transparent: true }, null).background, 'transparent')
})

test('a margin of zero stays a number', () => {
  assert.equal(designFrom({ ...FIELDS, margin: '0' }, null).margin, 0)
})

test('a logo goes as it is', () => {
  assert.equal(designFrom(FIELDS, 'data:image/png;base64,AAAA').logo, 'data:image/png;base64,AAAA')
})

for (let percent = 10; percent <= 30; percent += 1) {
  test(`a logo size of ${percent}% comes back whole from its share`, () => {
    const { logo_size: share } = designFrom({ ...FIELDS, logo_size: String(percent) }, null)
    assert.ok(share >= 0.1 && share <= 0.3)
    assert.equal(percentOf(share), percent)
  })
}

test('a file at the limit goes to the instance, and one past it does not', () => {
  assert.equal(logoProblem({ size: LOGO_MAX_BYTES }), null)
  assert.equal(logoProblem({ size: LOGO_MAX_BYTES + 1 }), 'redirect.design_logo_size')
  assert.equal(logoProblem({ size: 0 }), null)
})

test('the image address survives every character a drawing can hold', () => {
  const svg = '<svg a="#1 %20 & \' é 日本 \n"/>'
  const address = imageAddress(svg)
  assert.ok(address.startsWith('data:image/svg+xml;charset=utf-8,'))
  assert.equal(address.includes('#'), false)
  assert.equal(address.includes('"'), false)
  assert.equal(decodeURIComponent(address.split(',').slice(1).join(',')), svg)
})

test('the file takes the last segment of the path', () => {
  assert.equal(downloadName({ slug: 'QRcodes/Dish-of-the-day' }), 'Dish-of-the-day.svg')
  assert.equal(downloadName({ slug: 'plain' }), 'plain.svg')
})

// A call the test ends by hand, one by one
function heldCalls() {
  const calls = []
  const run = () =>
    new Promise((done, failed) => {
      calls.push({ done, failed })
    })
  return { calls, run }
}

const turn = () => new Promise((done) => setImmediate(done))

test('asked while it runs, it runs once more however many times it was asked', async () => {
  const { calls, run } = heldCalls()
  const ask = latestOnly(run)
  const first = ask()
  ask()
  ask()
  ask()
  assert.equal(calls.length, 1)
  calls[0].done()
  await turn()
  assert.equal(calls.length, 2)
  calls[1].done()
  await first
  assert.equal(calls.length, 2)
})

test('a later call runs by itself once it is idle', async () => {
  const { calls, run } = heldCalls()
  const ask = latestOnly(run)
  const first = ask()
  calls[0].done()
  await first
  const second = ask()
  assert.equal(calls.length, 2)
  calls[1].done()
  await second
})

test('settled comes once, when nothing is left to do', async () => {
  const { calls, run } = heldCalls()
  let settled = 0
  const ask = latestOnly(run, () => {
    settled += 1
  })
  const first = ask()
  ask()
  calls[0].done()
  await turn()
  assert.equal(settled, 0)
  calls[1].done()
  await first
  assert.equal(settled, 1)
})

test('a call that throws leaves it able to run, and settled still comes', async () => {
  const { calls, run } = heldCalls()
  let settled = 0
  const ask = latestOnly(run, () => {
    settled += 1
  })
  const first = ask()
  calls[0].failed(new Error('no'))
  await assert.rejects(first, /no/)
  assert.equal(settled, 1)
  const second = ask()
  assert.equal(calls.length, 2)
  calls[1].done()
  await second
  assert.equal(settled, 2)
})

test('the page has no way to put markup in the document', async () => {
  const source = await readFile(new URL('../../static/ui/qrcodes.js', import.meta.url), 'utf8')
  for (const way of ['innerHTML', 'outerHTML', 'insertAdjacentHTML', 'DOMParser', 'createContextualFragment', 'document.write', 'srcdoc']) {
    assert.equal(source.includes(way), false, way)
  }
})

test('a change asked during a call that throws runs once, and `settled` waits for it', async () => {
  const calls = []
  let settled = 0
  const ask = latestOnly(
    () =>
      new Promise((done, failed) => {
        calls.push({ done, failed })
      }),
    () => {
      settled += 1
    },
  )
  const first = ask()
  ask()
  ask()
  calls[0].failed(new Error('no'))
  await assert.rejects(first)
  assert.equal(calls.length, 2)
  assert.equal(settled, 0)
  calls[1].done()
  await new Promise((done) => setImmediate(done))
  assert.equal(calls.length, 2)
  assert.equal(settled, 1)
})

test('a call that throws with nothing asked settles and can run again', async () => {
  let settled = 0
  let fail = true
  const ask = latestOnly(
    async () => {
      if (fail) throw new Error('no')
    },
    () => {
      settled += 1
    },
  )
  await assert.rejects(ask())
  assert.equal(settled, 1)
  fail = false
  await ask()
  assert.equal(settled, 2)
})

test('what changes a drawing changes the address of its thumbnail', () => {
  const qr = { id: 'aB3dE6gH', updated_at: '2026-11-02T09:15:00Z', short_url: 'http://198.51.100.1/links/aB3dE6gH' }
  const same = thumbnailAddress(qr)
  assert.equal(thumbnailAddress({ ...qr }), same)
  assert.ok(same.startsWith('/api/links/aB3dE6gH/qr.svg?v='))
  assert.notEqual(thumbnailAddress({ ...qr, updated_at: '2026-11-02T09:15:01Z' }), same)
  assert.notEqual(thumbnailAddress({ ...qr, short_url: 'http://redirect.lan/links/aB3dE6gH' }), same)
  assert.ok(thumbnailAddress({ ...qr, short_url: 'http://a/?x=1&y=2' }).endsWith('to=http%3A%2F%2Fa%2F%3Fx%3D1%26y%3D2'))
})

test('the download asks for the same file as an attachment, and an id is always one segment', () => {
  assert.equal(downloadAddress({ id: 'aB3dE6gH' }), '/api/links/aB3dE6gH/qr.svg?download=1')
  assert.equal(downloadAddress({ id: '../x?y' }), '/api/links/..%2Fx%3Fy/qr.svg?download=1')
})

test('a code with a design this app cannot read has no drawing, and says why', () => {
  assert.equal(drawingProblem({ design: null }), 'redirect.design_unreadable')
  assert.equal(drawingProblem({ design: { color: '#000000' } }), null)
})

const CODE = {
  name: 'Lunch menu',
  slug: 'QRcodes/Lunch-menu',
  target: 'https://cloud.example/menu.pdf',
  public_url: 'http://host.example:8420/redirect/QRcodes/Lunch-menu',
  short_url: 'http://host.example:8420/links/aB3dE6gH',
}

test('what every QR code holds in its address tells no row from another', () => {
  for (const search of ['qrcodes', 'QRcodes/', 'redirect', '/redirect/', '/redirect/qrcodes/', 'links', '/links/']) {
    assert.equal(matchesQr(CODE, search), false, search)
  }
})

test('a QR code answers its name, its path, its target and its short link', () => {
  for (const search of ['lunch', 'lunch-menu', 'qrcodes/lunch', '/redirect/qrcodes/l', 'cloud.example', 'aB3dE6gH', '/links/aB3']) {
    assert.equal(matchesQr(CODE, search), true, search)
  }
})

test('a QR code named or aimed at what every address holds still answers it', () => {
  assert.equal(matchesQr({ ...CODE, name: 'My QRcodes' }, 'qrcodes'), true)
  assert.equal(matchesQr({ ...CODE, target: 'https://a.example/redirect' }, 'redirect'), true)
})
