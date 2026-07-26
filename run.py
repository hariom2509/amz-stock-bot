"""
Entry point for the Amazon Stock Watcher Hosted FastAPI Backend + Bot + Scheduler.

Run with:
    python run.py
"""
import os
import sys

# Ensure the project root is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from app.main import app

if __name__ == "__main__":
    port = int(os.getenv("API_PORT", 8000))
    host = os.getenv("API_HOST", "0.0.0.0")
    print(f"Starting Amazon Stock Watcher API server on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, workers=1)
