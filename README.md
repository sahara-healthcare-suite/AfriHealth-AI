# sahara-healthcare-suite

AfriHealth AI is a browser-based clinical voice workflow for community health
workers and clinicians working with English, Amharic-English, and
Afaan Oromoo-English speech. It combines frontline voice triage, voice-assisted
clinical/EHR intake, post-care voice follow-up, and a three-model speech
benchmark view.

The application is a clinical documentation and decision-support aid. It does
not replace a clinician or make autonomous diagnoses.

Medication outputs are safety-gated: the API returns no medication suggestion
until the caller supplies explicit clinician confirmation in patient context.
Possible viral presentations and penicillin-family allergy conflicts remain
blocked and are returned as review alerts.

## Run locally

### Browser demo

```powershell
npm install
npm start
```

Open the URL printed by `serve` (normally `http://localhost:3000`).

For live microphone streaming, run the FastAPI service separately:

```powershell
python -m pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The browser connects to `ws://localhost:8000/ws/stream` when served on another
local port. For a deployed API, set `window.SAHARA_API_ORIGIN` before the main
script loads to the HTTPS API origin.

The documented Intron streaming TTS protocol is proxied at
`ws://localhost:8000/ws/tts`. Pass the Intron TTS query parameters
(`voice_accent`, `voice_gender`, `voice_language`, and optionally
`output_audio_format`) through this route. The proxy forwards the documented
`INPUT_TEXT_CHUNK`, `FETCH_AUDIO_CHUNK`, and `COMMIT` messages and returns the
Intron session responses, including base64 audio payloads.

The documented synchronous bridges are also available:

- `POST /api/intron/tts/generate` for text up to 4096 characters;
- `GET /api/intron/tts/status/{text_id}` for timed-out TTS jobs;
- `POST /api/intron/stt/upload-sync` for audio files up to Intron's 120-second
  synchronous limit.

These routes keep `INTRON_API_KEY` on the FastAPI server and forward only the
documented request fields. Configure the key locally with
`$env:INTRON_API_KEY = "your-key"`; never place it in frontend source.

The Voice Triage recording control saves reviewed microphone audio as a local
WAV recording before upload. WAV playback is used for browser compatibility,
and the file is sent to the synchronous STT bridge only after the user presses
the upload button. Select either Amharic-English or Oromo-English code-switch
before uploading; the corresponding Intron language code is sent with the
request.

For the approved 15-case clinical package, validate the canonical recording
selection without uploading:

```powershell
python clinical_validation_upload.py
```

After confirming the selected files, upload them through the running local
FastAPI bridge:

```powershell
python clinical_validation_upload.py --upload
```

This uses one Amharic-English recording per case, keeps the reference
transcript and target terms in the results, and sends `am` as the Intron
language code. It intentionally excludes extra duplicate files.

The privacy-safe aggregate results for the reviewed 15-case recording set are
in [clinical_validation_report.json](clinical_validation_report.json). Raw
audio, provider response IDs, and full transcripts remain outside the
repository.

### Intron proxy

The optional Node proxy keeps `INTRON_API_KEY` on the server:

```powershell
$env:INTRON_API_KEY = "your-key"
node server.js
```

Do not commit API keys or place them in client-side source. Production
deployments should use the server proxy and an allowlisted origin.

### Python service

Install the service dependencies from [requirements.txt](./requirements.txt)
before running the FastAPI application:

```powershell
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

## Benchmark reproducibility

The benchmark inputs and scoring implementation are in
[benchmark_suite.py](./benchmark_suite.py). Run it with:

```powershell
python benchmark_suite.py
```

The generated outputs are [benchmark_report.json](./benchmark_report.json) and
[BENCHMARK_RESULTS.md](./BENCHMARK_RESULTS.md). The current fixture contains
three labelled samples and embedded hypotheses; it is a reproducible
demonstration benchmark, not a claim of production-wide model performance.
See [SUBMISSION_READINESS.md](./SUBMISSION_READINESS.md) for the evidence and
remaining submission tasks.

To validate the imported AfriSwitch pilot and produce a reference-only
coverage report, run:

```powershell
python benchmark_suite.py --afriswitch-pilot
```

This reports utterance counts, durations, switch points, and missing audio.
It does not report WER or model rankings until actual model hypotheses are
generated for the imported audio.

To run real ASR inference with three multilingual Whisper checkpoints, install
the ASR dependencies and start with the bounded smoke test:

```powershell
python -m pip install -r requirements.txt
python afriswitch_asr_benchmark.py --limit-per-config 2
```

The script defaults to `whisper-tiny`, `whisper-base`, and `whisper-small`,
records the exact checkpoints, and writes predictions and WER metrics to
`clinical_validation/afriswitch/asr_results.json`. Increase
`--limit-per-config` only after the smoke test completes; model downloads and
CPU inference can be substantial.

## AfriSwitch pilot import

AfriSwitch is a gated Hugging Face dataset. Its full release is
approximately 23.5 GB, contains 54.41 hours and 16,602 utterances, and is
licensed CC BY-NC-SA 4.0. The import is optional and should be kept separate
from the clinical-team validation set.

The recommended first step is the bounded Amharic and Oromo pilot. After
requesting dataset access on Hugging Face, set the token only in your local
shell and run:

```powershell
$env:HF_TOKEN = "hf_your_token"
python -m pip install -r requirements.txt
python afriswitch_import.py --output .\clinical_validation\afriswitch
```

The default pilot imports only the `amharic` and `oromo` configurations. To
request a specific pilot, use `--configs amharic` or
`--configs amharic oromo`. The importer writes audio, per-language CSV
manifests, and `import_metadata.json`. Never commit the token, raw audio, or
private consent records. Do not describe AfriSwitch results as clinical
validation; it is a general code-switched speech benchmark.

The full import is deliberately opt-in:

```powershell
python afriswitch_import.py --all-configs --output .\clinical_validation\afriswitch
```

## Safety and data handling

See [RESPONSIBLE_AI.md](./RESPONSIBLE_AI.md) for the human-review, consent,
privacy, and inclusion requirements that apply before clinical deployment.

For the final handoff, see [ARCHITECTURE.md](./ARCHITECTURE.md) and
[FINAL_SUBMISSION_GUIDE.md](./FINAL_SUBMISSION_GUIDE.md). The repository does
not include a demo video; [DEMO_SCRIPT.md](./DEMO_SCRIPT.md) is provided for a
live demonstration or a separately hosted recording if required.
