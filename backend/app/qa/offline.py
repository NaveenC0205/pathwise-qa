"""Transparent offline fixtures. Never impersonates live model reasoning."""
import re
from .models import Requirement, Requirements, Edge, Journey, Navigation, Case, Step


def analyze(body):
    requirements = []
    for source in ('story', 'success_criteria', 'confluence', 'figma'):
        module = 'General'
        for raw in getattr(body, source).splitlines():
            line = raw.strip()
            if not line or re.fullmatch(r'https?://\S+', line):
                continue
            if line.startswith('#'):
                module = line.lstrip('# ').strip() or module
                continue
            match = re.match(r'\[([^\]]+)\]\s*(.*)', line)
            if match:
                module, line = match.groups()
            elif module == 'General':
                for word in ('cart', 'checkout', 'payment', 'login', 'sign in', 'product', 'order'):
                    if word in line.lower():
                        module = word.title(); break
            types = ['Functional']
            if re.search(r'requir|invalid|must|cannot|only|denied', line, re.I): types.append('Negative')
            if re.search(r'\d', line): types.append('Boundary')
            if re.search(r'role|guest|sign in|permission|admin', line, re.I): types.append('Security')
            if re.search(r'fail|retry|error', line, re.I): types.append('Recovery')
            if re.search(r'preserv|retain|duplicate|reset', line, re.I): types.append('State')
            requirements.append(Requirement(id=f'R{len(requirements)+1:03}', module=module, text=line, source=source, source_quote=line, critical=source == 'story', required_types=types, rationale='Offline keyword classification; review applicability.'))
    if not requirements or len(requirements) > 100:
        raise ValueError('Use 1–100 requirement lines per offline run.')
    edges, journeys = [], []
    for raw in body.navigation.splitlines():
        parts = [x.strip() for x in re.split(r'\s*(?:->|→)\s*', raw) if x.strip()]
        ids = []
        for a, b in zip(parts, parts[1:]):
            edge = next((e for e in edges if e.origin == a and e.destination == b), None)
            if not edge:
                edge = Edge(id=f'N{len(edges)+1:03}', module=a, origin=a, destination=b, action=f'Open {b} from {a}', condition='Confirm role and route prerequisites.')
                edges.append(edge)
            ids.append(edge.id)
        if ids:
            journeys.append(Journey(id=f'J{len(journeys)+1:03}', name=' → '.join(parts), module=parts[0], edge_ids=ids, critical=len(journeys) == 0))
    nav = Navigation(edges=edges, journeys=journeys, questions=[] if edges else ['No explicit navigation supplied. E2E paths cannot be inferred by offline templates.'])
    return Requirements(requirements=requirements, questions=['Offline classifications and scenarios require QA review.']), nav


def draft(body):
    if body.modules:
        from .models import QAInput
        all_reqs, all_edges, all_journeys, all_cases, questions = [], [], [], [], []
        for index, module in enumerate(body.modules, 1):
            child = QAInput(**module.model_dump(include={'story', 'success_criteria', 'navigation', 'confluence', 'figma'}), mode='offline')
            reqs, nav, cases = draft(child)
            prefix = f'M{index}-'
            for row in [*reqs.requirements, *nav.edges, *nav.journeys, *cases]:
                row.id = prefix + row.id
                row.module = module.name
            for journey in nav.journeys: journey.edge_ids = [prefix + x for x in journey.edge_ids]
            for case in cases:
                case.requirement_ids = [prefix + x for x in case.requirement_ids]
                case.edge_ids = [prefix + x for x in case.edge_ids]
                case.journey_ids = [prefix + x for x in case.journey_ids]
            all_reqs.extend(reqs.requirements); all_edges.extend(nav.edges); all_journeys.extend(nav.journeys); all_cases.extend(cases)
            questions.extend(f'{module.name}: {q}' for q in reqs.questions + nav.questions)
        return Requirements(requirements=all_reqs, questions=questions), Navigation(edges=all_edges, journeys=all_journeys), all_cases
    reqs, nav = analyze(body)
    cases = []
    def add(**kw):
        suite = kw['suite']; num = sum(c.suite == suite for c in cases) + 1
        cases.append(Case(id=f"{'SMK' if suite == 'Smoke' else 'REG'}-{num:03}", role='Role from source; confirm test account', test_data=['Use an isolated test fixture that meets the source prerequisites.'], evidence_ids=[], status='Needs clarification', **kw))
    for r in reqs.requirements:
        variants = [('Regression', typ) for typ in r.required_types] + ([('Smoke', 'Functional')] if r.critical else [])
        for suite, typ in variants:
            action = f'Exercise the stated behavior: {r.text}'
            expected = f'Confirm the source criterion: {r.text}'
            assumption = 'Confirm concrete controls, fixtures, and observable pass/fail assertions before execution.'
            if typ == 'Negative':
                action = f'Violate one prerequisite in: {r.text}'
                expected = 'The invalid operation is rejected; verify the specified validation state and no unintended change.'
                assumption = 'The exact invalid input and validation message need product confirmation.'
            elif typ == 'Boundary':
                numbers = re.findall(r'\b\d+(?:\.\d+)?\b', r.text)
                action = f'Test the stated limit(s) {", ".join(numbers)} and adjacent valid/invalid values separately.'
                expected = 'Each value is accepted or rejected according to the documented inclusive/exclusive limit.'
                assumption = 'Split each boundary into separate executable cases; confirm units and inclusive limits.'
            elif typ == 'Security':
                action = f'Exercise the rule using both permitted and restricted test roles: {r.text}'
                expected = 'Only the authorized role can perform the stated operation; the restricted role cannot bypass it.'
            elif typ == 'Recovery':
                action = f'Reproduce the documented failure and retry behavior: {r.text}'
                expected = 'The documented recovery succeeds without additional unintended state changes.'
            elif typ == 'State':
                action = f'Change the documented state, leave the screen, and return: {r.text}'
                expected = r.text
            add(name=f'{r.module} — {typ.lower()}: {r.text[:85]}', description=f'Validate the {typ.lower()} obligation for source requirement {r.id}.', module=r.module, suite=suite, testing_type=typ, priority='P1' if r.critical else 'P2', level='Module', preconditions=[f'Open the {r.module} module.', 'Prepare the documented account and initial application state.'], steps=[Step(action=action, expected_result=expected)], expected_result=expected, requirement_ids=[r.id], edge_ids=[], journey_ids=[], assumptions=[assumption])
    for e in nav.edges:
        add(name=f'{e.origin} to {e.destination} — navigation', description=f'Validate the documented directed transition {e.id}.', module=e.module, suite='Regression', testing_type='Navigation', priority='P2', level='Module', preconditions=[f'User is on {e.origin}.'], steps=[Step(action=e.action, expected_result=f'{e.destination} is displayed with the expected route and initial state.')], expected_result=f'The user reaches {e.destination}.', requirement_ids=[], edge_ids=[e.id], journey_ids=[], assumptions=['Confirm exact navigation control, route, role, and destination assertions.'])
    for j in nav.journeys:
        if not j.critical: continue
        edges = [next(e for e in nav.edges if e.id == eid) for eid in j.edge_ids]
        add(name=f'Critical E2E — {j.name}', description='Smoke check of the complete supplied primary journey from entry to final destination.', module=j.module, suite='Smoke', testing_type='Functional', priority='P0', level='E2E', preconditions=[f'Start at {edges[0].origin} with valid test data.'], steps=[Step(action=e.action, expected_result=f'{e.destination} opens; verify its required screen state.') for e in edges], expected_result=f'The journey reaches {edges[-1].destination}.', requirement_ids=[], edge_ids=j.edge_ids, journey_ids=[j.id], assumptions=['Confirm controls, prerequisites, and business assertions for each transition; this template has not visited the UI.'])
    return reqs, nav, cases
