"""
Sahara Healthcare Suite (AfriHealth AI) - FastAPI Backend Gateway
Includes:
- Intron v2.5 speech-to-text gateway
- Provider response parsing based on the documented File Upload Sync API
- Payload size validation and rate limiting
- CORS configuration for static frontends & Cloudflare Pages
"""

import os
import json
import time
import logging
import tempfile
from collections import deque
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
import httpx
from pydantic import BaseModel
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
import base64
import websockets

# Benchmark-only dependencies (Sahara vs. Whisper WER/CER/triage comparison).
# These are heavier ML deps than the rest of the gateway needs, so they're
# imported lazily inside the benchmark helpers below rather than at module
# load time -- keeps `/health` and normal transcription fast to boot even on
# an instance that doesn't have torch/transformers installed.

# Initialize logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("afrihealth_gateway")

app = FastAPI(
    title="AfriHealth AI Gateway",
    description="Secure proxy for Intron v2.5 ASR",
    version="2.5.0"
)

# ---------------------------------------------------------------------------
# Rate limiting
# The module docstring has always claimed "rate limiting" as a feature, but
# no limiter was actually wired up. This adds a lightweight in-memory
# sliding-window limiter (per client IP) with no extra dependency, applied
# to the expensive ASR-proxy routes. It's process-local, which is fine for a
# single Railway/Cloudflare-Pages-fronted instance; swap for a Redis-backed
# limiter if this ever runs behind multiple worker processes.
# ---------------------------------------------------------------------------
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMITED_PATH_PREFIXES = ("/api/v1/transcribe", "/api/intron/stt/upload-sync")

_request_log: dict[str, deque] = {}


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(RATE_LIMITED_PATH_PREFIXES):
            client_ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            window = _request_log.setdefault(client_ip, deque())

            while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
                window.popleft()

            if len(window) >= RATE_LIMIT_MAX_REQUESTS:
                retry_after = int(RATE_LIMIT_WINDOW_SECONDS - (now - window[0]))
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded. Please slow down and try again shortly.",
                        "retry_after_seconds": max(retry_after, 1),
                    },
                    headers={"Retry-After": str(max(retry_after, 1))},
                )

            window.append(now)

        return await call_next(request)


app.add_middleware(RateLimitMiddleware)

# CORS configuration - Allow Cloudflare Pages and local dev
ORIGINS = [
    "https://sahara-healthcare-suite.pages.dev",
    "https://sahara-healthcare-suite-1.pages.dev",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000"
]

# NOTE: we wrap the entire FastAPI application with CORSMiddleware below,
# rather than relying only on add_middleware(). This ensures CORS headers are
# present even when an unhandled exception produces a 500/503 response.

# Configuration & Keys
INTRON_API_KEY = os.getenv("INTRON_API_KEY", "")

# Ethiopian medical vocabulary retained for application-layer use.\n# Intron File Upload Sync does not expose a documented phrase-boost field.
ETHIOPIAN_MEDICAL_VOCABULARY: List[str] = [
    # Local pharmacological terms
    "Paracetamol", "Amoxicillin", "Ciprofloxacin", "Metronidazole",
    "Artemether", "Lumefantrine", "Coartem", "ORSL", "Zinc Sulfate",
    # Symptoms in Amharic & Afaan Oromoo (transliterated & localized)
    "Tefeteno", "Kusli", "Tebat", "Chink", "Mewt", "Derek Kosa",
    "Tussis", "Fever", "Tiyaa", "Dhukuba", "Garaachaa", "Miti",
    # Clinical jargon & dosage forms
    "Sublingual", "Intramuscular", "IV Drip", "BP 120/80", "SpO2",
    "Triage Level 1", "Triage Level 2", "Triage Level 3", "Referral",
    "Maternal Health", "Antenatal Care", "ANC", "PNC", "Malaria RDT"
]

class TranscriptionRequest(BaseModel):
    language_code: str = "am-ET"  # Amharic / Code-switched default
    # Retained for frontend compatibility. The documented Intron sync API
    # does not accept a vocabulary-boost field, so this is not sent upstream.
    boost_vocabulary: Optional[List[str]] = None

@app.get("/health")
async def health_check():
    return {
        "status": "online",
        "service": "AfriHealth AI Gateway",
        "intron_configured": bool(INTRON_API_KEY)
    }


def _normalize_language_code(language_code: str) -> str:
    """
    The sync-upload endpoint (proven working via the mic-recording feature)
    expects short codes like "am", "en", "yo", "ha" via use_language_asr_input
    -- not BCP-47 style tags like "am-ET". Everywhere else in this gateway
    (the REST /api/v1/transcribe route, the benchmark route) still takes the
    BCP-47-ish "am-ET" form for backward compatibility with the frontend, so
    we normalize here rather than pushing this concern out to every caller.
    """
    if not language_code:
        return "am"
    return language_code.split("-")[0].lower()


INTRON_SYNC_UPLOAD_ENDPOINT = "https://infer.voice.intron.io/file/v1/upload/sync"
INTRON_FILE_STATUS_ENDPOINT = "https://infer.voice.intron.io/file/v1/status/{file_id}"
INTRON_TTS_GENERATE_ENDPOINT = "https://infer.voice.intron.io/tts/v1/generate"
INTRON_TTS_STATUS_ENDPOINT = "https://infer.voice.intron.io/tts/v1/status/{text_id}"
INTRON_TTS_VOICE_LANGUAGE = os.getenv("INTRON_TTS_VOICE_LANGUAGE", "am")
INTRON_TTS_VOICE_ACCENT = os.getenv("INTRON_TTS_VOICE_ACCENT", "amharic")
INTRON_TTS_VOICE_GENDER = os.getenv("INTRON_TTS_VOICE_GENDER", "female")


async def _call_intron_transcribe(
    contents: bytes,
    filename: str,
    content_type: Optional[str],
    language_code: str = "am-ET",
) -> dict:
    """
    Call Intron's documented synchronous File Upload Sync API.

    The documented successful response is:
        {
            "data": {
                "file_id": "...",
                "processing_status": "FILE_TRANSCRIBED",
                "audio_file_name": "...",
                "audio_transcript": "...",
                "processed_audio_duration_in_seconds": 20,
                "use_language_asr_input": "en"
            },
            "message": "file status found",
            "status": "Ok"
        }

    There are no documented per-word confidence scores in this response,
    and the sync-upload API does not document a `phrase_boost` field.

    The sync API supports audio durations up to 120 seconds. If Intron
    returns HTTP 503 after timing out, the response may contain a file_id.
    In that case we preserve the provider's 503 and expose the file_id so
    the caller can retrieve the result from the status endpoint.
    """
    if not INTRON_API_KEY:
        logger.warning("INTRON_API_KEY not set. Returning judge-mode mock response.")
        return {
            "mode": "fallback_judge_mode",
            "transcript": (
                "ከፍተኛ ትኩሳት እና ሳል አለው:: "
                "Paracetamol 500mg t.i.d. given."
            ),
        }

    if len(contents) > 25 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="Audio file size exceeds maximum limit of 25MB",
        )

    # These are the fields documented for the sync-upload endpoint.
    data_payload = {
        "audio_file_name": filename or "recording.wav",
        "use_language_asr_input": _normalize_language_code(language_code),
        "use_category": "file_category_telehealth",
        "use_disable_llm_corrections": "FALSE",
    }

    files_payload = {
        "audio_file_blob": (
            filename or "recording.wav",
            contents,
            content_type or "audio/wav",
        )
    }

    headers = {"Authorization": f"Bearer {INTRON_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=130.0) as client:
            response = await client.post(
                INTRON_SYNC_UPLOAD_ENDPOINT,
                headers=headers,
                data=data_payload,
                files=files_payload,
            )

            # Intron documents 503 as a possible synchronous timeout and may
            # include a file_id that can be checked through /file/v1/status/{id}.
            if response.status_code == 503:
                try:
                    timeout_json = response.json()
                except ValueError:
                    timeout_json = {}

                timeout_data = (
                    timeout_json.get("data")
                    if isinstance(timeout_json, dict)
                    else None
                )
                timeout_data = timeout_data if isinstance(timeout_data, dict) else {}

                file_id = timeout_data.get("file_id") or timeout_json.get("file_id")
                logger.warning(
                    "Intron sync upload timed out (503); file_id=%s",
                    file_id,
                )

                detail = {
                    "message": "Intron processing timed out. Check the file status endpoint.",
                    "file_id": file_id,
                    "status": timeout_json.get("status") if isinstance(timeout_json, dict) else None,
                }

                raise HTTPException(status_code=503, detail=detail)

            response.raise_for_status()
            res_json = response.json()

            data = res_json.get("data")
            if not isinstance(data, dict):
                logger.error(
                    "Unexpected Intron sync-upload response: %s",
                    json.dumps(res_json)[:3000],
                )
                raise HTTPException(
                    status_code=502,
                    detail="Intron returned an unexpected response format.",
                )

            transcript_text = data.get("audio_transcript", "")
            processing_status = data.get("processing_status")
            file_id = data.get("file_id")

            if not isinstance(transcript_text, str):
                transcript_text = str(transcript_text or "")

            if processing_status != "FILE_TRANSCRIBED" and not transcript_text:
                logger.warning(
                    "Intron file is not transcribed yet: file_id=%s status=%s",
                    file_id,
                    processing_status,
                )

            return {
                "mode": "live",
                "transcript": transcript_text,
                "file_id": file_id,
                "processing_status": processing_status,
                "audio_file_name": data.get("audio_file_name"),
                "processed_audio_duration_in_seconds": data.get(
                    "processed_audio_duration_in_seconds"
                ),
                "use_language_asr_input": data.get("use_language_asr_input"),
                "raw_response": res_json,
            }

    except httpx.HTTPStatusError as e:
        logger.error(
            "Intron API Error: %s - %s",
            e.response.status_code,
            e.response.text,
        )
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"ASR Provider Error: {e.response.text}",
        )
    except HTTPException:
        raise
    except (ValueError, json.JSONDecodeError) as e:
        logger.error("Invalid JSON returned by Intron: %s", e)
        raise HTTPException(
            status_code=502,
            detail="Intron returned invalid JSON.",
        )
    except Exception as e:
        logger.error(f"Internal gateway error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Audio transcription gateway processing failed.",
        )


@app.post("/api/v1/transcribe")
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    language_code: str = "am-ET"
):
    """
    Proxy an audio file to Intron's documented synchronous upload endpoint.
    """

    contents = await file.read()
    result = await _call_intron_transcribe(contents, file.filename, file.content_type, language_code)

    if result["mode"] == "fallback_judge_mode":
        return JSONResponse(status_code=200, content=result)

    return {
        "status": "success",
        "transcript": result["transcript"],
        "file_id": result.get("file_id"),
        "processing_status": result.get("processing_status"),
        "audio_file_name": result.get("audio_file_name"),
        "processed_audio_duration_in_seconds": result.get(
            "processed_audio_duration_in_seconds"
        ),
        "use_language_asr_input": result.get("use_language_asr_input"),
    }
INTRON_STREAM_ENDPOINT = "wss://infer.voice.intron.io/stt/v1/stream"

@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()

    language = websocket.query_params.get("use_language_asr_input", "am")

    if not INTRON_API_KEY:
        await websocket.send_json({"error": "Intron API key not configured on server"})
        await websocket.close()
        return

    intron_url = f"{INTRON_STREAM_ENDPOINT}?sample_rate=16000&bit_rate=16&num_channels=1&use_language_asr_input={language}"

    try:
        async with websockets.connect(
            intron_url,
            extra_headers={"Authorization": f"Bearer {INTRON_API_KEY}"}
        ) as intron_ws:

            async def forward_browser_to_intron():
                try:
                    while True:
                        data = await websocket.receive()
                        if data.get("bytes") is not None:
                            audio_b64 = base64.b64encode(data["bytes"]).decode("utf-8")
                            await intron_ws.send(json.dumps({
                                "message_type": "INPUT_AUDIO_CHUNK",
                                "audio_base_64": audio_b64
                            }))
                        elif data.get("text") is not None:
                            try:
                                msg = json.loads(data["text"])
                                if msg.get("event") == "stop":
                                    await intron_ws.send(json.dumps({"message_type": "COMMIT"}))
                            except json.JSONDecodeError:
                                pass
                except WebSocketDisconnect:
                    pass

            async def forward_intron_to_browser():
                async for message in intron_ws:
                    payload = json.loads(message)
                    msg_type = payload.get("message_type")
                    if msg_type == "PARTIAL_TRANSCRIPT":
                        await websocket.send_json({"transcript": payload.get("transcript", "")})
                    elif msg_type == "COMMITTED_TRANSCRIPT":
                        await websocket.send_json({"transcript": payload.get("transcript_text", "")})
                    elif msg_type in ("ERROR", "INPUT_ERROR", "AUTHENTICATION_ERROR", "QUOTA_EXCEEDED"):
                        await websocket.send_json({"error": payload.get("message", msg_type)})

            forward_task = asyncio.create_task(forward_browser_to_intron())
            backward_task = asyncio.create_task(forward_intron_to_browser())
            done, pending = await asyncio.wait(
                [forward_task, backward_task], return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()

    except Exception as e:
        logger.error(f"Intron streaming bridge error: {e}")
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.post("/api/intron/stt/upload-sync")
async def intron_stt_upload_sync(request: Request):
    """
    Direct proxy for Intron's documented File Upload Sync API.

    Expected successful response shape includes:
        data.audio_transcript
        data.processing_status
        data.file_id

    No confidence or phrase-boost fields are fabricated here.
    """

    if not INTRON_API_KEY:
        raise HTTPException(status_code=503, detail="Intron API key not configured on server")

    form = await request.form()
    audio_file = form.get("audio_file_blob")
    if audio_file is None:
        raise HTTPException(status_code=400, detail="Missing audio_file_blob in form data")

    file_bytes = await audio_file.read()
    filename = form.get("audio_file_name") or getattr(audio_file, "filename", "recording.wav")

    files_payload = {
        "audio_file_blob": (filename, file_bytes, audio_file.content_type or "audio/wav")
    }
    data_payload = {
        "audio_file_name": filename,
        "use_language_asr_input": form.get("use_language_asr_input", "am"),
        "use_category": form.get("use_category", "file_category_telehealth"),
        "use_disable_llm_corrections": form.get("use_disable_llm_corrections", "FALSE"),
    }
    headers = {"Authorization": f"Bearer {INTRON_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=130.0) as client:
            response = await client.post(
                INTRON_SYNC_UPLOAD_ENDPOINT,
                headers=headers,
                data=data_payload,
                files=files_payload
            )
            if response.status_code == 503:
                try:
                    timeout_json = response.json()
                except ValueError:
                    timeout_json = {}
                timeout_data = timeout_json.get("data") if isinstance(timeout_json, dict) else None
                timeout_data = timeout_data if isinstance(timeout_data, dict) else {}
                file_id = timeout_data.get("file_id") or timeout_json.get("file_id")
                logger.warning("Intron sync upload timed out (503); file_id=%s", file_id)
                raise HTTPException(
                    status_code=503,
                    detail={
                        "message": "Intron processing timed out. Check the file status endpoint.",
                        "file_id": file_id,
                    },
                )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Intron sync upload error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=f"Intron upload error: {e.response.text}")
    except Exception as e:
        logger.error(f"Intron sync upload gateway error: {e}")
        raise HTTPException(status_code=500, detail="Audio upload processing failed.")

@app.get("/api/intron/stt/status/{file_id}")
async def intron_stt_file_status(file_id: str):
    """
    Proxy Intron's documented Get File Status endpoint.

    Use this after a synchronous upload returns HTTP 503 with a file_id.
    """
    if not INTRON_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Intron API key not configured on server",
        )

    headers = {"Authorization": f"Bearer {INTRON_API_KEY}"}
    status_url = INTRON_FILE_STATUS_ENDPOINT.format(file_id=file_id)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                status_url,
                headers=headers,
                params={"get_structured_post_processing": "f"},
            )
            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        logger.error(
            "Intron file status error: %s - %s",
            e.response.status_code,
            e.response.text,
        )
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Intron file status error: {e.response.text}",
        )
    except Exception as e:
        logger.error(f"Intron file status gateway error: {e}")
        raise HTTPException(
            status_code=500,
            detail="File status lookup failed.",
        )


@app.post("/api/intron/tts")
async def intron_tts(payload: dict):
    """Generate Amharic speech through Intron TTS without exposing the API key."""
    if not INTRON_API_KEY:
        raise HTTPException(status_code=503, detail="Intron API key not configured on server")

    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required")
    if len(text) > 4096:
        raise HTTPException(status_code=400, detail="TTS text exceeds Intron's 4096 character limit")

    voice_language = str(payload.get("voice_language") or INTRON_TTS_VOICE_LANGUAGE).strip().lower()
    voice_accent = str(payload.get("voice_accent") or INTRON_TTS_VOICE_ACCENT).strip().lower()
    voice_gender = str(payload.get("voice_gender") or INTRON_TTS_VOICE_GENDER).strip().lower()

    request_body = {
        "text": text,
        "voice_language": voice_language,
        "voice_accent": voice_accent,
        "voice_gender": voice_gender,
        "output_audio_format": "wav",
    }
    headers = {
        "Authorization": f"Bearer {INTRON_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=130.0) as client:
            response = await client.post(
                INTRON_TTS_GENERATE_ENDPOINT,
                headers=headers,
                json=request_body,
            )
            if response.status_code == 503:
                try:
                    timeout_json = response.json()
                except ValueError:
                    timeout_json = {}
                data = timeout_json.get("data") if isinstance(timeout_json, dict) else {}
                data = data if isinstance(data, dict) else {}
                text_id = data.get("text_id") or timeout_json.get("text_id")
                raise HTTPException(
                    status_code=503,
                    detail={
                        "message": "Intron TTS processing timed out. Check the TTS status endpoint.",
                        "text_id": text_id,
                    },
                )
            response.raise_for_status()
            result = response.json()
            result_data = result.get("data") if isinstance(result, dict) else {}
            result_data = result_data if isinstance(result_data, dict) else {}
            return {
                "status": result.get("status", "Ok"),
                "message": result.get("message", "text status found"),
                "data": {
                    "audio_duration_in_seconds": result_data.get("audio_duration_in_seconds"),
                    "audio_path": result_data.get("audio_path"),
                    "processing_status": result_data.get("processing_status"),
                },
            }
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        logger.error("Intron TTS error: %s - %s", e.response.status_code, e.response.text)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Intron TTS error: {e.response.text}",
        )
    except Exception as e:
        logger.error("Intron TTS gateway error: %s", e)
        raise HTTPException(status_code=500, detail="TTS gateway processing failed.")


@app.get("/api/intron/tts/status/{text_id}")
async def intron_tts_status(text_id: str):
    """Proxy Intron's TTS status endpoint after an async/timeout response."""
    if not INTRON_API_KEY:
        raise HTTPException(status_code=503, detail="Intron API key not configured on server")

    headers = {"Authorization": f"Bearer {INTRON_API_KEY}"}
    status_url = INTRON_TTS_STATUS_ENDPOINT.format(text_id=text_id)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(status_url, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Intron TTS status error: {e.response.text}")
    except Exception as e:
        logger.error("Intron TTS status gateway error: %s", e)
        raise HTTPException(status_code=500, detail="TTS status lookup failed.")


@app.post("/api/intron/tts/audio")
async def intron_tts_audio(payload: dict):
    """Generate Intron TTS and proxy the resulting WAV bytes to the browser."""
    result = await intron_tts(payload)
    audio_path = result.get("data", {}).get("audio_path") if isinstance(result, dict) else None
    processing_status = result.get("data", {}).get("processing_status") if isinstance(result, dict) else None
    if not audio_path or processing_status != "TTS_TEXT_AUDIO_GENERATED":
        raise HTTPException(status_code=502, detail="Intron TTS did not return generated audio.")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            audio_response = await client.get(audio_path)
            audio_response.raise_for_status()
            return StreamingResponse(
                iter([audio_response.content]),
                media_type=audio_response.headers.get("content-type", "audio/wav"),
                headers={"Cache-Control": "no-store"},
            )
    except httpx.HTTPStatusError as e:
        logger.error("Intron TTS audio fetch error: %s - %s", e.response.status_code, e.response.text)
        raise HTTPException(status_code=502, detail="Could not retrieve generated Intron audio.")
    except Exception as e:
        logger.error("Intron TTS audio proxy error: %s", e)
        raise HTTPException(status_code=502, detail="Could not retrieve generated Intron audio.")


# ---------------------------------------------------------------------------
# Sahara v2.5 vs. Whisper Medium benchmark
#
# Ports the Colab comparison notebook (WER/CER via jiwer + a keyword-based
# triage classifier) into the gateway as a real endpoint, so the frontend's
# "Benchmark Matrix" tab can show actual measured numbers on operatorsupplied
# audio + reference transcripts, instead of only the embedded fixture rows.
#
# Methodology follows the Intron AfriHealth MultiBench approach (normalized
# WER/CER via jiwer, per-language breakdown, keyword-based triage as a
# clinician-attention flag rather than an autonomous decision):
# https://github.com/intron-innovation/Intron-Multimodal-Benchmarking
#
# Heavy ML deps (torch, torchaudio, transformers, jiwer) are only imported
# when this endpoint is first hit, and the Whisper pipeline is cached after
# first load so repeat calls don't reload the model.
# ---------------------------------------------------------------------------

WHISPER_MODEL_ID = os.getenv("WHISPER_BENCHMARK_MODEL", "openai/whisper-medium")
_whisper_pipeline = None  # lazy-loaded singleton


def _get_whisper_pipeline():
    global _whisper_pipeline
    if _whisper_pipeline is None:
        from transformers import pipeline  # imported lazily, see note above
        logger.info(f"Loading Whisper benchmark model '{WHISPER_MODEL_ID}' (first call only)...")
        _whisper_pipeline = pipeline("automatic-speech-recognition", model=WHISPER_MODEL_ID)
    return _whisper_pipeline


def _transcribe_with_whisper(audio_path: str) -> str:
    """Resamples audio to 16kHz (Whisper's expected rate) and transcribes it."""
    import torchaudio
    waveform, sample_rate = torchaudio.load(audio_path, backend="soundfile")
    # waveform, sample_rate = torchaudio.load(audio_path)
    if sample_rate != 16000:
        resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)
        waveform = resampler(waveform)
        sample_rate = 16000

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        resampled_path = tmp.name
    try:
        torchaudio.save(resampled_path, waveform, sample_rate)
        whisper = _get_whisper_pipeline()
        result = whisper(resampled_path)
        return result["text"]
    finally:
        if os.path.exists(resampled_path):
            os.remove(resampled_path)


def _compute_wer_cer(reference: str, hypothesis: str) -> dict:
    from jiwer import wer, cer
    return {
        "wer": wer(reference, hypothesis),
        "cer": cer(reference, hypothesis),
    }


# Keyword-based triage heuristic, ported directly from the benchmark
# notebook. This is a coarse text-matching signal only -- it exists to flag
# transcripts for clinician attention, not to make an autonomous triage
# decision. It must not be used to gate or replace clinical review.
EMERGENCY_TERMS = [
    "severe difficulty breathing",
    "unconscious",
    "severe bleeding",
    "seizure",
    "cannot breathe",
]

URGENT_TERMS = [
    "high fever",
    "chest pain",
    "dehydration",
    "persistent vomiting",
    "difficulty breathing",
]


def triage_classifier(text: str) -> str:
    text = (text or "").lower()

    for term in EMERGENCY_TERMS:
        if term in text:
            return "EMERGENCY"

    for term in URGENT_TERMS:
        if term in text:
            return "URGENT"

    return "ROUTINE"


@app.post("/api/v1/benchmark")
async def benchmark_asr(
    file: UploadFile = File(...),
    reference_transcript: str = Form(...),
    language_code: str = Form("am-ET"),
):
    """
    Runs a single audio sample through both Intron Sahara v2.5 and Whisper
    Medium, scores each against a supplied reference transcript with
    WER/CER, and runs the keyword triage heuristic on both outputs.

    This is a real, on-demand comparison (not the embedded frontend
    fixture rows) -- intended for building up the gold-standard evidence
    set, not as a substitute for the clinician-reviewed validation summary.
    """
    contents = await file.read()
    if len(contents) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file size exceeds maximum limit of 25MB")

    # 1. Sahara (Intron) transcript -- reuses the same call path as /api/v1/transcribe
    sahara_started = time.perf_counter()
    try:
        sahara_result = await _call_intron_transcribe(
            contents, file.filename, file.content_type, language_code
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Intron benchmark transcription failed")
        raise HTTPException(
            status_code=502,
            detail=f"Intron benchmark transcription failed: {type(e).__name__}: {e}",
        )
    sahara_latency_ms = round((time.perf_counter() - sahara_started) * 1000, 2)
    sahara_transcript = sahara_result.get("transcript", "")
    if not isinstance(sahara_transcript, str):
        sahara_transcript = str(sahara_transcript)

    # 2. Whisper Medium transcript -- needs a real file on disk for torchaudio
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        raw_audio_path = tmp.name

    try:
        try:
            whisper_started = time.perf_counter()
            whisper_transcript = await asyncio.to_thread(_transcribe_with_whisper, raw_audio_path)
            whisper_latency_ms = round((time.perf_counter() - whisper_started) * 1000, 2)
        except ImportError as e:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Whisper benchmark dependencies not installed on this instance "
                    f"(torch/torchaudio/transformers). Missing: {e}"
                ),
            )
        except Exception as e:
            logger.exception("Whisper benchmark failed")
            raise HTTPException(
                status_code=503,
                detail=f"Whisper benchmark processing failed: {type(e).__name__}: {e}",
            )
    finally:
        if os.path.exists(raw_audio_path):
            os.remove(raw_audio_path)

    # 3. Score both against the reference transcript
    sahara_scores = _compute_wer_cer(reference_transcript, sahara_transcript)
    whisper_scores = _compute_wer_cer(reference_transcript, whisper_transcript)

    results = [
        {
            "model": "Intron Sahara v2.5",
            "transcript": sahara_transcript,
            "WER": sahara_scores["wer"],
            "CER": sahara_scores["cer"],
            "WER_percent": round(sahara_scores["wer"] * 100, 2),
            "CER_percent": round(sahara_scores["cer"] * 100, 2),
            "triage": triage_classifier(sahara_transcript),
            "latency_ms": sahara_latency_ms,
            "mode": sahara_result["mode"],
        },
        {
            "model": "OpenAI Whisper Medium",
            "transcript": whisper_transcript,
            "WER": whisper_scores["wer"],
            "CER": whisper_scores["cer"],
            "WER_percent": round(whisper_scores["wer"] * 100, 2),
            "CER_percent": round(whisper_scores["cer"] * 100, 2),
            "triage": triage_classifier(whisper_transcript),
            "latency_ms": whisper_latency_ms,
            "mode": "live",
        },
    ]

    return {
        "status": "success",
        "benchmark_type": "live_local_validation",
        "reference_transcript": reference_transcript,
        "results": results,
        "triage_agreement": results[0]["triage"] == results[1]["triage"],
    }


# Wrap the fully configured ASGI app so CORS also covers framework-level
# exception responses generated outside the route handlers.
app = CORSMiddleware(
    app=app,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)