from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api.qa import router
app = FastAPI(title='Pathwise QA', version='0.1.0')
app.include_router(router)
@app.get('/health')
async def health(): return {'status': 'ok', 'application': 'Pathwise QA'}
frontend = Path(__file__).resolve().parents[2] / 'frontend/dist'
if frontend.exists(): app.mount('/', StaticFiles(directory=frontend, html=True), name='workspace')
