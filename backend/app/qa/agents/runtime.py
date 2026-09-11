"""Each specialist executes a LangGraph reasoning/validation/correction loop."""
import json
import re
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from app.llm import CompletionRequest
from .base import BASE


class AgentState(TypedDict, total=False):
    attempt: int
    output: str
    problem: str
    parsed: dict
    model: str


async def invoke_specialist(team, name, instructions, schema, context, validate, role):
    async def reason(state):
        payload = {'schema': schema.model_json_schema(), 'context': context}
        if state.get('problem'):
            payload.update(correction='Correct this validation failure: ' + state['problem'],
                           previous_output=state['output'])
        completion = await team.llm.complete(CompletionRequest(
            system=BASE + '\n' + instructions, prompt=json.dumps(payload),
            max_tokens=14000 if schema.__name__ == 'Cases' else 9000, purpose='qa_' + name))
        if completion.provider.startswith(('mock', 'offline')):
            raise ValueError('A mock fallback cannot fulfill a live QA agent run.')
        return {'output': completion.text, 'model': completion.model,
                'attempt': state.get('attempt', 0) + 1}

    async def validate_output(state):
        try:
            raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', state['output'].strip())
            parsed = schema.model_validate_json(raw)
            if validate:
                validate(parsed)
            await team.event(role, 'Running' if name == 'Browser decision' else 'Complete',
                             f"Validated response · {state['model']}", model=state['model'])
            return {'parsed': parsed.model_dump(), 'problem': ''}
        except ValueError as exc:
            if state['attempt'] >= 2:
                raise ValueError(f'{name} returned invalid output after correction: {str(exc)[:220]}') from exc
            await team.event(role, 'Repairing', 'Correcting invalid output or source references.')
            return {'problem': str(exc)[:2400]}

    graph = StateGraph(AgentState)
    graph.add_node('reason_with_live_model', reason)
    graph.add_node('validate_evidence_and_structure', validate_output)
    graph.add_edge(START, 'reason_with_live_model')
    graph.add_edge('reason_with_live_model', 'validate_evidence_and_structure')
    graph.add_conditional_edges('validate_evidence_and_structure',
                                lambda s: 'correct' if s.get('problem') else 'done',
                                {'correct': 'reason_with_live_model', 'done': END})
    # Agent-local state is transient; the parent workflow checkpoints completed stages.
    result = await graph.compile(checkpointer=False).ainvoke({'attempt': 0})
    return schema.model_validate(result['parsed'])
