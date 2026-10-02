// Generates the swappable music bed with Google's Lyria model on Vertex AI (instrumental,
// ~33 s per clip, SynthID-watermarked), using Application Default Credentials.
// Fixed prompts and seeds, so the bed can be regenerated. Output: public/music/<id>.wav
// Usage: node capture/music.mjs [clip id ...]

import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'

const PROJECT = process.env.GOOGLE_CLOUD_PROJECT || 'project-46053a8a-6324-40f0-ba8'
const URL = `https://us-central1-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/us-central1/publishers/google/models/lyria-002:predict`
const NEG = 'vocals, singing, speech, heavy drums, distortion, aggressive, harsh'
const CINEMATIC = 'Slow cinematic ambient underscore for a technology documentary: warm evolving synth pads, soft low strings, gentle pulsing arpeggio, a sense of vast scale and quiet ambition, no drums, 70 bpm'
const CLEAN = 'Bright, confident minimal electronic music: soft piano chords, plucked synth arpeggio, light steady percussion, calm and optimistic, clean and uncluttered, 100 bpm'

export const CLIPS = [
  { id: 'a1', prompt: CINEMATIC, seed: 11 },
  { id: 'a2', prompt: `${CINEMATIC}, slowly building`, seed: 12 },
  { id: 'b1', prompt: CLEAN, seed: 21 },
  { id: 'b2', prompt: CLEAN, seed: 22 },
  { id: 'b3', prompt: CLEAN, seed: 23 },
  { id: 'b4', prompt: `${CLEAN}, gently resolving`, seed: 24 },
]

const token = execFileSync('gcloud', ['auth', 'application-default', 'print-access-token']).toString().trim()
await mkdir('public/music', { recursive: true })
const wanted = process.argv.slice(2)
for (const c of CLIPS.filter((x) => !wanted.length || wanted.includes(x.id))) {
  const res = await fetch(URL, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'x-goog-user-project': PROJECT, 'Content-Type': 'application/json' },
    body: JSON.stringify({ instances: [{ prompt: c.prompt, negative_prompt: NEG, seed: c.seed }], parameters: {} }),
  })
  const body = await res.json()
  if (!res.ok) throw new Error(`${c.id}: ${body.error?.message}`)
  const audio = body.predictions[0].bytesBase64Encoded
  await writeFile(`public/music/${c.id}.wav`, Buffer.from(audio, 'base64'))
  console.log(`${c.id}: ${(audio.length * 0.75 / 1e6).toFixed(1)} MB`)
}
