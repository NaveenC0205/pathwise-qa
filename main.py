"""Vercel FastAPI entry. Local uvicorn still uses backend/app/main.py."""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent / 'backend'))
from app.api.qa import router

app = FastAPI(title='Pathwise QA', version='0.1.0')
app.include_router(router)

@app.get('/health')
async def health():
    return {'status': 'ok', 'application': 'Pathwise QA'}

PUBLIC = Path(__file__).resolve().parent / 'ui'
ASSETS = PUBLIC / 'assets'
if ASSETS.exists():
    app.mount('/assets', StaticFiles(directory=ASSETS), name='assets')

@app.get('/')
async def workspace():
    index = PUBLIC / 'index.html'
    if index.exists():
        return FileResponse(index)
    return {'application': 'Pathwise QA', 'ui': 'frontend build missing'}
