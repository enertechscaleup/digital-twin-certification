// Final master: two-pass EBU R128 loudness normalisation of the rendered video's audio to
// -14 LUFS integrated, -1.5 dBTP true peak (the usual online-video target). Video is copied.
// Usage: node capture/master.mjs out/in.mp4 out/master.mp4
import { spawnSync } from 'node:child_process'
import ffmpeg from 'ffmpeg-static'

const [input, output] = process.argv.slice(2)
const target = 'I=-14:TP=-1.5:LRA=11'
const report = (args) => {
  const r = spawnSync(ffmpeg, ['-hide_banner', ...args], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  if (r.status !== 0) throw new Error(r.stderr.slice(-800))
  return JSON.parse(r.stderr.slice(r.stderr.lastIndexOf('{'), r.stderr.lastIndexOf('}') + 1))
}
const m = report(['-i', input, '-vn', '-af', `loudnorm=${target}:print_format=json`, '-f', 'null', '-'])
console.log(`measured: ${m.input_i} LUFS, ${m.input_tp} dBTP, LRA ${m.input_lra}`)
const filter = `loudnorm=${target}:measured_I=${m.input_i}:measured_TP=${m.input_tp}:measured_LRA=${m.input_lra}:measured_thresh=${m.input_thresh}:offset=${m.target_offset}:linear=true:print_format=json`
const r = report(['-y', '-i', input, '-c:v', 'copy', '-af', filter, '-ar', '48000', '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart', output])
console.log(`output:   ${r.output_i} LUFS, ${r.output_tp} dBTP (${r.normalization_type})`)
