"""Minimal test app to verify Azure deployment works"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok", "message": "Test app is working!"}

@app.get("/api/health")
def health():
    return {"status": "ok", "test": True}
