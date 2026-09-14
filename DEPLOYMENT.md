# AfriHealth AI deployment and operations

This prototype has two deployment surfaces:

1. a static browser frontend (`index.html`, JavaScript, and assets); and
2. a server-side API bridge (`main.py`) that keeps the Intron credential private
   and proxies speech requests.

The frontend may be hosted on Cloudflare Pages. The FastAPI service must run on
an HTTPS-capable host that supports WebSockets. Do not deploy the API key in
the static frontend.

## Recommended architecture

```text
Browser
  |
  | HTTPS / WSS
  v
Cloudflare Pages       Separate FastAPI service
static frontend  --->  /health
                       /api/intron/stt/upload-sync
                       /api/intron/tts/*
                       /ws/stream
                       /ws/tts
                              |
                              v
                       Intron Voice API
```

The browser records audio locally, presents playback for review, and uploads
only after the user explicitly selects the upload action. The API service
receives the audio and uses `INTRON_API_KEY` server-side.

## Required environment variables

Configure these only on the API host:

```text
INTRON_API_KEY=...
ALLOWED_ORIGINS=https://your-project.pages.dev
```

Use a comma-separated list for multiple exact origins. Do not use `*` for
production CORS when credentials or protected clinical workflows are involved.
Do not commit `.env` files, API keys, patient recordings, full transcripts, or
provider response IDs.

## Run the API

Install the Python dependencies and start the service on an externally
reachable interface:

```powershell
python -m pip install -r requirements.txt
$env:INTRON_API_KEY = "your-key"
$env:ALLOWED_ORIGINS = "https://your-project.pages.dev"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Terminate TLS at the hosting platform or reverse proxy. The public API URL
must be HTTPS, and WebSocket clients must connect through `wss://`.

## Deploy the frontend to Cloudflare Pages

The repository is a static site. In Cloudflare Pages, connect the repository
and use:

- **Build command:** none
- **Build output directory:** `.`
- **Root directory:** repository root

If the deployment platform requires a command, use a no-op command such as
`echo "static site"` rather than running a development server. Do not upload
the private `clinical_validation/` directory or any local audio artifacts.

Set the API origin in the deployed page before the application script loads:

```html
<script>
  window.SAHARA_API_ORIGIN = "https://api.example.org";
</script>
```

For a production deployment, this value should be injected during the
deployment process rather than edited manually for each environment.

## Post-deployment checks

1. Open `https://your-project.pages.dev/` and confirm the page loads.
2. Request `https://api.example.org/health` and confirm the service is online.
3. Confirm the API reports the expected Intron connection state.
4. Test one consented, de-identified recording:
   local playback -> explicit upload -> transcript -> clinician review.
5. Confirm browser developer tools show no API key in source, storage, or
   request bodies.
6. Confirm REST requests use HTTPS and WebSocket requests use WSS.
7. Confirm a request from an unapproved origin is rejected by CORS.
8. Review hosting logs and retention settings before handling real patient
   information.

## Operational boundaries

This prototype is a clinician-reviewed documentation and decision-support aid.
Generated transcripts, entities, triage labels, coding suggestions, SOAP notes,
and medication suggestions require qualified human review. Clinical validation
materials are private evaluation and governance artifacts, not a public
approval claim. Use only consented, de-identified data for demonstrations and
evaluation.
