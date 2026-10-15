// Records the v5 draft's new footage from the local build of main (platform-gcs, port 8100):
// the new-project block (N1–N4: Connect telemetry, sample check, ingestion result, status view)
// and re-recordings of the Projects view and Composition patterns (s1_1_v5, s4_1_v5) with the
// same moves as capture/section3.mjs. The v4 footage in public/s3/ is left as it is.
// The two Dataflow stills are Waqar's cropped screenshots (video/review-stills/); the console
// is never recorded.
// Usage: PLATFORM_URL=... node capture/section3b.mjs [shot ...]     Output: public/s3/<shot>/

import { chromium } from 'playwright'
import { copyFile, mkdir, writeFile, rm } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.PLATFORM_URL || 'http://localhost:8100'
const OUT = path.resolve('public/s3')
const STILLS = path.resolve('review-stills')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// The same visible pointer, glide and click as capture/section3.mjs.
const POINTER = `
  window.addEventListener('DOMContentLoaded', () => {
    const c = document.createElement('div')
    c.id = '__pointer'
    c.innerHTML = '<svg width="30" height="30" viewBox="0 0 30 30"><path d="M4 2 L4 24 L10 18.5 L14.5 28 L18.5 26.2 L14.2 16.8 L22 16.8 Z" fill="#172b38" stroke="#fbfaf6" stroke-width="1.8" stroke-linejoin="round"/></svg>'
    Object.assign(c.style, { position: 'fixed', left: '0px', top: '0px', zIndex: 2147483647, pointerEvents: 'none', transition: 'transform 120ms ease-out', transformOrigin: '4px 2px' })
    document.body.appendChild(c)
    document.addEventListener('mousemove', (e) => { c.style.left = (e.clientX - 4) + 'px'; c.style.top = (e.clientY - 2) + 'px' }, true)
    document.addEventListener('mousedown', () => { c.style.transform = 'scale(0.82)' }, true)
    document.addEventListener('mouseup', () => { c.style.transform = 'scale(1)' }, true)
  })`

let mouse = { x: 960, y: 640 }
async function glide(page, x, y, ms = 900) {
  const steps = Math.max(8, Math.round(ms / 16))
  const from = { ...mouse }
  for (let i = 1; i <= steps; i++) {
    const t = i / steps
    const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2
    await page.mouse.move(from.x + (x - from.x) * e, from.y + (y - from.y) * e)
    await sleep(16)
  }
  mouse = { x, y }
}
const centre = async (loc) => { const b = await loc.boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2] }
async function click(page, loc, ms = 900) {
  const [x, y] = await centre(loc)
  await glide(page, x, y, ms)
  await sleep(180)
  await page.mouse.down(); await sleep(90); await page.mouse.up()
}

async function screencast(context, page, shot, run, scale = 1, extra = {}) {
  const dir = path.join(OUT, shot)
  await rm(dir, { recursive: true, force: true })
  await mkdir(dir, { recursive: true })
  const cdp = await context.newCDPSession(page)
  const frames = []
  let t0 = null
  cdp.on('Page.screencastFrame', async (f) => {
    const ts = f.metadata.timestamp
    if (t0 == null) t0 = ts
    const file = `${String(frames.length).padStart(5, '0')}.jpg`
    frames.push({ file, t: ts - t0 })
    await writeFile(path.join(dir, file), Buffer.from(f.data, 'base64'))
    await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {})
  })
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: 1920 * scale, maxHeight: 1080 * scale, everyNthFrame: 1 })
  const started = Date.now()
  await run()
  await cdp.send('Page.stopScreencast')
  await sleep(200)
  const duration = (Date.now() - started) / 1000
  await writeFile(path.join(dir, 'frames.json'), JSON.stringify({ duration, frames, ...extra }, null, 1))
  console.log(`${shot}: ${frames.length} frames over ${duration.toFixed(1)} s`)
}

async function interaction(browser, shot, prepare, act, scale = 1) {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: scale })
  await context.addInitScript(POINTER)
  const page = await context.newPage()
  mouse = { x: 960, y: 640 }
  await prepare(page)
  await page.mouse.move(mouse.x, mouse.y)
  await sleep(300)
  const extra = { marks: {}, boxes: {} }
  let started
  await screencast(context, page, shot, () => { started = Date.now(); return act(page, (k) => { extra.marks[k] = (Date.now() - started) / 1000 }, extra.boxes) }, scale, extra)
  await context.close()
}

async function stills(browser, shot, steps) {
  const dir = path.join(OUT, shot)
  await rm(dir, { recursive: true, force: true })
  await mkdir(dir, { recursive: true })
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 })
  const page = await context.newPage()
  const out = []
  for (const [i, step] of steps.entries()) {
    await step.prepare(page)
    await sleep(500)
    const boxes = {}
    for (const [k, loc] of Object.entries(step.boxes(page))) boxes[k] = await loc.boundingBox()
    const file = `still${i}.png`
    await page.screenshot({ path: path.join(dir, file) })
    out.push({ file, boxes })
  }
  await writeFile(path.join(dir, 'stills.json'), JSON.stringify({ stills: out, viewport: [1920, 1080] }, null, 1))
  console.log(`${shot}: ${out.length} stills`)
  await context.close()
}

const toTop = (loc, offset = 120) => loc.first().evaluate((el, o) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - o), offset)
const smoothTo = async (page, loc, offset) => {
  await loc.first().evaluate((el, o) => window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - o, behavior: 'smooth' }), offset)
  await sleep(1300)
}
const h4 = (p, t) => p.locator('.h4', { hasText: t }).first()
const section = (p, t) => h4(p, t).locator('xpath=..')
const step = (p) => p.locator('.panel', { has: p.locator('h3', { hasText: 'Connect telemetry' }) }).first()
const ingestion = async (p) => { await p.goto(`${BASE}/#ingestion`); await h4(p, '1 · Source').waitFor(); await sleep(800) }

const SHOTS = {
  // 1.1 Projects, re-recorded from the current build: the same moves as v4's s1_1.
  's1_1_v5': (b) => interaction(b, 's1_1_v5', async (p) => {
    await p.goto(`${BASE}/#projects`)
    await p.getByText(/Verified evidence ·/).first().waitFor()
    await p.waitForFunction(() => document.querySelectorAll('.project-card .pill').length >= 2)
    await sleep(800)
  }, async (p, mark) => {
    await sleep(2200)
    const cards = p.locator('.project-card')
    mark('to_first')
    await glide(p, ...(await centre(cards.nth(0))), 1200); mark('on_first'); await sleep(3000)
    mark('to_second')
    await glide(p, ...(await centre(cards.nth(1))), 1200); mark('on_second'); await sleep(3000)
    mark('to_open')
    await click(p, cards.nth(0).locator('.text-link'), 1100)
    await p.getByText('Evidence verified').waitFor(); await sleep(1400)
  }),

  // 4.1 Composition patterns, re-recorded: the same moves as v4's s4_1.
  's4_1_v5': (b) => interaction(b, 's4_1_v5', async (p) => {
    await p.goto(`${BASE}/#composition`)
    await p.getByText('Sequential: Compressor train').waitFor()
    await p.locator('.compare').evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 120))
    await sleep(600)
  }, async (p) => {
    await sleep(1200)
    const a = p.locator('article.panel').first()
    await click(p, a.locator('g.node', { hasText: 'Compressor' }), 1000); await sleep(2600)
    const motor = a.locator('g.node', { hasText: 'Motor' })
    await click(p, motor, 900); await sleep(900)
    await click(p, motor, 300); await sleep(3200)
  }),

  // N1 Connect telemetry (#ingestion, example project): the source choice, the twin and plant
  // streams with the synthetic-plant line, the per-channel contract, the comparison rule.
  'n1': (b) => interaction(b, 'n1', async (p) => {
    await ingestion(p)
    await toTop(h4(p, '1 · Source'), 140)
    await sleep(500)
  }, async (p, mark, boxes) => {
    await sleep(600)
    mark('source'); boxes.source = await section(p, '1 · Source').boundingBox()
    await click(p, step(p).getByRole('radio', { name: /Push to Pub\/Sub/ }), 900); await sleep(500)
    await glide(p, 1890, 1050, 700); await sleep(400) // the pointer out of the way of the text
    mark('to_streams'); await smoothTo(p, p.locator('[data-stream="twin"]'), 200)
    mark('streams'); boxes.streams = await p.locator('[data-stream="twin"]').locator('xpath=..').boundingBox(); await sleep(2600)
    mark('to_table'); await smoothTo(p, p.locator('table:has(tr[data-values])'), 90)
    mark('table'); boxes.table = await p.locator('table:has(tr[data-values])').boundingBox(); await sleep(2600)
    mark('to_rule'); await smoothTo(p, h4(p, '3 · Comparison rule'), 260)
    mark('rule'); boxes.rule = await section(p, '3 · Comparison rule').boundingBox(); await sleep(2800)
    mark('end')
  }, 2),

  // N2 Sample check: valid, change the unit, recompute the hashes (the page's own button), check:
  // rejected with unknown_channel and its reason.
  'n2': (b) => interaction(b, 'n2', async (p) => {
    await ingestion(p)
    await toTop(h4(p, '7 · Check a sample message'), 150)
    await sleep(500)
  }, async (p, mark, boxes) => {
    const s = step(p), data = s.locator('#sample-data'), result = s.getByTestId('check-result')
    boxes.sample = await section(p, '7 · Check a sample message').boundingBox()
    await sleep(600)
    mark('start')
    await click(p, s.getByRole('button', { name: 'Check message' }), 900)
    await result.getByText('Valid').waitFor(); mark('valid'); await sleep(1400)
    const original = await data.inputValue()
    await click(p, data, 800)
    await data.fill(original.replace(/"unit":\s*"[^"]*"/, '"unit": "furlongs"')); mark('edited'); await sleep(1000)
    await click(p, s.getByRole('button', { name: 'Recompute content_sha256 and reading_key' }), 800); await sleep(500)
    await click(p, s.getByRole('button', { name: 'Check message' }), 800)
    await result.getByText('unknown_channel').waitFor(); mark('rejected')
    boxes.result = await result.boundingBox()
    await sleep(3200)
    mark('end')
  }, 2),

  // N3 (app stills): the recorded result of replay r1015b, and the Connect step's two-source row.
  'n3_app': (b) => stills(b, 'n3_app', [{
    prepare: async (p) => { await ingestion(p); await toTop(p.locator('h3', { hasText: 'Recorded result of the last replay' }), 150) },
    boxes: (p) => {
      const panel = p.locator('.panel', { has: p.locator('h3', { hasText: 'Recorded result of the last replay' }) }).first()
      return { panel, counts: panel.locator('table').nth(0), checks: panel.locator('table').nth(1) }
    },
  }, {
    prepare: async (p) => { await toTop(h4(p, '5 · Where each value comes from'), 300) },
    boxes: (p) => ({
      table: section(p, '5 · Where each value comes from').locator('table'),
      row: p.locator('tr', { has: p.locator('td', { hasText: 'Built and run on replayed synthetic data on' }) }).first(),
    }),
  }]),

  // N3 (Dataflow stills): Waqar's cropped screenshots of the finished r1015b job, copied as they are.
  // Boxes are in image pixels; the counters box leaves out the per-pane duplicates counter (88,
  // counted across re-fired panes), which would read as a second duplicates figure beside 44.
  'n3_df': async () => {
    const dir = path.join(OUT, 'n3_df')
    await rm(dir, { recursive: true, force: true }); await mkdir(dir, { recursive: true })
    await copyFile(path.join(STILLS, 'dataflow_r1015b_graph.png'), path.join(dir, 'graph.png'))
    await copyFile(path.join(STILLS, 'dataflow_r1015b_counters.png'), path.join(dir, 'counters.png'))
    const stillsJson = { images: [
      { file: 'graph.png', size: [1677, 1005], boxes: { all: { x: 600, y: 120, width: 480, height: 880 }, top: { x: 600, y: 120, width: 480, height: 330 } } },
      { file: 'counters.png', size: [829, 500], boxes: { rows: { x: 12, y: 314, width: 806, height: 178 } } },
    ] }
    await writeFile(path.join(dir, 'images.json'), JSON.stringify(stillsJson, null, 1))
    console.log('n3_df: 2 images')
  },

  // N4 Status of this prototype: press the button, hold on the first line, then each section.
  'n4': (b) => interaction(b, 'n4', async (p) => {
    await ingestion(p)
    await toTop(h4(p, '8 · Enable'), 420)
    await sleep(500)
  }, async (p, mark, boxes) => {
    await sleep(600)
    mark('click')
    await click(p, step(p).getByRole('button', { name: 'Register project and enable connection' }), 1000)
    const view = p.getByTestId('prototype-status'); await view.waitFor()
    await glide(p, 1890, 1050, 500)
    await sleep(300); await smoothTo(p, view, 110)
    mark('open')
    const sub = (t) => view.locator('.h4', { hasText: t }).locator('xpath=..')
    boxes.view = await view.boundingBox()
    boxes.first = await view.locator('h3').boundingBox()
    boxes.line = await view.locator('p').first().boundingBox()
    boxes.built = await sub('Built and demonstrated').boundingBox()
    boxes.designed = await sub('Designed, not built').boundingBox()
    boxes.golive = await sub('What a real go-live needs').boundingBox()
    await sleep(9500)
    mark('end')
  }, 2),
}

const wanted = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(SHOTS)
const browser = await chromium.launch({ channel: 'chrome' })
for (const s of wanted) await SHOTS[s](browser)
await browser.close()
