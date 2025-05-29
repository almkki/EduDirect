import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",   # Assuming your combined code is saved in main.py and the FastAPI app is named `app`
        host="127.0.0.1",
        port=8000,
        reload=True   # auto-reload on code changes (good for development)
    )
