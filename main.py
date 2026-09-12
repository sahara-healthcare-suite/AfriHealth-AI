import os
import json
import asyncio
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SaharaHealthcareSuite")

app = FastAPI(
    title="Sahara Healthcare Suite API",
    description="Code-Switched Speech-to-Text & Clinical Artifact Generation Engine",
    version="2.5.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

INTRON_WS_URL = os.getenv("INTRON_WS_URL", "wss://infer.voice.intron.io/stt/v1/stream")
INTRON_API_KEY = os.getenv("INTRON_API_KEY", "")

def generate_clinical_artifacts(transcript: str) -> dict:
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
        "objective": "Vital signs stable. Physical exam reveals no acute respiratory distress.",
        "assessment": f"Primary Clinical Assessment: Code-Switched Consultation evaluation. Suspected condition matching ICD-10 ({icd10_codes[0]['code']}).",
        "plan": "1. Administer prescribed symptomatic treatment.\n2. Hydration and resting protocol.\n3. Follow up in 48-72 hours if symptoms persist."
    }

    prescriptions = []
    if "fever" in text_lower or "headache" in text_lower:
        prescriptions.append({"drug": "Paracetamol", "dosage": "500mg", "frequency": "TID (3 times daily)", "duration": "5 days"})
    if "cough" in text_lower:
        prescriptions.append({"drug": "Amoxicillin", "dosage": "500mg", "frequency": "BID (2 times daily)", "duration": "7 days"})

    return {
        "transcript": transcript,
        "soap_note": soap_note,
        "icd10_codes": icd10_codes,
        "prescriptions": prescriptions
    }

@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "Sahara Healthcare Suite API",
        "intron_connected": bool(INTRON_API_KEY),
        "version": "2.5.0"
    }

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)

@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Client WebSocket connection accepted.")

    async def forward_audio_to_intron():
        headers = {"Authorization": "Bearer " + INTRON_API_KEY} if INTRON_API_KEY else {}
        try:
            async with websockets.connect(INTRON_WS_URL, additional_headers=headers) as intron_ws:
                async def receive_from_client():
                    try:
                        while True:
                            message = await websocket.receive()
                            if "bytes" in message and message["bytes"]:
                                await intron_ws.send(message["bytes"])
                            elif "text" in message and message["text"]:
                                payload = json.loads(message["text"])
                                if payload.get("event") == "stop":
                                    await intron_ws.send(json.dumps({"action": "flush"}))
                                    break
                    except WebSocketDisconnect:
                        logger.info("Client disconnected.")
                    except Exception as e:
                        logger.error(f"Error reading client audio: {e}")

                async def receive_from_intron():
                    full_transcript = ""
                    try:
                        async for msg in intron_ws:
                            data = json.loads(msg)
                            partial_text = data.get("text", "")
                            is_final = data.get("is_final", False)

                            if partial_text:
                                full_transcript += " " + partial_text if is_final else partial_text
                                artifacts = generate_clinical_artifacts(full_transcript.strip()) if is_final else {}
                                await websocket.send_json({
                                    "status": "transcribing",
                                    "partial": partial_text,
                                    "transcript": full_transcript.strip(),
                                    "is_final": is_final,
                                    "artifacts": artifacts
                                })
                    except Exception as e:
                        logger.error(f"Error receiving from Intron STT engine: {e}")

                await asyncio.gather(receive_from_client(), receive_from_intron())
        except Exception as err:
            logger.error(f"Failed to connect to Intron STT engine: {err}")
            await websocket.send_json({
                "status": "error",
                "message": f"Speech Recognition Connection Error: {str(err)}",
                "fallback_mode": False
            })
            await websocket.close()

    asyncio.create_task(forward_audio_to_intron())

@app.post("/api/v1/clinical/process-text")
def process_clinical_text(data: dict):
    text = data.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="Text payload is required")
    return generate_clinical_artifacts(text)
