"""Test doubles are injected only here, never selected by the production API."""
from uuid import uuid4
import pytest
from langgraph.types import Command
from app.qa.models import QAInput
from app.qa.workflow import stored_graph, config, Approval, validate_approval
from test_qa import FakeRouter, module


@pytest.mark.asyncio
async def test_sqlite_pause_survives_restart_and_uses_edited_understanding(tmp_path):
    database = tmp_path / 'checkpoints.sqlite'
    run_id = str(uuid4())
    model = FakeRouter()
    async with stored_graph(llm=model, database=database) as graph:
        result = await graph.ainvoke({'input': QAInput(modules=[module()]).model_dump()}, config(run_id))
        assert result['__interrupt__']
        assert 'result' not in result
        assert model.reg_calls == 0  # No test-case designer runs before approval.
        analysis = result['analysis']
    approval = Approval(approved=True, requirements=analysis['requirements'], navigation=analysis['navigation'], strategy=analysis['strategy'])
    approval.requirements.requirements[0].text = 'Show the product selected by the user.'
    async with stored_graph(llm=model, database=database) as graph:
        saved = await graph.aget_state(config(run_id))
        assert saved.next == ('human_approval',)
        result = await graph.ainvoke(Command(resume=approval.model_dump()), config(run_id))
        assert result['result']['requirements'][0]['text'] == 'Show the product selected by the user.'
        assert result['result']['approved_at']
        assert result['result']['framework'] == 'LangGraph'
        assert result['result']['approved_understanding']['user_edits']
        assert model.reg_calls > 0


@pytest.mark.asyncio
async def test_no_fake_fallback_and_no_source_tampering(tmp_path):
    class MockModel(FakeRouter):
        provider_name = 'mock'
    async with stored_graph(llm=MockModel(), database=tmp_path / 'mock.sqlite') as graph:
        with pytest.raises(ValueError, match='real configured model'):
            await graph.ainvoke({'input': QAInput(modules=[module()]).model_dump()}, config(str(uuid4())))
    async with stored_graph(llm=FakeRouter(), database=tmp_path / 'valid.sqlite') as graph:
        result = await graph.ainvoke({'input': QAInput(modules=[module()]).model_dump()}, config(str(uuid4())))
    analysis = result['analysis']
    approval = Approval(approved=True, requirements=analysis['requirements'], navigation=analysis['navigation'], strategy=analysis['strategy'])
    approval.requirements.requirements[0].source_quote = 'Invented business rule'
    with pytest.raises(ValueError, match='source citations'):
        validate_approval(analysis, approval)


@pytest.mark.asyncio
async def test_failed_model_is_error_without_drafts(tmp_path):
    class FailingModel(FakeRouter):
        async def complete(self, req):
            raise ValueError('Model unavailable')
    async with stored_graph(llm=FailingModel(), database=tmp_path / 'failed.sqlite') as graph:
        cfg = config(str(uuid4()))
        with pytest.raises(ValueError, match='Model unavailable'):
            await graph.ainvoke({'input': QAInput(modules=[module()]).model_dump()}, cfg)
        assert not (await graph.aget_state(cfg)).values.get('result')


def test_api_analysis_approval_and_duplicate_resume(tmp_path, monkeypatch):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import qa
    from app.qa import pipeline, workflow
    monkeypatch.setattr(workflow, 'DATABASE', tmp_path / 'api.sqlite')
    monkeypatch.setattr(qa, 'qa_live_configured', lambda: True)
    monkeypatch.setattr(pipeline, 'LLMRouter', lambda model: FakeRouter())
    app = FastAPI(); app.include_router(qa.router)
    with TestClient(app) as client:
        response = client.post('/api/qa/generate/stream', json={'modules': [module()]})
        rows = [json.loads(line) for line in response.text.splitlines()]
        pending = rows[-1]['result']
        assert pending['status'] == 'awaiting_approval'
        assert all(row.get('agent') not in ('Smoke designer', 'Regression designer') for row in rows)
        run_id = pending['run_id']
        assert client.get(f'/api/qa/runs/{run_id}').json()['status'] == 'awaiting_approval'
        assert client.post(f'/api/qa/runs/{run_id}/retry/stream').status_code == 422
        analysis = pending['analysis']
        payload = {'approved': True, 'requirements': analysis['requirements'], 'navigation': analysis['navigation'], 'strategy': analysis['strategy']}
        denied = client.post(f'/api/qa/runs/{run_id}/approve/stream', json={**payload, 'approved': False})
        assert denied.status_code == 422
        response = client.post(f'/api/qa/runs/{run_id}/approve/stream', json=payload)
        rows = [json.loads(line) for line in response.text.splitlines()]
        assert rows[-1]['result']['status'] == 'complete'
        assert rows[-1]['result']['result']['cases']
        assert client.post(f'/api/qa/runs/{run_id}/approve/stream', json=payload).status_code == 422
        assert client.post(f'/api/qa/runs/{run_id}/retry/stream').status_code == 422


@pytest.mark.asyncio
async def test_retry_uses_previous_approval_without_reanalysis(tmp_path, monkeypatch):
    from app.qa import workflow, pipeline
    monkeypatch.setattr(workflow, 'DATABASE', tmp_path / 'retry.sqlite')
    run_id = str(uuid4())
    async with stored_graph(llm=FakeRouter(invalid=True)) as graph:
        result = await graph.ainvoke({'input': QAInput(modules=[module()]).model_dump()}, config(run_id))
        analysis = result['analysis']
        approval = {'approved': True, 'requirements': analysis['requirements'], 'navigation': analysis['navigation'], 'strategy': analysis['strategy']}
        with pytest.raises(ValueError, match='unknown requirement'):
            await graph.ainvoke(Command(resume=approval), config(run_id))
        approved_at = (await graph.aget_state(config(run_id))).values['approved_at']
    monkeypatch.setattr(pipeline, 'LLMRouter', lambda model: FakeRouter())
    events = []
    async def emit(e): events.append(e)
    result = await workflow.retry(run_id, emit)
    assert result['status'] == 'complete'
    assert result['result']['approved_at'] == approved_at
    assert not any(e['agent'] in ('QA supervisor', 'Requirements analyst') for e in events)
