// Narration script v4 (manufacturing and Gen AI framing), built on v3 with the v3_wk text edits
// (voice: Google Cloud TTS, en-GB-Chirp3-HD-Kore).
// Each cue is anchored to a moment in its section (seconds from the section's start, or a
// Section 3 shot); Full.jsx places the cues after synthesis so none overlaps the one before.
// Beat 3 is the locked final wording from the v3 script.

export const VOICE = { languageCode: 'en-GB', name: 'en-GB-Chirp3-HD-Kore' }

export const CUES = [
  // Section 1 — Vision. The voice begins under the opening statement.
  { id: 's1_vision', section: 1, anchor: 0.4, text: "Manufacturing and industrial operations run on digital twins to predict machine behavior — but when a twin quietly drifts from the real equipment it's modeling, nobody can independently prove it, until a failure makes it obvious. That gap costs downtime, quality, and trust." },

  // Section 2 — Find. Test. Combine.
  { id: 's2_intro', section: 2, anchor: 0.3, text: 'Introducing TwinEvidence! An independent physical-AI assurance platform for the industrial world. It starts from a library of digital twins, each one owned and maintained by the vendor whose equipment it represents.' },
  { id: 's2_find', section: 2, anchor: 14.1, text: 'Find the twins a system needs.' },
  { id: 's2_test', section: 2, anchor: 16.1, text: 'Test each twin on its own vendor\'s engine, under a governance layer built on grounded generative AI — it can only reason from the platform\'s own verified data, never from free generation. Every twin is identified, versioned, and sealed in a tamper-evident ledger.' },
  { id: 's2_combine', section: 2, anchor: 31.7, text: 'Combine them, and compare candidate configurations before committing to a build.' },

  // Section 3 — The real platform (anchors are the shot starts).
  { id: 's3_projects', section: 3, shot: 'lib', text: 'This is the platform we built. Every twin in the library carries its own identity. Here are two projects built from it: an oil and gas compressor train, and a robotics cell.' },
  { id: 's3_oilgas', section: 3, shot: 's2_1', text: "Each channel compares what the asset measured with what its twin predicted, at the same instant. Here the motor's gap grows until its assurance is nullified, and the system twin reflects it immediately." },
  // Beat 3 (locked), across shots 3.1 and 3.2.
  { id: 's3_beat3', section: 3, shot: 's3_1', text: "This is drift. It could be sensor wear, physical degradation, or the model itself losing fidelity. TwinEvidence doesn't determine the cause of drift. What it does is independently detect the divergence the moment it happens, flag it to the twin owner, and keep that record even if the reading later recovers. That's evidence of performance an insurer or an operator can't get today." },
  { id: 's3_lineage', section: 3, shot: 'lin', text: "The vendor recalibrates the motor twin for wear. TwinEvidence doesn't just accept the fix. It registers a new version, linked to the one before it, and the old evidence stays exactly as it was." },
  { id: 's3_joint', section: 3, shot: 'joint', text: "Before the system trusts that new version, it has to prove it still works with everything around it. TwinEvidence runs the motor and the compressor together, through each vendor's own engine, and reports if any of them crosses the boundary. This time, the recalibrated motor's predicted speed falls outside the compressor's assured range. The system twin isn't re-assured with the owner in loop." },
  // The grounded assistant answers live, then the sealed Gemini explanation of the same event.
  { id: 's3_gemini', section: 3, shot: 'gem', text: 'When drift is flagged, Gemini — grounded only in this platform\'s own verified evidence, never guessing — turns the raw numbers into a plain-language explanation an operations engineer can act on immediately, without reading a data science report.' },
  // The ledger and integrity shots, then the close (Section 4).
  { id: 's3_close', section: 3, shot: 's4_2', text: 'Every state change is sealed in a tamper-evident ledger — evidence an insurer could underwrite against, or a reliability team could act on. The same engine runs any twin, from a single motor to a full production line: this is how manufacturing operations turn raw telemetry into trusted, GenAI-assisted decisions, at scale.' },
]
