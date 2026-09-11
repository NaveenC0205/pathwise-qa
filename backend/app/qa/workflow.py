"""Durable LangGraph workflow. No production fixture or template execution path."""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict, Literal
from uuid import uuid4, UUID

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field

from app.config import ROOT
from .models import StrictModel, QAInput, Requirements, Navigation, Strategy
from .pipeline import run_plan, noop
from .coverage import validate_references

DATABASE = Path(os.environ['QA_CHECKPOINT_DB']) if os.environ.get('QA_CHECKPOINT_DB') else (
    Path('/tmp/pathwise-qa/agent-checkpoints.sqlite') if os.environ.get('VERCEL') else ROOT / 'outputs' / 'agent-checkpoints.sqlite'
)
_locks = {}


class Approval(StrictModel):
    approved: Literal[True]
    requirements: Requirements
    navigation: Navigation
    strategy: Strategy
    notes: str = Field(default='', max_length=10000)
    input: dict = Field(default_factory=dict)
    analysis: dict = Field(default_factory=dict)


class State(TypedDict, total=False):
    input: dict
    analysis: dict
    approved_analysis: dict
    approved_at: str
    result: dict


def validate_approval(analysis, approval):
    """Edits may change interpretation, never fabricate the original source citation."""
    old = {r['id']: r for r in analysis['requirements']['requirements']}
    new = approval.requirements.requirements
    if len(new) != len(old) or {r.id for r in new} != set(old):
        raise ValueError('Keep requirement IDs intact. Change source inputs and reanalyze to add or remove requirements.')
    for r in new:
        for key in ('module', 'source', 'source_quote', 'evidence_ids'):
            if getattr(r, key) != old[r.id].get(key, []):
                raise ValueError('Original source citations cannot be edited. Edit the interpretation or reanalyze the sources.')
        if 'Functional' not in r.required_types:
            raise ValueError('Every requirement must retain functional coverage.')
    names = {m['module'] for m in analysis['strategy']['modules']}
    if {m.module for m in approval.strategy.modules} != names or len(approval.strategy.modules) != len(names):
        raise ValueError('The strategy must include each analyzed module exactly once.')
    if any(e.module not in names for e in approval.navigation.edges):
        raise ValueError('Navigation must belong to an analyzed module.')
    validate_references(new, approval.navigation, [], analysis['evidence'])


def build_graph(checkpointer, emit=noop, llm=None):
    async def analyze(state):
        body = QAInput.model_validate(state['input'])
        if body.mode != 'live':
            raise ValueError('This workflow requires a live model. Offline generation is disabled.')
        analysis = await run_plan(body, emit, llm)
        return {'analysis': analysis}

    def approval_gate(state):
        answer = interrupt({'kind': 'understanding_approval', 'analysis': state['analysis']})
        approval = Approval.model_validate(answer)
        validate_approval(state['analysis'], approval)
        analysis = dict(state['analysis'])
        analysis.update(requirements=approval.requirements.model_dump(),
                        navigation=approval.navigation.model_dump(), strategy=approval.strategy.model_dump())
        originals = {r['id']: r for r in state['analysis']['requirements']['requirements']}
        analysis['user_edits'] = [{'requirement_id': r.id, 'original': originals[r.id]['text'], 'approved': r.text}
                                 for r in approval.requirements.requirements if r.text != originals[r.id]['text']]
        analysis['approval_notes'] = approval.notes
        analysis['context'] = {**analysis['context'], 'approval_notes': approval.notes,
                               'instruction': 'Use the approved interpretation and strategy. User corrections override earlier interpretations. Unresolved questions remain gaps; do not invent answers.'}
        return {'approved_analysis': analysis, 'approved_at': datetime.now(timezone.utc).isoformat()}

    async def generate(state):
        result = await run_plan(QAInput.model_validate(state['input']), emit, llm,
                                approved=state['approved_analysis'])
        result.update(framework='LangGraph', approved_at=state['approved_at'],
                      approved_understanding=state['approved_analysis'])
        return {'result': result}

    graph = StateGraph(State)
    graph.add_node('source_and_navigation_analysis', analyze)
    graph.add_node('human_approval', approval_gate)
    graph.add_node('suite_design_review_and_documentation', generate)
    graph.add_edge(START, 'source_and_navigation_analysis')
    graph.add_edge('source_and_navigation_analysis', 'human_approval')
    graph.add_edge('human_approval', 'suite_design_review_and_documentation')
    graph.add_edge('suite_design_review_and_documentation', END)
    return graph.compile(checkpointer=checkpointer)


@asynccontextmanager
async def stored_graph(emit=noop, llm=None, database=None):
    path = Path(database or DATABASE)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        yield build_graph(saver, emit, llm)


def config(run_id):
    UUID(run_id)
    return {'configurable': {'thread_id': run_id}}


def public_state(run_id, snapshot):
    values = snapshot.values
    if not values:
        raise ValueError('Saved run was not found.')
    if values.get('result'):
        return {'run_id': run_id, 'status': 'complete', 'result': values['result'], 'input': values['input']}
    return {'run_id': run_id, 'status': 'awaiting_approval' if snapshot.next == ('human_approval',) else 'interrupted',
            'analysis': values.get('analysis'), 'input': values['input'], 'framework': 'LangGraph',
            'can_retry': snapshot.next == ('suite_design_review_and_documentation',) and bool(values.get('approved_at'))}


async def start(body, emit=noop):
    run_id = str(uuid4())
    await emit({'agent': 'Workflow', 'status': 'Running', 'detail': 'Starting saved LangGraph run.', 'run_id': run_id})
    async with stored_graph(emit) as graph:
        await graph.ainvoke({'input': body.model_dump()}, config(run_id))
        return public_state(run_id, await graph.aget_state(config(run_id)))


async def read(run_id):
    async with stored_graph() as graph:
        return public_state(run_id, await graph.aget_state(config(run_id)))


async def resume(run_id, approval, emit=noop):
    # The local app uses one API worker; serialize double-clicks and duplicate requests.
    lock = _locks.setdefault(run_id, asyncio.Lock())
    if lock.locked():
        raise ValueError('This run is already generating test cases.')
    async with lock:
        async with stored_graph(emit) as graph:
            snapshot = await graph.aget_state(config(run_id))
            if snapshot.next == ('human_approval',):
                validate_approval(snapshot.values['analysis'], approval)
                await graph.ainvoke(Command(resume=approval.model_dump(exclude={'input', 'analysis'})), config(run_id))
                return public_state(run_id, await graph.aget_state(config(run_id)))
            if snapshot.values:
                raise ValueError('This run is not awaiting approval. Start a new analysis if inputs changed.')
        if approval.analysis and approval.input:
            return await generate_approved(run_id, approval, emit)
        raise ValueError('This run is not awaiting approval. Start a new analysis if inputs changed.')


async def generate_approved(run_id, approval, emit=noop):
    """Continue suite design when the serverless isolate no longer has the checkpoint."""
    UUID(run_id)
    validate_approval(approval.analysis, approval)
    analysis = dict(approval.analysis)
    analysis.update(requirements=approval.requirements.model_dump(),
                    navigation=approval.navigation.model_dump(), strategy=approval.strategy.model_dump())
    originals = {r['id']: r for r in approval.analysis['requirements']['requirements']}
    analysis['user_edits'] = [{'requirement_id': r.id, 'original': originals[r.id]['text'], 'approved': r.text}
                             for r in approval.requirements.requirements if r.text != originals[r.id]['text']]
    analysis['approval_notes'] = approval.notes
    analysis['context'] = {**analysis['context'], 'approval_notes': approval.notes,
                           'instruction': 'Use the approved interpretation and strategy. User corrections override earlier interpretations. Unresolved questions remain gaps; do not invent answers.'}
    approved_at = datetime.now(timezone.utc).isoformat()
    result = await run_plan(QAInput.model_validate(approval.input), emit, approved=analysis)
    result.update(framework='LangGraph', approved_at=approved_at, approved_understanding=analysis)
    return {'run_id': run_id, 'status': 'complete', 'result': result, 'input': approval.input}


async def retry(run_id, emit=noop):
    lock = _locks.setdefault(run_id, asyncio.Lock())
    if lock.locked():
        raise ValueError('This run is already generating test cases.')
    async with lock:
        async with stored_graph(emit) as graph:
            snapshot = await graph.aget_state(config(run_id))
            if not public_state(run_id, snapshot).get('can_retry'):
                raise ValueError('Only an interrupted, previously approved generation can be retried.')
            await graph.ainvoke(None, config(run_id))
            return public_state(run_id, await graph.aget_state(config(run_id)))
