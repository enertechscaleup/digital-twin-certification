// Narration script (voice: Google Cloud TTS, en-GB-Chirp3-HD-Kore). Each cue is anchored to
// a moment in its section (seconds from the section's start); timing.js places the cues
// after synthesis so none overlaps the one before. Section 1 has no voiceover (brief).
// Beat 3 and Beat 4 ledger lines are the locked commercial-framing lines from the brief.

export const VOICE = { languageCode: 'en-GB', name: 'en-GB-Chirp3-HD-Kore' }

export const CUES = [
  // Section 2 — Find. Test. Combine.
  { id: 's2_intro', section: 2, anchor: 1.0, text: 'TwinEvidence starts from a library of digital twins, each built and owned by its vendor.' },
  { id: 's2_find', section: 2, anchor: 3.3, text: 'Find the twins a system needs.' },
  { id: 's2_test', section: 2, anchor: 10.2, text: "Test them together, under an assurance layer that belongs to the system owner, and never sits inside any vendor's engine." },
  { id: 's2_combine', section: 2, anchor: 18.8, text: 'Combine them, and compare candidate configurations before committing to a build.' },

  // Section 3 — The real platform (anchors are the shot starts).
  { id: 's3_projects', section: 3, shot: 's1_1', text: 'This is the platform we built. Two projects, configured rather than custom-coded: an oil and gas compressor train with verified evidence, and a robotics cell still in preview.' },
  { id: 's3_oilgas', section: 3, shot: 's2_1', text: "Each channel compares what the asset measured with what its twin predicted, at the same instant. Here the motor's gap grows until its assurance is nullified, and the system twin reflects it immediately." },
  { id: 's3_amr', section: 3, shot: 's2_2', text: 'The same screens run the robotics cell: four twins, seventeen channels and a central dispatcher, set up from configuration. Its data is mock for now, and the platform says so.' },
  // Beat 3 (locked), across shots 3.1 and 3.2.
  { id: 's3_beat3', section: 3, shot: 's3_1', text: "This is drift. It could be sensor wear, physical degradation, or the model itself losing fidelity. TwinEvidence doesn't need to know which, not yet. What it does is independently detect the divergence the moment it happens, flag it, and keep that record even if the reading later recovers. That's evidence an insurer or an operator can't get today." },
  // Beat 4 (locked, trimmed), across shots 4.2 (ledger and integrity) then 4.1 (composition).
  { id: 's3_beat4', section: 3, shot: 's4_2', text: "Every state change is sealed in a tamper-evident ledger: evidence a liability dispute could be settled with, or an insurer could underwrite against. Because it's kept twin by twin, you can see which vendor's twin diverged, and which didn't. Not an engineering diagnosis. An evidence trail, for whoever has to settle responsibility after." },

  // Section 4 — Close.
  { id: 's4_message', section: 4, anchor: 1.0, text: "TwinEvidence makes every twin provable and every combination testable, before commitment and throughout the asset's life. It bridges domain, data, engineering and construction, so large projects integrate on evidence, not assumption." },
  { id: 's4_proof', section: 4, anchor: 12.5, text: "What you've seen today is a first proof. At any scale." },
]
