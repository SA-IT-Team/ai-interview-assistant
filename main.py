"""
Entry point - imports the FastAPI app from app.main
This allows deployment platforms to auto-detect the FastAPI application.
"""
from app.main import app

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
