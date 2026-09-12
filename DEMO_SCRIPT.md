# Sahara challenge demo script

Target duration: 2–3 minutes. Use only built-in judge-mode samples or audio
for which consent and de-identification have been documented.

## 0:00–0:20 — Problem and users

Say: “AfriHealth AI helps community health workers and clinicians document
code-switched consultations in English, Amharic, and Afaan Oromoo. It supports
triage and documentation; it does not replace clinical judgment.”

Show the three care modules and the target frontline workflow.

## 0:20–1:05 — Frontline triage

Open Module 1 and select a built-in sample such as
`GOLD-ETH-001: Pediatric High Fever`. Use “Pre-load Audio Judge Mode” so the
demo is deterministic and does not expose a patient recording.

Show the transcript, extracted medical entities, triage classification, and
referral recommendation. State that the clinician must verify every result
against the source audio and patient context.

## 1:05–1:35 — Clinical intake and follow-up

Open Module 2 to show the structured clinical/EHR intake fields, then Module 3
to show the post-care voice workflow. Explain which steps are suggestions and
which require clinician or staff confirmation.

## 1:35–2:10 — Benchmark

Open the benchmark matrix. Explain that the repository includes a reproducible
three-sample fixture comparing Intron Sahara v2.5, OpenAI Whisper Medium, and
Meta Wav2Vec2 XLS-R using WER, clinical-entity recall, and FAAS.

Say: “These are fixture results, not a population-wide claim. A final
submission should include the actual dataset version, sample count, model
versions, consent status, and per-sample evidence.”

## 2:10–2:35 — Safety and deployment

Show the Responsible AI note. Mention consent, de-identification,
human-in-the-loop review, and server-side API-key storage. Do not display or
type a real API key into the recording.

## Final spoken limitation

“This prototype is a clinical documentation and decision-support aid. It must
not be used as an autonomous diagnostic or prescribing system.”
