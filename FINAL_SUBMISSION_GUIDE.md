# Sahara Challenge Final Submission Guide

## Submission statement

AfriHealth AI is a clinician-reviewed voice documentation and decision-support
prototype for code-switched English, Amharic, and Afaan Oromoo workflows. It
helps frontline workers capture speech, review a transcript, structure a
clinical intake, and prepare follow-up documentation. It does not diagnose,
prescribe, or replace clinical judgment.

## What is included

- Working browser prototype: `index.html`
- FastAPI integration and safety gate: `main.py`
- Optional static/proxy server: `server.js`
- Setup and endpoint instructions: `README.md`
- Architecture and data-flow description: `ARCHITECTURE.md`
- Responsible AI and inclusion controls: `RESPONSIBLE_AI.md`
- Reproducible fixture benchmark: `benchmark_suite.py`
- AfriSwitch import and real-inference tooling:
  `afriswitch_import.py` and `afriswitch_asr_benchmark.py`
- Reviewed 15-case simulated clinical benchmark report:
  `clinical_validation_report.json`
- Recording protocol, metadata template, and team handoff checklist

## Evidence interpretation

Use the evidence labels below in the submission:

1. **Prototype evidence:** browser workflows and built-in judge-mode samples.
2. **Fixture benchmark evidence:** reproducible demonstration scores from the
   labelled fixture. These are not general performance claims.
3. **General ASR evidence:** bounded AfriSwitch pilot import/inference. This is
   not clinical validation.
4. **Simulated clinical benchmark evidence:** 15 reviewed Amharic-English
   recordings of simulated clinical scenarios, uploaded to Intron with a mean
   WER of `0.564` and mean target-term recall of `0.443`. These results are
   useful for model comparison, error analysis, and terminology improvement,
   but are not evidence from real patients and do not authorize autonomous
   care.

Do not present `benchmark_report.json`, `evaluation_report_summary.json`, and
the clinical report as one experiment. They use different datasets and
protocols.

## Run instructions for reviewers

### Frontend

```powershell
npm install
npm start
```

Open `http://localhost:3000`.

### FastAPI integration

```powershell
python -m pip install -r requirements.txt
$env:INTRON_API_KEY = "your-key"
python -m uvicorn main:app --reload --port 8000
```

Never put the real key in the frontend or commit it.

### Safe judge path without microphone

1. Open Module 1.
2. Select `GOLD-ETH-001`, `GOLD-ETH-002`, or `GOLD-ETH-003`.
3. Use **Pre-load Audio Judge Mode**.
4. Review the transcript, extracted entities, triage label, and recommendation.
5. Explain that the result is clinician-review output.

## Privacy and clinical review

The public repository intentionally excludes raw audio, complete provider
responses, and private transcripts. The reviewed recordings are simulated
clinical scenarios with no real patient identities. Detailed files remain in
the approved local validation package.

Before any real clinical deployment or real-patient evaluation, obtain:

- documented consent and de-identification;
- clinician review of the 15-case outputs;
- completed safety scenarios and Responsible AI sign-off;
- an approved retention and access-control policy;
- production CORS, authentication, monitoring, and incident-response
  configuration.

## Demo video

No demo video file or video link is included, by request. The project includes
[DEMO_SCRIPT.md](./DEMO_SCRIPT.md) so the owner can provide a live demonstration
or record an unlisted video separately if the submission portal requires one.

## Final checklist

- [x] Working prototype source included.
- [x] Local setup and API contracts documented.
- [x] Architecture and data-flow documentation included.
- [x] Responsible AI, privacy, and medication safety controls documented.
- [x] Benchmark limitations explicitly documented.
- [x] Clinical baseline aggregate report included without private audio.
- [x] No API key or raw clinical recordings committed.
- [ ] Add a demo URL only if the challenge portal makes it mandatory.
- [ ] Complete clinician sign-off and attach consent evidence privately if
      requested by the challenge organizers.
