// Synthesizes every narration cue with Google Cloud Text-to-Speech, using the machine's
// Application Default Credentials (gcloud auth application-default login). No API key.
// Output: public/vo/<id>.mp3 and src/vo.json (durations in seconds).
// Usage: node capture/narrate.mjs [cue id ...]   (default: all v4 cues; v5 cue ids may be named)

import { execFileSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { CUES, CUES_V5, VOICE } from '../src/narration.js'

const PROJECT = process.env.GOOGLE_CLOUD_PROJECT || 'project-46053a8a-6324-40f0-ba8'
const token = execFileSync('gcloud', ['auth', 'application-default', 'print-access-token']).toString().trim()
await mkdir('public/vo', { recursive: true })

const durations = JSON.parse(await readFile('src/vo.json', 'utf8').catch(() => '{}'))
const wanted = process.argv.slice(2)
const ALL = [...CUES, ...CUES_V5.filter((c) => !CUES.some((x) => x.id === c.id))]
for (const cue of (wanted.length ? ALL.filter((c) => wanted.includes(c.id)) : CUES)) {
  const res = await fetch('https://texttospeech.googleapis.com/v1/text:synthesize', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'x-goog-user-project': PROJECT, 'Content-Type': 'application/json' },
    body: JSON.stringify({ input: { text: cue.text }, voice: VOICE, audioConfig: { audioEncoding: 'MP3', sampleRateHertz: 24000 } }),
  })
  const body = await res.json()
  if (!res.ok) throw new Error(`${cue.id}: ${body.error?.message}`)
  const file = `public/vo/${cue.id}.mp3`
  await writeFile(file, Buffer.from(body.audioContent, 'base64'))
  const probe = execFileSync('npx', ['remotion', 'ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file]).toString()
  durations[cue.id] = Number(probe.trim().split('\n').pop())
  console.log(`${cue.id.padEnd(12)} ${durations[cue.id].toFixed(2)} s  ${cue.text.split(/\s+/).length} words`)
}
await writeFile('src/vo.json', JSON.stringify(durations, null, 1))
