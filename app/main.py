from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import json
import os
from datetime import datetime

from app.schemas import ChatRequest, TTSRequest, EvaluationRequest
from app.llm import get_interview_response, generate_evaluation
from app.tts import text_to_speech
from app.stt import speech_to_text
from app.resume import extract_text_from_pdf

app = FastAPI(title="AI Interview Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EVALUATIONS_DIR = "evaluations"
os.makedirs(EVALUATIONS_DIR, exist_ok=True)

@app.get("/")
async def root():
    return {"message": "AI Interview Assistant API"}

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        response = get_interview_response(
            messages=request.conversation_history,
            job_role=request.job_role,
            resume_text=request.resume_text
        )
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tts")
async def tts(request: TTSRequest):
    try:
        audio_bytes = await text_to_speech(request.text)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/stt")
async def stt(audio: UploadFile = File(...)):
    try:
        text = await speech_to_text(audio.file)
        return {"text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    try:
        content = await file.read()
        text = extract_text_from_pdf(content)
        return {"text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/evaluate")
async def evaluate(request: EvaluationRequest):
    try:
        evaluation = generate_evaluation(
            messages=request.conversation_history,
            job_role=request.job_role
        )
        
        eval_data = save_evaluation(evaluation, request.job_role)
        
        return {"evaluation": evaluation, "saved": eval_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def save_evaluation(evaluation: str, job_role: str) -> dict:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{job_role.replace(' ', '_')}_{timestamp}.json"
    filepath = os.path.join(EVALUATIONS_DIR, filename)
    
    data = {
        "job_role": job_role,
        "evaluation": evaluation,
        "timestamp": datetime.now().isoformat()
    }
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    
    return {"filename": filename, "timestamp": data["timestamp"]}

@app.get("/evaluations")
async def list_evaluations():
    try:
        files = os.listdir(EVALUATIONS_DIR)
        evaluations = []
        for f in files:
            if f.endswith('.json'):
                with open(os.path.join(EVALUATIONS_DIR, f)) as file:
                    data = json.load(file)
                    evaluations.append({"filename": f, **data})
        return {"evaluations": evaluations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
