"""
run.py
======
Development entry point. Run with:  python run.py

For production use uvicorn directly:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
    )
