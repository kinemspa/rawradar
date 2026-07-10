from fastapi import FastAPI
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="RawRadar - Raw Weather Observations")

@app.get("/")
def root():
    return {"message": "RawRadar is running. Tracking original weather data."}

@app.get("/health")
def health():
    return {"status": "healthy"}
