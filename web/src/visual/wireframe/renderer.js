// Shared rendering helpers for wireframe visuals, used by WireframeAsset (one asset
// per canvas, in the platform) and WireframeScene (many assets and their graphs in one
// canvas, in the demo video). Geometry comes from assets.js in both cases.

import * as THREE from 'three'

/** Colours from the page's design tokens, with the platform's values as fallbacks. */
export function readTokens() {
  const css = typeof document !== 'undefined' ? getComputedStyle(document.documentElement) : null
  const t = (name, fallback) => css?.getPropertyValue(name).trim() || fallback
  return {
    ink: t('--ink', '#172b38'),
    accent: t('--orange', '#e66b3c'),
    accentBright: t('--orange-bright', '#f2814f'),
    rule: t('--rule-strong', '#d2d0c7'),
    paper: t('--paper', '#f4f2eb'),
    paperLight: t('--paper-light', '#fbfaf6'),
    night: t('--night', '#152a37'),
    nightDeep: t('--night-deep', '#101f2a'),
  }
}

/**
 * A transparent WebGL renderer, or null if WebGL is unavailable.
 * preserveDrawingBuffer keeps the last frame readable, which headless capture
 * (the video renderer) needs; the platform leaves it off.
 */
export function createRenderer({ preserveDrawingBuffer = false } = {}) {
  try {
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer })
    renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio || 1, 2))
    return renderer
  } catch {
    return null
  }
}

/** Every line object under ``root``, in a stable order (the order they were built in). */
export function lineParts(root) {
  const parts = []
  root.traverse((o) => { if (o.isLineSegments || o.isLine) parts.push(o) })
  return parts
}

/**
 * Reveal an object's outlines progressively, as if drawn line by line.
 * ``progress`` 0 shows nothing, 1 shows everything.
 */
export function applyDraw(parts, progress) {
  const counts = parts.map((p) => p.geometry.getAttribute('position').count)
  const total = counts.reduce((a, b) => a + b, 0)
  let budget = Math.round(Math.max(0, Math.min(1, progress)) * total)
  parts.forEach((p, i) => {
    const n = Math.min(counts[i], budget)
    p.geometry.setDrawRange(0, n - (n % 2))
    p.visible = n > 1
    budget -= n
  })
}

/** Free every geometry and material under ``root``. */
export function disposeTree(root) {
  root.traverse((o) => {
    o.geometry?.dispose()
    const m = o.material
    if (Array.isArray(m)) m.forEach((x) => x.dispose())
    else m?.dispose()
  })
}
