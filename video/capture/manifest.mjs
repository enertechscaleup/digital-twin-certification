// Collects capture metadata (frame timings, tick shots, element boxes) into src/s3data.json.
import { readdir, readFile, writeFile } from 'node:fs/promises'
const out = {}
for (const shot of (await readdir('public/s3')).sort()) {
  for (const f of ['frames.json', 'shots.json']) {
    try { out[shot] = { kind: f === 'frames.json' ? 'screencast' : 'ticked', ...JSON.parse(await readFile(`public/s3/${shot}/${f}`, 'utf8')) } } catch { /* other kind */ }
  }
}
await writeFile('src/s3data.json', JSON.stringify(out))
console.log(Object.entries(out).map(([k, v]) => `${k}:${v.kind}`).join(' '))
