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

## Safety and data handling

See [RESPONSIBLE_AI.md](./RESPONSIBLE_AI.md) for the human-review, consent,
privacy, and inclusion requirements that apply before clinical deployment.
