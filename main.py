import asyncio
import json
import logging
import os

import websockets
import requests
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SaharaHealthcareSuite")

app = FastAPI(
    title="Sahara Healthcare Suite API",
    description="Code-Switched Speech-to-Text & Clinical Artifact Generation Engine",
    version="2.5.0",
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

INTRON_WS_URL = os.getenv("INTRON_WS_URL", "wss://infer.voice.intron.io/stt/v1/stream")
INTRON_TTS_WS_URL = os.getenv("INTRON_TTS_WS_URL", "wss://infer.voice.intron.io/tts/v1/stream")
INTRON_TTS_GENERATE_URL = os.getenv(
    "INTRON_TTS_GENERATE_URL", "https://infer.voice.intron.io/tts/v1/generate"
)
INTRON_STT_UPLOAD_SYNC_URL = os.getenv(
    "INTRON_STT_UPLOAD_SYNC_URL", "https://infer.voice.intron.io/file/v1/upload/sync"
)
INTRON_TTS_STATUS_URL = os.getenv(
    "INTRON_TTS_STATUS_URL", "https://infer.voice.intron.io/tts/v1/status"
)
INTRON_API_KEY = os.getenv("INTRON_API_KEY", "")


def generate_clinical_artifacts(transcript: str, patient_context: dict | None = None) -> dict:
    patient_context = patient_context or {}
    text_lower = transcript.lower()
    symptoms = []
    if "cough" in text_lower or "dhukkuba" in text_lower:
        symptoms.append("Persistent cough")
    if "fever" in text_lower or "ho'a" in text_lower or "tazabi" in text_lower:
        symptoms.append("Elevated body temperature / Fever")
    if "headache" in text_lower or "bo'oo" in text_lower:
        symptoms.append("Acute headache")
    if not symptoms:
        symptoms.append("General malaise and unspecified symptoms")

    icd10_codes = []
    if "fever" in text_lower:
        icd10_codes.append({"code": "R50.9", "description": "Fever, unspecified"})
    if "cough" in text_lower:
        icd10_codes.append({"code": "R05.9", "description": "Cough, unspecified"})
    if "headache" in text_lower:
        icd10_codes.append({"code": "R51.9", "description": "Headache, unspecified"})
    if not icd10_codes:
        icd10_codes.append({"code": "Z00.00", "description": "General adult medical examination"})

    soap_note = {
        "subjective": f"Patient presents with: {', '.join(symptoms)}. Symptoms documented via code-switched oral intake.",
        "objective": "Not provided in the source transcript; clinician examination and vital signs required.",
        "assessment": f"Primary Clinical Assessment: Code-Switched Consultation evaluation. Suspected condition matching ICD-10 ({icd10_codes[0]['code']}).",
        "plan": "1. Clinician review required before treatment or coding.\n2. Record vital signs, examination findings, allergies, age, weight, and relevant history.\n3. Follow up according to clinician assessment.",
    }

    allergies = str(patient_context.get("allergies", "")).lower()
    clinician_confirmed = patient_context.get("clinician_confirmed", False) is True
    allergy_conflict = any(term in allergies for term in ("penicillin", "amoxicillin", "augmentin"))
    viral_features = any(term in text_lower for term in ("runny nose", "clear nasal", "mild sore throat", "viral"))
    medication_alerts = []
    blocked_medications = []

    if viral_features:
        medication_alerts.append(
            "Possible viral upper-respiratory presentation: do not suggest empiric antibiotics."
        )
    if allergy_conflict:
        medication_alerts.append(
            "Penicillin-family allergy recorded: Amoxicillin/Augmentin suggestions are blocked."
        )
    if viral_features:
        blocked_medications.append("Amoxicillin")

    medication_candidates = []
    if "fever" in text_lower or "headache" in text_lower:
        medication_candidates.append(
            {"drug": "Paracetamol", "dosage": "Dose requires age, weight, contraindications, and local protocol.", "frequency": "Clinician to determine", "duration": "Clinician to determine"}
        )
    if "cough" in text_lower and not viral_features:
        medication_candidates.append(
            {"drug": "Amoxicillin", "dosage": "Requires confirmed indication and patient-specific dosing.", "frequency": "Clinician to determine", "duration": "Clinician to determine"}
        )

    for candidate in medication_candidates:
        if not clinician_confirmed:
            if candidate["drug"] not in blocked_medications:
                blocked_medications.append(candidate["drug"])
        elif candidate["drug"] == "Amoxicillin" and (allergy_conflict or viral_features):
            if candidate["drug"] not in blocked_medications:
                blocked_medications.append(candidate["drug"])

    prescriptions = [
        candidate for candidate in medication_candidates
        if candidate["drug"] not in blocked_medications
    ]
    if blocked_medications:
        medication_alerts.append(
            "Medication suggestions are blocked until a clinician confirms the indication, dose, allergies, and patient context."
        )

    return {
        "transcript": transcript,
        "soap_note": soap_note,
        "icd10_codes": icd10_codes,
        "prescriptions": prescriptions,
        "safety_review": {
            "clinician_review_required": True,
            "clinician_confirmed": clinician_confirmed,
            "medication_suggestions_blocked": bool(blocked_medications),
            "blocked_medications": blocked_medications,
            "alerts": medication_alerts,
        },
    }


@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "Sahara Healthcare Suite API",
        "intron_connected": bool(INTRON_API_KEY),
        "version": "2.5.0",
    }


def masked_intron_authorization() -> str:
    if not INTRON_API_KEY:
        raise HTTPException(status_code=503, detail="Intron API key is not configured")
    return f"Bearer {INTRON_API_KEY}"


def intron_request_authorization() -> str:
    if not INTRON_API_KEY:
        raise HTTPException(status_code=503, detail="Intron API key is not configured")
    return (
        INTRON_API_KEY
        if INTRON_API_KEY.lower().startswith("bearer ")
        else f"Bearer {INTRON_API_KEY}"
    )


def provider_authorization_fixed() -> str:
    if not INTRON_API_KEY:
        raise HTTPException(status_code=503, detail="Intron API key is not configured")
    return INTRON_API_KEY if INTRON_API_KEY.lower().startswith("bearer ") else f"Bearer {INTRON_API_KEY}"


def provider_authorization() -> str:
    if not INTRON_API_KEY:
        raise HTTPException(status_code=503, detail="Intron API key is not configured")
    if INTRON_API_KEY.lower().startswith("bearer "):
        return INTRON_API_KEY
    return "Bearer " + INTRON_API_KEY


@app.post("/api/intron/tts/generate")
def generate_intron_tts(data: dict):
    text = data.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        raise HTTPException(status_code=400, detail="TTS text must contain 1 to 4096 characters")
    required = ("voice_language", "voice_accent", "voice_gender")
    if any(not isinstance(data.get(field), str) or not data[field].strip() for field in required):
        raise HTTPException(status_code=400, detail="TTS voice language, accent, and gender are required")
    payload = {key: value for key, value in data.items() if key in (
        "text", "voice_language", "voice_accent", "voice_gender", "output_audio_format"
    )}
    try:
        response = requests.post(
            INTRON_TTS_GENERATE_URL,
            headers={"Authorization": provider_authorization(), "Content-Type": "application/json"},
            json=payload,
            timeout=125,
        )
    except requests.RequestException as error:
        logger.error("Intron TTS request failed: %s", error)
        raise HTTPException(status_code=502, detail="Intron TTS request failed") from error
    try:
        body = response.json()
    except ValueError as error:
        raise HTTPException(status_code=502, detail="Intron TTS returned an invalid response") from error
    return Response(
        content=json.dumps(body),
        status_code=response.status_code,
        media_type="application/json",
    )


@app.get("/api/intron/tts/status/{text_id}")
def get_intron_tts_status(text_id: str):
    if not text_id or "/" in text_id:
        raise HTTPException(status_code=400, detail="Invalid TTS text ID")
    try:
        response = requests.get(
            f"{INTRON_TTS_STATUS_URL.rstrip('/')}/{text_id}",
            headers={"Authorization": provider_authorization()},
            timeout=30,
        )
    except requests.RequestException as error:
        logger.error("Intron TTS status request failed: %s", error)
        raise HTTPException(status_code=502, detail="Intron TTS status request failed") from error
    try:
        body = response.json()
    except ValueError as error:
        raise HTTPException(status_code=502, detail="Intron TTS returned an invalid response") from error
    return Response(content=json.dumps(body), status_code=response.status_code, media_type="application/json")


@app.post("/api/intron/stt/upload-sync")
def upload_intron_stt_sync(
    audio_file_blob: UploadFile = File(...),
    audio_file_name: str = Form(...),
    use_language_asr_input: str = Form(...),
    use_diarization: str | None = Form(default=None),
    use_category: str | None = Form(default=None),
    use_disable_llm_corrections: str | None = Form(default=None),
):
    audio_bytes = audio_file_blob.file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    fields = {
        "audio_file_name": audio_file_name,
        "use_language_asr_input": use_language_asr_input,
    }
    optional_fields = {
        "use_diarization": use_diarization,
        "use_category": use_category,
        "use_disable_llm_corrections": use_disable_llm_corrections,
    }
    fields.update({key: value for key, value in optional_fields.items() if value is not None})
    try:
        response = requests.post(
            INTRON_STT_UPLOAD_SYNC_URL,
            headers={"Authorization": provider_authorization()},
            files={"audio_file_blob": (audio_file_name, audio_bytes, audio_file_blob.content_type)},
            data=fields,
            timeout=125,
        )
    except requests.RequestException as error:
        logger.error("Intron synchronous STT request failed: %s", error)
        raise HTTPException(status_code=502, detail="Intron synchronous STT request failed") from error
    try:
        body = response.json()
    except ValueError as error:
        raise HTTPException(status_code=502, detail="Intron STT returned an invalid response") from error
    return Response(content=json.dumps(body), status_code=response.status_code, media_type="application/json")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Client WebSocket connection accepted.")
    auth_header = provider_authorization() if INTRON_API_KEY else ""
    headers = {"Authorization": auth_header} if auth_header else {}

    try:
        async with websockets.connect(INTRON_WS_URL, additional_headers=headers) as intron_ws:
            full_transcript = ""
            while True:
                message = await websocket.receive()
                if message.get("bytes"):
                    await intron_ws.send(message["bytes"])
                elif message.get("text"):
                    payload = json.loads(message["text"])
                    if payload.get("event") == "stop":
                        await intron_ws.send(json.dumps({"action": "flush"}))
                        try:
                            while True:
                                response = await asyncio.wait_for(intron_ws.recv(), timeout=3)
                                data = json.loads(response)
                                partial_text = data.get("text", "")
                                is_final = data.get("is_final", True)
                                if partial_text:
                                    full_transcript = f"{full_transcript} {partial_text}".strip()
                                await websocket.send_json({
                                    "status": "transcribed",
                                    "partial": partial_text,
                                    "transcript": full_transcript,
                                    "is_final": is_final,
                                    "artifacts": generate_clinical_artifacts(full_transcript),
                                })
                                if is_final:
                                    break
                        except asyncio.TimeoutError:
                            logger.warning("Timed out waiting for final Intron transcript.")
                        break

                try:
                    response = await asyncio.wait_for(intron_ws.recv(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
                data = json.loads(response)
                partial_text = data.get("text", "")
                is_final = data.get("is_final", False)
                if partial_text:
                    full_transcript = (
                        f"{full_transcript} {partial_text}".strip()
                        if is_final
                        else partial_text
                    )
                    await websocket.send_json({
                        "status": "transcribing",
                        "partial": partial_text,
                        "transcript": full_transcript,
                        "is_final": is_final,
                        "artifacts": generate_clinical_artifacts(full_transcript) if is_final else {},
                    })
    except WebSocketDisconnect:
        logger.info("Client disconnected.")
    except Exception as error:
        logger.error("Speech recognition connection failed: %s", error)
        await websocket.send_json({
            "status": "error",
            "message": f"Speech Recognition Connection Error: {error}",
            "fallback_mode": False,
        })
        await websocket.close()


@app.websocket("/ws/tts")
async def tts_websocket_endpoint(websocket: WebSocket):
    """Proxy the documented Intron streaming TTS protocol without exposing the key."""
    await websocket.accept()
    query = str(websocket.scope.get("query_string", b""), encoding="utf-8")
    tts_url = f"{INTRON_TTS_WS_URL}?{query}" if query else INTRON_TTS_WS_URL
    headers = {"Authorization": f"Bearer {INTRON_API_KEY}"} if INTRON_API_KEY else {}

    try:
        headers = {"Authorization": provider_authorization()}
        async with websockets.connect(tts_url, additional_headers=headers) as intron_ws:
            initial_response = await intron_ws.recv()
            if isinstance(initial_response, bytes):
                await websocket.send_bytes(initial_response)
            else:
                await websocket.send_text(initial_response)
            while True:
                message = await websocket.receive()
                if message.get("text"):
                    await intron_ws.send(message["text"])
                elif message.get("type") == "websocket.disconnect":
                    break

                response = await intron_ws.recv()
                if isinstance(response, bytes):
                    await websocket.send_bytes(response)
                else:
                    await websocket.send_text(response)
                    if '"message_type": "COMMITTED_AUDIO"' in response:
                        break
    except WebSocketDisconnect:
        logger.info("TTS client disconnected.")
    except Exception as error:
        logger.error("TTS connection failed: %s", error)
        await websocket.send_json({
            "message_type": "ERROR",
            "error": "Text-to-speech connection failed.",
        })
        await websocket.close()


@app.post("/api/v1/clinical/process-text")
def process_clinical_text(data: dict):
    text = data.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="Text payload is required")
    return generate_clinical_artifacts(text, data.get("patient_context"))
