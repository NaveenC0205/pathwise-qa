"""QA API: streamed agent events and cancellable bounded runs."""
import asyncio
import contextlib
import json
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from starlette.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from app.qa.models import QAInput
from app.qa.pipeline import run_plan
from app.qa.browser import capabilities, check_target
from app.config import get_settings

router = APIRouter(prefix='/api/qa', tags=['qa'])


@router.get('/capabilities')
async def qa_capabilities():
    settings = get_settings()
    return {'live_available': settings.llm_provider == 'ollama' or bool(settings.openai_api_key), 'model': settings.openai_model if settings.llm_provider in ('openai', 'groq', 'openai-compat') else settings.llm_model, 'models': settings.models, 'figma_api_available': bool(settings.figma_access_token), 'browser': capabilities(), 'agents': 7, 'max_repair_rounds': 2}


def preflight(body):
    if body.model and body.model not in get_settings().models:
        raise HTTPException(422, 'Choose a configured model.')
    if body.explore_ui:
        from app.qa.figma import parse_figma_url
        try:
            for module in body.modules:
                if module.figma_url: parse_figma_url(module.figma_url)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.post('/generate')
async def generate(body: QAInput):
    preflight(body)
    try:
        return await asyncio.wait_for(run_plan(body), timeout=3600)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(504, 'QA run exceeded 60 minutes. Split the sources into smaller modules.') from exc
    except Exception as exc:
        raise HTTPException(502, 'A model or browser service failed. Check configuration and retry.') from exc


@router.post('/generate/stream')
async def generate_stream(body: QAInput, request: Request):
    preflight(body)
    async def stream():
        queue = asyncio.Queue()
        async def emit(event):
            await queue.put({'type': 'event', **event})
        async def worker():
            try:
                result = await asyncio.wait_for(run_plan(body, emit), timeout=3600)
                await queue.put({'type': 'result', 'result': result})
            except asyncio.CancelledError:
                raise
            except ValueError as exc:
                await queue.put({'type': 'error', 'message': str(exc)})
            except TimeoutError:
                await queue.put({'type': 'error', 'message': 'Run reached the 60-minute limit. Split the sources into smaller modules.'})
            except Exception:
                await queue.put({'type': 'error', 'message': 'A model or browser service failed. Check server configuration and retry.'})
        task = asyncio.create_task(worker())
        try:
            while True:
                if await request.is_disconnected(): break
                try: row = await asyncio.wait_for(queue.get(), timeout=1)
                except TimeoutError: continue
                yield json.dumps(row) + '\n'
                if row['type'] in ('result', 'error'): break
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError): await task
    return StreamingResponse(stream(), media_type='application/x-ndjson', headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@router.post('/import-cases')
async def upload_cases(file: UploadFile = File(...)):
    from app.qa.imports import import_cases
    try:
        data = await file.read(2_000_001)
        return await run_in_threadpool(import_cases, data, file.filename or '')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(503, 'Excel import requires the server qa dependencies.') from exc
    finally:
        await file.close()
