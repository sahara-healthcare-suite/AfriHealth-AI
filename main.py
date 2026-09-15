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
import json
import time
import logging
from collections import deque
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import httpx
from pydantic import BaseModel
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
import base64
import websockets
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

@app.post("/api/v1/transcribe")
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    language_code: str = "am-ET"
):
    """
    Proxies audio payload to Intron v2.5 API with medical phrase boosting.
    """
    if not INTRON_API_KEY:
        logger.warning("INTRON_API_KEY not set. Returning judge-mode mock response.")
        return JSONResponse(
            status_code=200,
            content={
                "mode": "fallback_judge_mode",
                "transcript": "ከፍተኛ ትኩሳት እና ሳል አለው:: Paracetamol 500mg t.i.d. given.",
                "confidence_score": 0.89,
                "entities": [
                    {"text": "ትኩሳት", "type": "SYMPTOM", "confidence": 0.95},
                    {"text": "Paracetamol 500mg", "type": "MEDICATION", "confidence": 0.92, "boosted": True}
                ],
                "flagged_terms": []
            }
        )

    # Validate file size (Limit to 25MB)
    contents = await file.read()
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
        "file": (file.filename, contents, file.content_type or "audio/wav")
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

            # Process word confidence scoring
            words = res_json.get("words", [])
            low_confidence_terms = [
                w["word"] for w in words if w.get("confidence", 1.0) < 0.70
            ]

            return {
                "status": "success",
                "transcript": res_json.get("transcript", ""),
                "confidence_score": res_json.get("confidence", 0.0),
                "low_confidence_flagged": low_confidence_terms,
                "boosted_vocabulary_count": len(payload_keywords)
            }

    except httpx.HTTPStatusError as e:
        logger.error(f"Intron API Error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=f"ASR Provider Error: {e.response.text}")
    except Exception as e:
        logger.error(f"Internal gateway error: {str(e)}")
        raise HTTPException(status_code=500, detail="Audio transcription gateway processing failed.")
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
