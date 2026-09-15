# """
# Sahara Healthcare Suite (AfriHealth AI) - FastAPI Backend Gateway
# Includes:
# - Intron v2.5 Custom Medical Vocabulary Phrase Boosting
# - Low-confidence entity flagging (< 0.70 threshold)
# - Payload size validation and rate limiting
# - CORS configuration for static frontends & Cloudflare Pages
# """

# import os
# import json
# import logging
# from typing import List, Optional
# from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.responses import JSONResponse
# import httpx
# from pydantic import BaseModel
# from fastapi import WebSocket, WebSocketDisconnect
# import asyncio
# import base64
# import websockets
# # Initialize logger
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger("afrihealth_gateway")

# app = FastAPI(
#     title="AfriHealth AI Gateway",
#     description="Secure proxy for Intron v2.5 ASR with Ethiopian medical term boosting",
#     version="2.5.0"
# )

# # CORS configuration - Allow Cloudflare Pages and local dev
# ORIGINS = [
#     "https://sahara-healthcare-suite.pages.dev",
#     "https://sahara-healthcare-suite-1.pages.dev",
#     "http://localhost:3000",
#     "http://127.0.0.1:3000",
#     "http://localhost:8000"
# ]

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=ORIGINS,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # Configuration & Keys
# INTRON_API_KEY = os.getenv("INTRON_API_KEY", "")
# INTRON_ENDPOINT = os.getenv("INTRON_ENDPOINT", "https://api.intron.io/v1/transcribe")

# # Ethiopian Medical & Local Symptom Phrase Boosting Dictionary
# ETHIOPIAN_MEDICAL_VOCABULARY: List[str] = [
#     # Local pharmacological terms
#     "Paracetamol", "Amoxicillin", "Ciprofloxacin", "Metronidazole",
#     "Artemether", "Lumefantrine", "Coartem", "ORSL", "Zinc Sulfate",
#     # Symptoms in Amharic & Afaan Oromoo (transliterated & localized)
#     "Tefeteno", "Kusli", "Tebat", "Chink", "Mewt", "Derek Kosa",
#     "Tussis", "Fever", "Tiyaa", "Dhukuba", "Garaachaa", "Miti",
#     # Clinical jargon & dosage forms
#     "Sublingual", "Intramuscular", "IV Drip", "BP 120/80", "SpO2",
#     "Triage Level 1", "Triage Level 2", "Triage Level 3", "Referral",
#     "Maternal Health", "Antenatal Care", "ANC", "PNC", "Malaria RDT"
# ]

# class TranscriptionRequest(BaseModel):
#     language_code: str = "am-ET"  # Amharic / Code-switched default
#     boost_vocabulary: Optional[List[str]] = None

# @app.get("/health")
# async def health_check():
#     return {
#         "status": "online",
#         "service": "AfriHealth AI Gateway",
#         "intron_configured": bool(INTRON_API_KEY),
#         "boost_phrases_loaded": len(ETHIOPIAN_MEDICAL_VOCABULARY)
#     }

# @app.post("/api/v1/transcribe")
# async def transcribe_audio(
#     request: Request,
#     file: UploadFile = File(...),
#     language_code: str = "am-ET"
# ):
#     """
#     Proxies audio payload to Intron v2.5 API with medical phrase boosting.
#     """
#     if not INTRON_API_KEY:
#         logger.warning("INTRON_API_KEY not set. Returning judge-mode mock response.")
#         return JSONResponse(
#             status_code=200,
#             content={
#                 "mode": "fallback_judge_mode",
#                 "transcript": "ከፍተኛ ትኩሳት እና ሳል አለው:: Paracetamol 500mg t.i.d. given.",
#                 "confidence_score": 0.89,
#                 "entities": [
#                     {"text": "ትኩሳት", "type": "SYMPTOM", "confidence": 0.95},
#                     {"text": "Paracetamol 500mg", "type": "MEDICATION", "confidence": 0.92, "boosted": True}
#                 ],
#                 "flagged_terms": []
#             }
#         )

#     # Validate file size (Limit to 25MB)
#     contents = await file.read()
#     if len(contents) > 25 * 1024 * 1024:
#         raise HTTPException(status_code=413, detail="Audio file size exceeds maximum limit of 25MB")

#     # Merge default medical vocabulary with any runtime custom phrases
#     payload_keywords = ETHIOPIAN_MEDICAL_VOCABULARY.copy()

#     headers = {
#         "Authorization": f"Bearer {INTRON_API_KEY}",
#         "Accept": "application/json"
#     }

#     data_payload = {
#         "language": language_code,
#         "phrase_boost": payload_keywords,  # Intron Custom Vocabulary Boosting
#         "enable_word_confidence": True
#     }

#     files_payload = {
#         "file": (file.filename, contents, file.content_type or "audio/wav")
#     }

#     try:
#         async with httpx.AsyncClient(timeout=30.0) as client:
#             response = await client.post(
#                 INTRON_ENDPOINT,
#                 headers=headers,
#                 data=data_payload,
#                 files=files_payload
#             )
#             response.raise_for_status()
#             res_json = response.json()

#             # Process word confidence scoring
#             words = res_json.get("words", [])
#             low_confidence_terms = [
#                 w["word"] for w in words if w.get("confidence", 1.0) < 0.70
#             ]

#             return {
#                 "status": "success",
#                 "transcript": res_json.get("transcript", ""),
#                 "confidence_score": res_json.get("confidence", 0.0),
#                 "low_confidence_flagged": low_confidence_terms,
#                 "boosted_vocabulary_count": len(payload_keywords)
#             }

#     except httpx.HTTPStatusError as e:
#         logger.error(f"Intron API Error: {e.response.status_code} - {e.response.text}")
#         raise HTTPException(status_code=e.response.status_code, detail=f"ASR Provider Error: {e.response.text}")
#     except Exception as e:
#         logger.error(f"Internal gateway error: {str(e)}")
#         raise HTTPException(status_code=500, detail="Audio transcription gateway processing failed.")
# INTRON_STREAM_ENDPOINT = "wss://infer.voice.intron.io/stt/v1/stream"

# @app.websocket("/ws/stream")
# async def websocket_stream(websocket: WebSocket):
#     await websocket.accept()

#     language = websocket.query_params.get("use_language_asr_input", "am")

#     if not INTRON_API_KEY:
#         await websocket.send_json({"error": "Intron API key not configured on server"})
#         await websocket.close()
#         return

#     intron_url = f"{INTRON_STREAM_ENDPOINT}?sample_rate=16000&bit_rate=16&num_channels=1&use_language_asr_input={language}"

#     try:
#         async with websockets.connect(
#             intron_url,
#             extra_headers={"Authorization": f"Bearer {INTRON_API_KEY}"}
#         ) as intron_ws:

#             async def forward_browser_to_intron():
#                 try:
#                     while True:
#                         data = await websocket.receive()
#                         if data.get("bytes") is not None:
#                             audio_b64 = base64.b64encode(data["bytes"]).decode("utf-8")
#                             await intron_ws.send(json.dumps({
#                                 "message_type": "INPUT_AUDIO_CHUNK",
#                                 "audio_base_64": audio_b64
#                             }))
#                         elif data.get("text") is not None:
#                             try:
#                                 msg = json.loads(data["text"])
#                                 if msg.get("event") == "stop":
#                                     await intron_ws.send(json.dumps({"message_type": "COMMIT"}))
#                             except json.JSONDecodeError:
#                                 pass
#                 except WebSocketDisconnect:
#                     pass

#             async def forward_intron_to_browser():
#                 async for message in intron_ws:
#                     payload = json.loads(message)
#                     msg_type = payload.get("message_type")
#                     if msg_type == "PARTIAL_TRANSCRIPT":
#                         await websocket.send_json({"transcript": payload.get("transcript", "")})
#                     elif msg_type == "COMMITTED_TRANSCRIPT":
#                         await websocket.send_json({"transcript": payload.get("transcript_text", "")})
#                     elif msg_type in ("ERROR", "INPUT_ERROR", "AUTHENTICATION_ERROR", "QUOTA_EXCEEDED"):
#                         await websocket.send_json({"error": payload.get("message", msg_type)})

#             forward_task = asyncio.create_task(forward_browser_to_intron())
#             backward_task = asyncio.create_task(forward_intron_to_browser())
#             done, pending = await asyncio.wait(
#                 [forward_task, backward_task], return_when=asyncio.FIRST_COMPLETED
#             )
#             for task in pending:
#                 task.cancel()

#     except Exception as e:
#         logger.error(f"Intron streaming bridge error: {e}")
#         try:
#             await websocket.send_json({"error": str(e)})
#         except Exception:
#             pass
#     finally:
#         try:
#             await websocket.close()
#         except Exception:
#             pass

# INTRON_SYNC_UPLOAD_ENDPOINT = "https://infer.voice.intron.io/file/v1/upload/sync"

# @app.post("/api/intron/stt/upload-sync")
# async def intron_stt_upload_sync(request: Request):
#     if not INTRON_API_KEY:
#         raise HTTPException(status_code=503, detail="Intron API key not configured on server")

#     form = await request.form()
#     audio_file = form.get("audio_file_blob")
#     if audio_file is None:
#         raise HTTPException(status_code=400, detail="Missing audio_file_blob in form data")

#     file_bytes = await audio_file.read()
#     filename = form.get("audio_file_name") or getattr(audio_file, "filename", "recording.wav")

#     files_payload = {
#         "audio_file_blob": (filename, file_bytes, audio_file.content_type or "audio/wav")
#     }
#     data_payload = {
#         "audio_file_name": filename,
#         "use_language_asr_input": form.get("use_language_asr_input", "am"),
#         "use_category": form.get("use_category", "file_category_telehealth"),
#         "use_disable_llm_corrections": form.get("use_disable_llm_corrections", "FALSE"),
#     }
#     headers = {"Authorization": f"Bearer {INTRON_API_KEY}"}

#     try:
#         async with httpx.AsyncClient(timeout=130.0) as client:
#             response = await client.post(
#                 INTRON_SYNC_UPLOAD_ENDPOINT,
#                 headers=headers,
#                 data=data_payload,
#                 files=files_payload
#             )
#             response.raise_for_status()
#             return response.json()
#     except httpx.HTTPStatusError as e:
#         logger.error(f"Intron sync upload error: {e.response.status_code} - {e.response.text}")
#         raise HTTPException(status_code=e.response.status_code, detail=f"Intron upload error: {e.response.text}")
#     except Exception as e:
#         logger.error(f"Intron sync upload gateway error: {e}")
#         raise HTTPException(status_code=500, detail="Audio upload processing failed.")

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
"""
Sahara Healthcare Suite (AfriHealth AI) - FastAPI Backend Gateway
Includes:
- Intron v2.5 Custom Medical Vocabulary Phrase Boosting
- Low-confidence entity flagging (< 0.70 threshold)
- Payload size validation and rate limiting
- CORS configuration for static frontends & Cloudflare Pages
"""

import os
import io
import json
import time
import logging
import tempfile
from collections import deque
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    description="Secure proxy for Intron v2.5 ASR with Ethiopian medical term boosting",
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration & Keys
INTRON_API_KEY = os.getenv("INTRON_API_KEY", "")
INTRON_ENDPOINT = os.getenv("INTRON_ENDPOINT", "https://api.intron.io/v1/transcribe")

# Ethiopian Medical & Local Symptom Phrase Boosting Dictionary
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
    boost_vocabulary: Optional[List[str]] = None

@app.get("/health")
async def health_check():
    return {
        "status": "online",
        "service": "AfriHealth AI Gateway",
        "intron_configured": bool(INTRON_API_KEY),
        "boost_phrases_loaded": len(ETHIOPIAN_MEDICAL_VOCABULARY)
    }

async def _call_intron_transcribe(
    contents: bytes,
    filename: str,
    content_type: Optional[str],
    language_code: str = "am-ET",
) -> dict:
    """
    Core Intron v2.5 call, shared by the live /api/v1/transcribe endpoint and
    the /api/v1/benchmark comparison endpoint. Raises HTTPException on
    provider/gateway errors so callers can decide how to surface them.
    Returns a normalized dict: {mode, transcript, confidence_score, ...}.
    """
    if not INTRON_API_KEY:
        logger.warning("INTRON_API_KEY not set. Returning judge-mode mock response.")
        return {
            "mode": "fallback_judge_mode",
            "transcript": "ከፍተኛ ትኩሳት እና ሳል አለው:: Paracetamol 500mg t.i.d. given.",
            "confidence_score": 0.89,
            "entities": [
                {"text": "ትኩሳት", "type": "SYMPTOM", "confidence": 0.95},
                {"text": "Paracetamol 500mg", "type": "MEDICATION", "confidence": 0.92, "boosted": True}
            ],
            "flagged_terms": [],
        }

    if len(contents) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file size exceeds maximum limit of 25MB")

    # Merge default medical vocabulary with any runtime custom phrases
    payload_keywords = ETHIOPIAN_MEDICAL_VOCABULARY.copy()

    headers = {
        "Authorization": f"Bearer {INTRON_API_KEY}",
        "Accept": "application/json"
    }

    data_payload = {
        "language": language_code,
        "phrase_boost": payload_keywords,  # Intron Custom Vocabulary Boosting
        "enable_word_confidence": True
    }

    files_payload = {
        "file": (filename, contents, content_type or "audio/wav")
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                INTRON_ENDPOINT,
                headers=headers,
                data=data_payload,
                files=files_payload
            )
            response.raise_for_status()
            res_json = response.json()

            words = res_json.get("words", [])
            low_confidence_terms = [
                w["word"] for w in words if w.get("confidence", 1.0) < 0.70
            ]

            return {
                "mode": "live",
                "transcript": res_json.get("transcript", ""),
                "confidence_score": res_json.get("confidence", 0.0),
                "low_confidence_flagged": low_confidence_terms,
                "boosted_vocabulary_count": len(payload_keywords),
            }

    except httpx.HTTPStatusError as e:
        logger.error(f"Intron API Error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=f"ASR Provider Error: {e.response.text}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Internal gateway error: {str(e)}")
        raise HTTPException(status_code=500, detail="Audio transcription gateway processing failed.")


@app.post("/api/v1/transcribe")
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    language_code: str = "am-ET"
):
    """
    Proxies audio payload to Intron v2.5 API with medical phrase boosting.
    """
    contents = await file.read()
    result = await _call_intron_transcribe(contents, file.filename, file.content_type, language_code)

    if result["mode"] == "fallback_judge_mode":
        return JSONResponse(status_code=200, content=result)

    return {
        "status": "success",
        "transcript": result["transcript"],
        "confidence_score": result["confidence_score"],
        "low_confidence_flagged": result["low_confidence_flagged"],
        "boosted_vocabulary_count": result["boosted_vocabulary_count"],
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

INTRON_SYNC_UPLOAD_ENDPOINT = "https://infer.voice.intron.io/file/v1/upload/sync"

@app.post("/api/intron/stt/upload-sync")
async def intron_stt_upload_sync(request: Request):
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
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Intron sync upload error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=f"Intron upload error: {e.response.text}")
    except Exception as e:
        logger.error(f"Intron sync upload gateway error: {e}")
        raise HTTPException(status_code=500, detail="Audio upload processing failed.")

# ---------------------------------------------------------------------------
# Sahara v2.5 vs. Whisper Medium benchmark
#
# Ports the Colab comparison notebook (WER/CER via jiwer + a keyword-based
# triage classifier) into the gateway as a real endpoint, so the frontend's
# "Benchmark Matrix" tab can show actual measured numbers on operatorsupplied
# audio + reference transcripts, instead of only the embedded fixture rows.
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

    waveform, sample_rate = torchaudio.load(audio_path)
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
    sahara_result = await _call_intron_transcribe(contents, file.filename, file.content_type, language_code)
    sahara_transcript = sahara_result["transcript"]

    # 2. Whisper Medium transcript -- needs a real file on disk for torchaudio
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        raw_audio_path = tmp.name

    try:
        try:
            whisper_transcript = await asyncio.to_thread(_transcribe_with_whisper, raw_audio_path)
        except ImportError as e:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Whisper benchmark dependencies not installed on this instance "
                    f"(torch/torchaudio/transformers). Missing: {e}"
                ),
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
            "mode": "live",
        },
    ]

    return {
        "status": "success",
        "reference_transcript": reference_transcript,
        "results": results,
        "triage_agreement": results[0]["triage"] == results[1]["triage"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
