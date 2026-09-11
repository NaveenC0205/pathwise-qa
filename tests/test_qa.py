import io
import json
import zipfile
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.qa import QAInput, router
from app.qa.pipeline import run_plan
from app.qa.workflow import build_graph
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command


async def approved_run(body, emit=None, llm=None):
    from app.qa.pipeline import noop
    graph = build_graph(InMemorySaver(), emit or noop, llm)
    cfg = {'configurable': {'thread_id': 'test'}}
    state = await graph.ainvoke({'input': body.model_dump()}, cfg)
    analysis = state['analysis']
    return (await graph.ainvoke(Command(resume={'approved': True, 'requirements': analysis['requirements'], 'navigation': analysis['navigation'], 'strategy': analysis['strategy']}), cfg))['result']
from app.qa.models import Case, ModuleInput, Requirements, Requirement
from app.qa.imports import import_cases
from app.qa.browser import candidates, check_target
from app.qa.manual import infer_types, implied_types, boundary_min_cases
from app.qa.pipeline import check_sources


def module(name='Catalog', story='Users can open a product.'):
    return {'id': name, 'name': name, 'story': story, 'success_criteria': 'The selected product details are displayed.', 'navigation': 'Home → Product'}


@pytest.mark.asyncio
async def test_modules_stay_separate_with_step_results_and_smoke_paths():
    result = await run_plan(QAInput(modules=[module(), module('Orders', 'Users can view orders.')], mode='offline'))
    assert {r['module'] for r in result['requirements']} == {'Catalog', 'Orders'}
    assert {r['source'] for r in result['requirements']} == {'story', 'success_criteria'}
    assert len({c['id'] for c in result['cases']}) == len(result['cases'])
    assert all(s['action'] and s['expected_result'] for c in result['cases'] for s in c['steps'])
    assert {c['suite'] for c in result['cases']} == {'Smoke', 'Regression'}
    assert any(c['level'] == 'E2E' and c['journey_ids'] for c in result['cases'])
    assert result['coverage']['missing'] == 0
    assert result['coverage']['clarifications'] == len(result['cases'])
    assert result['execution_status'] == 'Not executed'


@pytest.mark.asyncio
async def test_no_navigation_does_not_claim_e2e():
    result = await run_plan(QAInput(story='Users can sign in.', figma='https://figma.com/design/example', mode='offline'))
    assert not result['edges']
    assert not any(c['level'] == 'E2E' for c in result['cases'])
    assert any('not fetched' in g for g in result['gaps'])


def test_module_validation():
    with pytest.raises(ValueError): QAInput(modules=[module(), module()])
    with pytest.raises(ValueError): QAInput(modules=[{**module(), 'story': ''}])
    with pytest.raises(ValueError): QAInput(story='Valid story text', explore_ui=True, target_url='http://example.com', mode='offline')


def test_manual_tester_infers_negative_and_boundary_types():
    text = 'Quantity must be between 1 and 10.'
    assert infer_types(text) == ['Functional', 'Negative', 'Boundary']
    assert implied_types(text, ['Functional']) == ['Negative', 'Boundary']
    assert boundary_min_cases(text) == 2
    assert infer_types('Users can open a product.') == ['Functional']


def test_requirements_must_include_implied_edge_types():
    body = QAInput(modules=[{**module('Cart', 'Shopper can update cart quantity.'), 'success_criteria': 'Quantity must be between 1 and 10.'}])
    reqs = Requirements(requirements=[Requirement(id='R1', module='Cart', text='Quantity limits', source='success_criteria', source_quote='Quantity must be between 1 and 10.', critical=False, required_types=['Functional'], rationale='Happy path only.')])
    with pytest.raises(ValueError, match='Boundary'):
        check_sources(reqs, body, [])


@pytest.mark.asyncio
async def test_offline_writes_manual_steps_and_split_edge_cases():
    body = QAInput(modules=[{**module('Cart', 'Shopper can update cart quantity.'), 'success_criteria': 'Quantity must be between 1 and 10 inclusive.', 'navigation': 'Product → Cart'}], mode='offline')
    result = await run_plan(body)
    boundary = [c for c in result['cases'] if c['testing_type'] == 'Boundary']
    assert len(boundary) >= 4
    assert any('empty' in c['name'].lower() or 'cleared' in c['name'].lower() for c in boundary)
    assert any(s['action'].startswith('On the ') for c in result['cases'] for s in c['steps'])
    assert all(c['test_data'] for c in result['cases'])
    assert result['coverage']['missing'] == 0


def test_csv_import_mapping_and_formula_exclusion():
    data = b'Module,Test Case Name,Test Steps,Expected Result\nCatalog,Open item,Click item,Details appear\nCart,Quantity,Enter 0,Error shown\nCart,Formula,=HYPERLINK("bad"),Not executed\n'
    result = import_cases(data, 'suite.csv')
    assert result['count'] == 3
    assert result['cases'][1]['module'] == 'Cart'
    assert result['cases'][1]['source_row'] == 3
    assert result['cases'][2]['steps'] == ''
    assert result['warnings']
    assert import_cases(data, 'renamed.csv')['cases'][0]['id'] == result['cases'][0]['id']


def test_bad_import_is_actionable():
    with pytest.raises(ValueError, match='header'): import_cases(b'Unknown,Steps\nOne,Two', 'bad.csv')
    with pytest.raises(ValueError, match='valid XLSX'): import_cases(b'invalid', 'bad.xlsx')
    with pytest.raises(ValueError, match='2 MB'): import_cases(b'x' * 2_000_001, 'large.csv')


def test_xlsx_reader_preserves_rows():
    # Minimal test fixture, not a user-facing workbook artifact.
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Cases" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Test Case Name</t></is></c><c r="B1" t="inlineStr"><is><t>Expected Result</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>Open catalog</t></is></c><c r="B2" t="inlineStr"><is><t>Catalog displays</t></is></c></row></sheetData></worksheet>')
    result = import_cases(data.getvalue(), 'cases.xlsx')
    assert result['cases'][0]['source_sheet'] == 'Cases'
    assert result['cases'][0]['name'] == 'Open catalog'
    assert result['cases'][0]['expected_result'] == 'Catalog displays'


def test_browser_candidates_and_origins(monkeypatch):
    snapshot = '- link "Products" [ref=e1]\n- button "Delete" [ref=e2]\n- button "Pay" [ref=e3]\n- button "Menu" [ref=e4]\n- button "View" [disabled] [ref=e5]'
    assert [x['ref'] for x in candidates(snapshot)] == ['e1', 'e4']
    monkeypatch.setenv('QA_ALLOWED_ORIGINS', 'https://test.example')
    assert check_target('https://test.example/catalog') == 'https://test.example'
    for url in ['file:///etc/passwd', 'http://169.254.169.254/', 'https://evil.example/', 'https://test.example/delete']:
        with pytest.raises(ValueError): check_target(url)


class FakeRouter:
    provider_name = 'fixture-real'
    def __init__(self, invalid=False): self.reg_calls = 0; self.invalid = invalid
    async def complete(self, req):
        from app.llm import Completion
        context = json.loads(req.prompt)['context']
        if req.purpose == 'qa_QA supervisor':
            data = {'modules': [{'module': m['name'], 'priority': 'P1', 'test_focus': ['Core functionality'], 'estimated_case_count': 8} for m in context.get('modules', [])], 'decisions': ['Plan smoke and regression by module.'], 'gaps': []}
        elif req.purpose == 'qa_Test plan writer':
            data = {'title': 'QA plan', 'overview': 'Draft test design plan.', 'scope_in': ['Catalog'], 'scope_out': ['Runtime execution'], 'approach': ['Smoke and regression'], 'environments': ['Test environment'], 'entry_criteria': ['Requirements reviewed'], 'exit_criteria': ['Approved tests pass'], 'risks': ['Incomplete evidence'], 'deliverables': ['Test suites'], 'assumptions': [], 'case_ids': [c['id'] for c in context['cases']]}
        elif req.purpose == 'qa_Requirements analyst':
            data = {'requirements': [{'id': 'R1', 'module': 'Catalog', 'text': 'Open product', 'source': 'story', 'source_quote': 'Users can open a product.', 'critical': True, 'required_types': ['Functional', 'Negative'], 'rationale': 'Valid and unavailable product states.'}], 'questions': []}
        elif req.purpose == 'qa_Figma explorer':
            data = {'edges': [{'id': 'N1', 'module': 'Catalog', 'origin': 'Home', 'destination': 'Product', 'action': 'Click the product', 'condition': ''}], 'journeys': [{'id': 'J1', 'name': 'Open product', 'module': 'Catalog', 'edge_ids': ['N1'], 'critical': True}], 'questions': []}
        elif req.purpose in ('qa_Smoke designer', 'qa_Regression designer'):
            smoke = req.purpose == 'qa_Smoke designer'
            if not smoke: self.reg_calls += 1
            kinds = ['Functional'] if smoke else ['Functional', 'Navigation'] + (['Negative'] if self.reg_calls > 1 else [])
            data = {'cases': [Case(id=f'T{i}', name=f'Open product {typ}', description='Verify that the selected product details appear.', module='Catalog', suite='Smoke' if smoke else 'Regression', testing_type=typ, priority='P1', level='E2E' if smoke else 'Module', role='Guest', preconditions=['Catalog is loaded'], test_data=['Available product P1'], steps=[{'action': 'Click product P1', 'expected_result': 'Product P1 details appear'}], expected_result='Correct product details appear', requirement_ids=['BAD' if self.invalid else 'R1'], edge_ids=['N1'], journey_ids=['J1'] if smoke else [], evidence_ids=[], assumptions=[]).model_dump() for i, typ in enumerate(kinds)]}
        else:
            data = {'findings': [], 'decision': 'Reviewed supplied scope.', 'existing_case_reviews': [{'existing_case_id': c['id'], 'disposition': 'Improve', 'reason': 'Add explicit expected results.'} for c in context.get('existing_test_cases', [])]}
        return Completion(text=json.dumps(data), model='fixture', provider='fixture-real')


@pytest.mark.asyncio
async def test_five_agent_loop_repairs_missing_obligation():
    events = []
    async def emit(e): events.append(e)
    result = await approved_run(QAInput(modules=[module()], mode='live'), emit, FakeRouter())
    assert result['repairs'] == 1
    assert result['review_history'][0]['findings'][0]['id'] == 'COV-R1:Negative'
    assert result['coverage']['missing'] == 0
    assert {e['agent'] for e in events} == {'QA supervisor', 'Requirements analyst', 'Figma explorer', 'Smoke designer', 'Regression designer', 'Coverage reviewer', 'Test plan writer'}
    assert len(result['review_history']) == 2


@pytest.mark.asyncio
async def test_live_rejects_unknown_references():
    with pytest.raises(ValueError, match='unknown requirement'):
        await approved_run(QAInput(modules=[module()], mode='live'), llm=FakeRouter(invalid=True))


@pytest.mark.asyncio
async def test_existing_cases_are_assessed_without_claiming_execution():
    m = module(); m['existing_cases'] = import_cases(b'Name,Steps\nOpen product,Click product', 'prior.csv')['cases']
    result = await approved_run(QAInput(modules=[m], mode='live'), llm=FakeRouter())
    assert result['existing_case_reviews'][0]['disposition'] == 'Improve'
    assert result['existing_cases'][0]['source_row'] == 2


def test_api_stream_and_import():
    app = FastAPI(); app.include_router(router); client = TestClient(app)
    response = client.post('/api/qa/generate/stream', json={'modules': [module()], 'mode': 'offline'})
    assert response.status_code == 422
    assert 'disabled' in response.json()['detail']
    response = client.post('/api/qa/import-cases', files={'file': ('cases.csv', b'Name,Steps,Expected Result\nOpen,Click,Page visible', 'text/csv')})
    assert response.status_code == 200
    assert response.json()['count'] == 1


@pytest.mark.asyncio
async def test_large_suite_and_line_inventory():
    inputs = [module(f'Module {i}', f'Users can open screen {i}.') for i in range(20)]
    for m in inputs:
        m['success_criteria'] = 'A required name is validated.\nQuantity must be between 1 and 10.'
    result = await run_plan(QAInput(modules=inputs, mode='offline'))
    assert len(result['cases']) >= 100
    assert len(result['source_lines']) == 80
    assert len({c['id'] for c in result['cases']}) == len(result['cases'])
    assert result['test_plan']['entry_criteria']


def test_figma_structure_and_urls():
    from app.qa.figma import parse_figma_url, design_lines
    assert parse_figma_url('https://www.figma.com/design/ABC/File?node-id=1-2') == ('ABC', '1:2')
    with pytest.raises(ValueError): parse_figma_url('https://evil.example/design/ABC')
    text, truncated, count = design_lines({'document': {'id':'1','type':'FRAME','name':'Cart','children':[{'id':'2','type':'TEXT','characters':'Checkout','reactions':[{'action':{'destinationId':'3'}}]}]}})
    assert 'Checkout' in text and 'destinationId' in text and count == 2 and not truncated


def test_prototype_buttons_are_simulated_navigation_not_live_mutations():
    snapshot = '- button "Pay" [ref=e1]\n- button "Delete file" [ref=e2]'
    assert candidates(snapshot) == []
    assert [c['ref'] for c in candidates(snapshot, prototype=True)] == ['e1']


@pytest.mark.asyncio
async def test_failed_batch_cancels_parallel_work():
    import asyncio
    from app.qa.pipeline import parallel
    stopped = asyncio.Event()
    async def slow():
        try: await asyncio.sleep(10)
        finally: stopped.set()
    async def fail():
        await asyncio.sleep(0)
        raise ValueError('failed batch')
    with pytest.raises(ValueError): await parallel(slow(), fail())
    assert stopped.is_set()
