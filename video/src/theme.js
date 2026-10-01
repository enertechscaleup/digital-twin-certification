// Video palette, from the platform's design tokens (web/src/platform/platform.css).
// Sections 1, 2 and 4 are dark and cinematic, matching twinevidence.com's hero.
// Status colours (assured, flagged, nullified) are reserved for Section 3's real
// platform footage and must not appear here.
import { loadFont as loadSerif } from '@remotion/google-fonts/DMSerifDisplay'
import { loadFont as loadSans } from '@remotion/google-fonts/Manrope'

export const serif = loadSerif('normal', { weights: ['400'], subsets: ['latin'] }).fontFamily
export const serifItalic = loadSerif('italic', { weights: ['400'], subsets: ['latin'] }).fontFamily
export const sans = loadSans('normal', { weights: ['500', '700', '800'], subsets: ['latin'] }).fontFamily

export const TOKENS = {
  night: '#152a37',
  nightDeep: '#101f2a',
  paper: '#f4f2eb',
  paperLight: '#fbfaf6',
  orange: '#e66b3c',
  orangeBright: '#f2814f',
}

// Scene colours on the dark background: assets in paper, their graphs in a quiet
// blue-grey, data flow in the brand orange.
export const SCENE_COLORS = { line: TOKENS.paper, graph: '#9fb2bc', flow: TOKENS.orangeBright, grid: '#26404f' }
