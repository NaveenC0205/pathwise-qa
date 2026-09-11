"""Deterministic obligations: counted separately from semantic agent review."""
from .manual import boundary_min_cases
from .models import Finding


def validate_references(requirements, navigation, cases, evidence):
    sets = {'requirement': {r.id for r in requirements}, 'edge': {e.id for e in navigation.edges}, 'journey': {j.id for j in navigation.journeys}, 'evidence': {e['id'] for e in evidence}}
    for label, rows in [('requirement', requirements), ('edge', navigation.edges), ('journey', navigation.journeys), ('case', cases)]:
        if len({row.id for row in rows}) != len(rows):
            raise ValueError(f'Duplicate {label} IDs')
    edge_map = {e.id: e for e in navigation.edges}
    for journey in navigation.journeys:
        if set(journey.edge_ids) - sets['edge']:
            raise ValueError('Journey references unknown edges')
        chain = [edge_map[i] for i in journey.edge_ids]
        if any(a.destination != b.origin for a, b in zip(chain, chain[1:])):
            raise ValueError('Journey edges must form an ordered, connected path')
    for row in [*requirements, *navigation.edges]:
        if set(row.evidence_ids) - sets['evidence']:
            raise ValueError('Unknown evidence reference')
    for c in cases:
        for label in sets:
            if set(getattr(c, label + '_ids')) - sets[label]:
                raise ValueError(f'Case references unknown {label} IDs')
        for jid in c.journey_ids:
            chain = next(j.edge_ids for j in navigation.journeys if j.id == jid)
            # A case cannot claim a journey without its entire ordered path.
            indices = [c.edge_ids.index(e) for e in chain if e in c.edge_ids]
            if len(indices) != len(chain) or indices != sorted(indices):
                raise ValueError('Case claims a journey without its ordered edges')
        if c.assumptions and c.status != 'Needs clarification':
            raise ValueError('Cases with assumptions must be marked Needs clarification')
        if not c.requirement_ids and not c.edge_ids:
            raise ValueError(f'{c.id} ({c.name}) has no requirement_ids or edge_ids. Link the actual tested source IDs or omit this unsupported scenario.')


def coverage_report(requirements, navigation, cases):
    obligations = []
    def add(key, module, suite, target, typ, matches, min_cases=1):
        obligations.append({'id': key, 'module': module, 'suite': suite, 'target_id': target, 'testing_type': typ, 'case_ids': [c.id for c in matches], 'status': 'Linked' if len(matches) >= min_cases else 'Missing', 'needs_clarification': any(c.status == 'Needs clarification' for c in matches)})
    for r in requirements:
        for typ in dict.fromkeys(r.required_types):
            matches = [c for c in cases if c.suite == 'Regression' and r.id in c.requirement_ids and c.testing_type == typ]
            add(f'{r.id}:{typ}', r.module, 'Regression', r.id, typ, matches, min_cases=boundary_min_cases(r.text) if typ == 'Boundary' else 1)
        if r.critical:
            add(f'Smoke:{r.id}', r.module, 'Smoke', r.id, 'Functional', [c for c in cases if c.suite == 'Smoke' and r.id in c.requirement_ids])
    for e in navigation.edges:
        add(f'{e.id}:Navigation', e.module, 'Regression', e.id, 'Navigation', [c for c in cases if c.suite == 'Regression' and e.id in c.edge_ids and c.testing_type == 'Navigation'])
    for j in navigation.journeys:
        if j.critical:
            add(f'Smoke:{j.id}', j.module, 'Smoke', j.id, 'E2E', [c for c in cases if c.suite == 'Smoke' and c.level == 'E2E' and j.id in c.journey_ids])
    missing = [o for o in obligations if o['status'] == 'Missing']
    modules = []
    for name in dict.fromkeys(o['module'] for o in obligations):
        subset = [o for o in obligations if o['module'] == name]
        modules.append({'name': name, 'linked': sum(o['status'] == 'Linked' for o in subset), 'total': len(subset), 'smoke': sum(c.suite == 'Smoke' and c.module == name for c in cases), 'regression': sum(c.suite == 'Regression' and c.module == name for c in cases)})
    return {'linked': len(obligations) - len(missing), 'total': len(obligations), 'missing': len(missing), 'obligations': obligations, 'modules': modules, 'smoke': sum(c.suite == 'Smoke' for c in cases), 'regression': sum(c.suite == 'Regression' for c in cases), 'clarifications': sum(c.status == 'Needs clarification' for c in cases)}


def missing_findings(report):
    return [Finding(id='COV-' + o['id'], severity='Major', owner=o['suite'] + ' designer', description=f"Missing {o['suite']} {o['testing_type']} case for {o['target_id']} in {o['module']}.", target_ids=[o['target_id']]) for o in report['obligations'] if o['status'] == 'Missing']
