"""Transparent offline fixtures. Never impersonates live model reasoning."""
import re
from .manual import infer_types
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
            types = infer_types(line)
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
        cases.append(Case(id=f"{'SMK' if suite == 'Smoke' else 'REG'}-{num:03}", role='Role from source; confirm test account', evidence_ids=[], status='Needs clarification', **kw))
    def scenario(r, typ, name, action, expected, data, assumption):
        add(name=f'{r.module} — {name}'[:100], description=f'Manual {typ.lower()} check for source requirement {r.id}: {r.text}', module=r.module, suite='Regression', testing_type=typ, priority='P1' if r.critical else 'P2', level='Module', preconditions=[f'Start on the {r.module} screen with a known valid fixture.', 'No other tester is changing the same record.'], test_data=data, steps=[Step(action=action, expected_result=expected)], expected_result=expected, requirement_ids=[r.id], edge_ids=[], journey_ids=[], assumptions=[assumption])
    for r in reqs.requirements:
        for typ in r.required_types:
            if typ == 'Functional':
                scenario(r, typ, f'happy path: {r.text[:70]}', f'On the {r.module} screen, complete the documented happy path using valid data for: {r.text}', f'The {r.module} screen shows the documented success state. Required values remain visible and the primary action completes.', ['Valid fixture that satisfies the source prerequisites.'], 'Confirm the exact control names and success message before execution.')
            elif typ == 'Negative':
                scenario(r, typ, f'invalid or missing input: {r.text[:55]}', f'On the {r.module} screen, attempt the action with one invalid or missing required value from: {r.text}', 'The invalid change is rejected. The previous valid state is unchanged. A validation state is shown if the source specifies one.', ['One invalid or blank value for a required field in the source.'], 'Confirm the exact invalid input and validation message with the product.')
            elif typ == 'Boundary':
                numbers = list(dict.fromkeys(re.findall(r'\b\d+(?:\.\d+)?\b', r.text)))
                parsed = []
                for raw in numbers:
                    parsed.append(int(raw) if re.fullmatch(r'\d+', raw) else float(raw))
                if len(parsed) >= 2:
                    low, high = min(parsed), max(parsed)
                    edges = [(low, 'minimum valid'), (high, 'maximum valid')]
                    if all(isinstance(n, int) for n in (low, high)):
                        edges += [(low - 1, 'just below minimum'), (high + 1, 'just above maximum')]
                elif parsed:
                    value = parsed[0]
                    edges = [(value, 'stated limit')]
                    if isinstance(value, int):
                        edges += [(value - 1, 'just below stated limit'), (value + 1, 'just above stated limit')]
                else:
                    edges = []
                for value, label in edges:
                    accepted = 'below' not in label and 'above' not in label
                    scenario(r, typ, f'{label} {value}', f'On the {r.module} screen, enter {value} ({label}) and attempt to continue.', f'{value} is accepted and the flow continues.' if accepted else f'{value} is rejected. The previous valid value remains. No unintended record is created.', [f'{label}: {value}'], 'Confirm whether the documented limit is inclusive and the exact validation text.')
                scenario(r, typ, 'empty or cleared field', f'On the {r.module} screen, clear the constrained field and attempt to continue.', 'Blank input is rejected or the field is restored to a valid value. The previous valid state is unchanged.', ['Empty / cleared field'], 'Confirm required-vs-optional behavior if the source does not state it.')
            elif typ == 'Security':
                scenario(r, typ, f'unauthorized role: {r.text[:60]}', f'Attempt the {r.module} action as a restricted or unsigned-in role: {r.text}', 'The restricted role cannot complete the action or see the restricted data. The authorized role still can.', ['Permitted role and restricted/guest role'], 'Confirm the exact roles and denied-state presentation.')
            elif typ == 'Recovery':
                scenario(r, typ, f'failure and retry: {r.text[:60]}', f'On the {r.module} screen, reproduce the documented failure, then use the retry/continue control: {r.text}', 'The documented recovery succeeds. No extra record is created. The user can continue from a consistent state.', ['A fixture that can trigger the documented failure once'], 'Confirm the failure injection method and retry assertion.')
            elif typ == 'State':
                scenario(r, typ, f'leave and return: {r.text[:60]}', f'Change the documented {r.module} state, navigate away or refresh, then return: {r.text}', 'The documented state is preserved or reset exactly as the source requires.', ['A changed in-progress record'], 'Confirm back, refresh and timeout behavior if unspecified.')
            elif typ == 'Navigation':
                scenario(r, typ, f'navigation: {r.text[:70]}', f'Follow the documented navigation for: {r.text}', 'The expected screen opens with its initial state.', ['Known starting screen from the source'], 'Confirm the control, route and role for this transition.')
            else:
                scenario(r, typ, f'{typ.lower()}: {r.text[:70]}', f'On the {r.module} screen, exercise the {typ.lower()} obligation: {r.text}', f'The observable {typ.lower()} outcome from the source is met.', ['Fixture that meets the source prerequisites.'], 'Confirm concrete controls and pass/fail assertions before execution.')
        if r.critical:
            add(name=f'{r.module} — smoke walk: {r.text[:70]}', description=f'Manual smoke walk of critical requirement {r.id}.', module=r.module, suite='Smoke', testing_type='Functional', priority='P0', level='Module', preconditions=[f'Start the release smoke pass on {r.module} with a valid account.'], test_data=['Valid happy-path fixture'], steps=[Step(action=f'Walk the documented happy path: {r.text}', expected_result=f'The critical {r.module} success state is visible and the tester can continue.')], expected_result=f'The critical criterion holds: {r.text}', requirement_ids=[r.id], edge_ids=[], journey_ids=[], assumptions=['Confirm controls and accounts used on the smoke pass.'])
    for e in nav.edges:
        add(name=f'{e.origin} to {e.destination} — navigation', description=f'Manual navigation check for {e.id}.', module=e.module, suite='Regression', testing_type='Navigation', priority='P2', level='Module', preconditions=[f'The tester is on {e.origin} with the documented role.'], test_data=['Known record that can open this transition'], steps=[Step(action=e.action, expected_result=f'{e.destination} opens. The tester can see the expected starting state.')], expected_result=f'The tester reaches {e.destination}.', requirement_ids=[], edge_ids=[e.id], journey_ids=[], assumptions=['Confirm exact navigation control, route, role, and destination assertions.'])
    for j in nav.journeys:
        if not j.critical: continue
        edges = [next(e for e in nav.edges if e.id == eid) for eid in j.edge_ids]
        add(name=f'Critical E2E — {j.name}', description='Manual smoke walk of the complete primary journey from entry to final destination.', module=j.module, suite='Smoke', testing_type='Functional', priority='P0', level='E2E', preconditions=[f'Start at {edges[0].origin} with valid test data.'], test_data=['Happy-path fixture for the full journey'], steps=[Step(action=e.action, expected_result=f'{e.destination} opens. Confirm the required fields and primary action on that screen.') for e in edges], expected_result=f'The tester reaches {edges[-1].destination} with the documented success state.', requirement_ids=[], edge_ids=j.edge_ids, journey_ids=[j.id], assumptions=['Confirm controls, prerequisites, and business assertions for each transition; this template has not visited the UI.'])
    return reqs, nav, cases
