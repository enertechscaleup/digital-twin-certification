// Records Section 3 from the real platform (served locally, reading the locked evidence
// bucket). Ticked shots are one double-resolution screenshot per tick; interaction shots
// are a Chrome screencast (JPEG frames with timestamps) with a visible pointer.
// Usage: node capture/section3.mjs [shot ...]     Output: public/s3/<shot>/

import { chromium } from 'playwright'
import { mkdir, writeFile, rm } from 'node:fs/promises'
import path from 'node:path'

const BASE = process.env.PLATFORM_URL || 'http://localhost:8100'
const RUN = 'assurance-demo_full_cycle-seed42'
const OUT = path.resolve('public/s3')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// A visible pointer for interaction shots (a headless screencast has none).
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

async function screencast(context, page, shot, run, scale = 1) {
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
  await writeFile(path.join(dir, 'frames.json'), JSON.stringify({ duration, frames }, null, 1))
  console.log(`${shot}: ${frames.length} frames over ${duration.toFixed(1)} s`)
}

async function waitTick(page, n) {
  await page.waitForFunction((n) => document.querySelector('.replay-tick')?.textContent.startsWith(`Tick ${n} `), n, { timeout: 60000 })
  await page.waitForLoadState('networkidle')
  await sleep(350)
}

async function ticked(browser, shot, { url, from, to, tab, focus, scrollTo }) {
  const dir = path.join(OUT, shot)
  await rm(dir, { recursive: true, force: true })
  await mkdir(dir, { recursive: true })
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 })
  const page = await context.newPage()
  await page.goto(`${BASE}${url}`)
  await waitTick(page, from)
  if (tab) { await page.getByRole('tab', { name: tab }).click(); await sleep(400) }
  await page.locator(scrollTo).first().evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 150))
  await sleep(400)
  const boxes = {}
  const shots = []
  for (let t = from; t <= to; t++) {
    if (t > from) { await page.getByRole('button', { name: 'Step forward' }).click(); await waitTick(page, t) }
    const file = `t${String(t).padStart(3, '0')}.png`
    await page.screenshot({ path: path.join(dir, file) })
    shots.push({ tick: t, file })
    if (t === from) for (const [k, sel] of Object.entries(focus || {})) boxes[k] = await page.locator(sel.css, { hasText: sel.text }).first().boundingBox()
  }
  await writeFile(path.join(dir, 'shots.json'), JSON.stringify({ shots, boxes, viewport: [1920, 1080] }, null, 1))
  console.log(`${shot}: ticks ${from}–${to}`)
  await context.close()
}

// ``scale`` 2 records at double resolution, for shots the video zooms into.
async function interaction(browser, shot, prepare, act, scale = 1) {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: scale })
  await context.addInitScript(POINTER)
  const page = await context.newPage()
  mouse = { x: 960, y: 640 }
  await prepare(page)
  await page.mouse.move(mouse.x, mouse.y)
  await sleep(300)
  await screencast(context, page, shot, () => act(page), scale)
  await context.close()
}

const SHOTS = {
  // 1.1 Projects: both projects, hover each, open the compressor train.
  's1_1': (b) => interaction(b, 's1_1', async (p) => {
    await p.goto(`${BASE}/#projects`)
    await p.getByText('Verified evidence · 3 runs').waitFor()
    await p.waitForFunction(() => document.querySelectorAll('.project-card .pill').length >= 2)
    await sleep(800)
  }, async (p) => {
    await sleep(2200)
    const cards = p.locator('.project-card')
    await glide(p, ...(await centre(cards.nth(0))), 1200); await sleep(3000)
    await glide(p, ...(await centre(cards.nth(1))), 1200); await sleep(3000)
    await click(p, cards.nth(0).locator('.text-link'), 1100)
    await p.getByText('Evidence verified').waitFor(); await sleep(1400)
  }),

  // 2.1 Compressor train, whole system, ticks 26–46 (motor nullified live at 36).
  's2_1': (b) => ticked(b, 's2_1', {
    url: `/?run=${RUN}&tick=26&stage=system#oil-gas-compressor-train`, from: 26, to: 46, scrollTo: '#status-h',
  }),

  // 2.2 Fulfilment cell (preview, mock data) playing.
  's2_2': (b) => interaction(b, 's2_2', async (p) => {
    await p.goto(`${BASE}/#amr-fulfilment-cell`)
    await p.locator('#tick').waitFor()
    await p.locator('#tick').evaluate((el) => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
      set.call(el, '8'); el.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await p.locator('#status-h').evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 330))
    await sleep(600)
  }, async (p) => {
    await sleep(1200)
    await click(p, p.getByRole('button', { name: 'Play replay' }), 900)
    await sleep(13000)
  }),

  // 3.1 The real2sim gap crossing tolerance: motor view, ticks 14–19.
  's3_1': (b) => ticked(b, 's3_1', {
    url: `/?run=${RUN}&tick=14#oil-gas-compressor-train`, from: 14, to: 19, scrollTo: '#status-h',
    focus: { channel: { css: '.channel', text: 'Shaft speed' }, card: { css: '.twin-card', text: 'Motor' } },
  }),

  // 3.2 Sticky status: compressor input recovers after the adjustment, status stays flagged.
  's3_2': (b) => ticked(b, 's3_2', {
    url: `/?run=${RUN}&tick=62&stage=system#oil-gas-compressor-train`, from: 62, to: 72, tab: 'Compressor', scrollTo: '#status-h',
    focus: { channel: { css: '.channel', text: 'Drive speed' }, card: { css: '.twin-card', text: 'Compressor' } },
  }),

  // 4.1 Composition patterns: compressor flagged (output twin), then motor nullified (cascade).
  's4_1': (b) => interaction(b, 's4_1', async (p) => {
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

  // 4.2 Evidence: hash-chained ledger entry, then re-verify from the bucket.
  's4_2': (b) => interaction(b, 's4_2', async (p) => {
    await p.goto(`${BASE}/?run=${RUN}&tick=79&stage=system#oil-gas-compressor-train`)
    await waitTick(p, 79)
    await p.getByText('Evidence ledger').first().evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 150))
    await sleep(600)
  }, async (p) => {
    await sleep(1000)
    await click(p, p.locator('.ledger-row', { hasText: 'Post-state check' }).first(), 1000)
    // Sharp stills of the two moments the video zooms into (the screen is still meanwhile).
    await sleep(700); await p.screenshot({ path: path.join(OUT, 's4_2', 'hold_ledger.png') }); await sleep(1500)
    await p.evaluate(() => { const el = [...document.querySelectorAll('.panel')].find((x) => x.textContent.includes('Evidence integrity')); window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 200, behavior: 'smooth' }) })
    await sleep(1400)
    await click(p, p.getByRole('button', { name: /Re-verify now/ }), 900)
    await p.getByText(/just now in/).waitFor({ timeout: 60000 })
    await sleep(400); await p.screenshot({ path: path.join(OUT, 's4_2', 'hold_integrity.png') }); await sleep(1700)
  }, 2),
}

const wanted = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(SHOTS)
const browser = await chromium.launch({ channel: 'chrome' })
for (const s of wanted) await SHOTS[s](browser)
await browser.close()
