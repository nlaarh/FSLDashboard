"""Minimal FastAPI test app for Azure"""
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"status": "working", "message": "Minimal test app is running!"}

@app.get("/api/health")
def health():
    return {"status": "ok", "test": True}
