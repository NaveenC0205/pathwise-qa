import asyncio
import re
from .models import Requirements, Navigation, Cases, Review, Finding, Strategy, TestPlan
from .agents import AGENTS
from .agents.runtime import invoke_specialist
from .coverage import validate_references, coverage_report, missing_findings
from .offline import draft
from .browser import explore
from .figma import read_design
from .line_coverage import inventory
from .manual import implied_types, MANUAL
from app.llm import LLMRouter

ROLES = ['QA supervisor', 'Requirements analyst', 'Figma explorer', 'Smoke designer', 'Regression designer', 'Coverage reviewer', 'Test plan writer']


async def parallel(*operations):
    tasks = [asyncio.create_task(op) for op in operations]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def noop(event):
    pass


class Team:
    def __init__(self, emit=noop, llm=None):
        self.llm = llm
        self.emit = emit
        self.trace = []
        self.slots = asyncio.Semaphore(2)

    async def event(self, agent, status, detail, **extra):
        row = {'agent': agent, 'status': status, 'detail': detail, **extra}
        self.trace.append(row)
        await self.emit(row)

    async def ask(self, name, schema, context, validate=None):
        return await AGENTS[name].run(self, schema, context, validate)

    async def invoke(self, name, instructions, schema, context, validate=None):
        role = 'Figma explorer' if name == 'Browser decision' else name
        async with self.slots:
            await self.event(role, 'Running', f"{'Choosing the next UI action' if name == 'Browser decision' else 'Analyzing evidence and generating structured output'}{': ' + context['batch_label'] if context.get('batch_label') else ''}")
            return await invoke_specialist(self, name, instructions, schema, context, validate, role)


def check_sources(reqs, body, evidence):
    byid = {e['id']: e for e in evidence}
    for r in reqs.requirements:
        if r.source == 'ui':
            sources = '\n'.join(byid[i]['snapshot'] for i in r.evidence_ids if i in byid)
        else:
            if body.modules:
                module = next((m for m in body.modules if m.name == r.module), None)
                if module is None: raise ValueError('Requirements must use the exact supplied module names.')
                sources = getattr(module, r.source)
            else:
                sources = getattr(body, r.source)
        if r.source_quote not in sources:
            raise ValueError(f'{r.id} source_quote must be an exact substring of its cited source.')
        if 'Functional' not in r.required_types:
            raise ValueError(f'{r.id} must include the Functional obligation.')
        missing_types = implied_types(r.source_quote, r.required_types)
        if missing_types:
            raise ValueError(f'{r.id} must include {", ".join(missing_types)} so manual testers cover the edges implied by the source quote.')


def batches(reqs, nav):
    """Bound output size by small module batches rather than silently truncating cases."""
    groups = []
    modules = list(dict.fromkeys([r.module for r in reqs] + [e.module for e in nav.edges]))
    for module in modules:
        rs = [r for r in reqs if r.module == module]
        es = [e for e in nav.edges if e.module == module]
        for start in range(0, max(len(rs), len(es), 1), 3):
            groups.append({'module': module, 'requirements': [r.model_dump() for r in rs[start:start+3]], 'edges': [e.model_dump() for e in es[start:start+3]]})
    return groups


def assign_ids(cases):
    counters = {'Smoke': 0, 'Regression': 0}
    for c in cases:
        counters[c.suite] += 1
        c.id = ('SMK' if c.suite == 'Smoke' else 'REG') + f'-{counters[c.suite]:03}'


async def run_plan(body, emit=noop, llm=None, *, approved=None):
    team = Team(emit, llm)
    gaps, evidence, decisions, findings = [], [], [], []
    review_history = []
    existing = [c for m in body.modules for c in m.existing_cases]
    existing_reviews = []
    repairs = 0
    strategy = None
    for item in body.modules or [body]:
        prefix = getattr(item, 'name', 'Project')
        for source in ('confluence', 'figma'):
            if not getattr(item, source).strip(): gaps.append(f'{prefix}: no {source.title()} source supplied.')
            elif re.search(r'https?://', getattr(item, source)): gaps.append(f'{prefix}: {source.title()} links were not fetched; pasted content only.')
    if body.mode == 'offline':
        reqs, nav, cases = draft(body)
        assign_ids(cases)
        existing_reviews = [{'existing_case_id': c.id, 'disposition': 'Needs clarification', 'reason': 'Offline mode cannot assess semantic reuse; run live agents to compare this case with current requirements.'} for c in existing]
        for role in ROLES:
            await team.event(role, 'Complete', 'Offline template stage; no live reasoning or browser interaction.')
        gaps.append('Offline drafts are scaffolding only. They do not provide semantic review or independently verified test design.')
    else:
        team.llm = team.llm or LLMRouter(body.model)
        if team.llm.provider_name.startswith('mock'):
            raise ValueError('Live agents require a real configured model. Configure the server provider.')
        if approved is None:
            context = body.model_dump(exclude={'mode', 'max_actions', 'max_repairs'})
            def check_strategy(plan):
                names = {m.name for m in body.modules}
                if names and {m.module for m in plan.modules} != names: raise ValueError('Plan exactly the selected module names.')
            strategy = await team.ask('QA supervisor', Strategy, context, check_strategy)
            context['strategy'] = strategy.model_dump()
            gaps.extend(strategy.gaps)
            if body.explore_ui:
                enriched = []
                for module in body.modules:
                    current = module.model_copy(deep=True)
                    if module.figma_url:
                        await team.event('Figma explorer', 'Running', f'Reading design evidence for {module.name}.')
                        try:
                            text, count, source_gaps = await read_design(module.figma_url)
                            current.figma = (current.figma + '\n' + text).strip()
                            gaps.extend(f'{module.name}: {g}' for g in source_gaps)
                            await team.event('Figma explorer', 'Running', f'{module.name}: extracted {count} design nodes.')
                        except ValueError as exc:
                            gaps.append(f'{module.name}: {exc}')
                        except Exception:
                            gaps.append(f'{module.name}: Figma design API unavailable. Pasted design content remains usable.')
                        try:
                            explore_body = body.model_copy(update={'target_url': module.figma_url})
                            observed, actions, browser_gaps = await explore(explore_body, team.ask, lambda e: team.event(**e))
                            prefix = module.id + '-'
                            for e in observed: e['id'] = prefix + e['id']; e['module'] = module.name
                            for d in actions: d['evidence_id'] = prefix + d['evidence_id']
                            evidence.extend(observed); decisions.extend(actions)
                            gaps.extend(f'{module.name}: {g}' for g in browser_gaps)
                        except Exception:
                            gaps.append(f'{module.name}: prototype/browser exploration unavailable. Private or canvas-only designs require the API or an export.')
                    else:
                        gaps.append(f'{module.name}: no Figma URL; using pasted design evidence only.')
                    enriched.append(current)
                body = body.model_copy(update={'modules': enriched})
                context.update(body.model_dump(exclude={'mode', 'max_actions', 'max_repairs'}))
            else:
                gaps.append('Figma links were not explored; generation uses per-module design text/exports and requirements.')
            context['ui_evidence'] = evidence
            context['existing_test_cases'] = [c.model_dump() for c in existing]
            reqs = await team.ask('Requirements analyst', Requirements, context, lambda r: check_sources(r, body, evidence))
            source_lines = inventory(body, reqs.requirements)
            missing_lines = [row for row in source_lines if row['status'] != 'Linked']
            if missing_lines:
                await team.event('Requirements analyst', 'Repairing', f'Rechecking {len(missing_lines)} source lines without requirement links.')
                reqs = await team.ask('Requirements analyst', Requirements, {**context, 'previous_requirements': reqs.model_dump(), 'unlinked_source_lines': missing_lines, 'instruction': 'Return the full corrected requirement set, including omitted relevant lines. Preserve valid requirements. Explain untestable or conflicting lines in questions.'}, lambda r: check_sources(r, body, evidence))
            context['requirements'] = [r.model_dump() for r in reqs.requirements]
            nav = await team.ask('Figma explorer', Navigation, context, lambda n: validate_references(reqs.requirements, n, [], evidence))
            context['navigation_graph'] = nav.model_dump()
            # Re-plan against analyzed requirements and observed navigation, before approval.
            strategy = await team.ask('QA supervisor', Strategy, context, check_strategy)
            context['strategy'] = strategy.model_dump()
            return {'body': body.model_dump(), 'context': context, 'requirements': reqs.model_dump(),
                    'navigation': nav.model_dump(), 'strategy': strategy.model_dump(),
                    'gaps': gaps + strategy.gaps + reqs.questions + nav.questions, 'evidence': evidence,
                    'decisions': decisions, 'trace': team.trace,
                    'source_lines': inventory(body, reqs.requirements)}
        else:
            from .models import QAInput
            body = QAInput.model_validate(approved['body'])
            context = dict(approved['context'])
            reqs = Requirements.model_validate(approved['requirements'])
            nav = Navigation.model_validate(approved['navigation'])
            strategy = Strategy.model_validate(approved['strategy'])
            evidence, decisions = approved['evidence'], approved['decisions']
            gaps = list(approved['gaps'])
            team.trace = list(approved['trace'])
            context.update(requirements=reqs.model_dump()['requirements'],
                           navigation_graph=nav.model_dump(), strategy=strategy.model_dump(),
                           user_approved=True, user_edits=approved.get('user_edits', []))
        specs = [{'suite': 'Smoke', 'batch_label': 'Critical journeys and release blockers', 'requirements': context['requirements'], 'edges': [e.model_dump() for e in nav.edges]}]
        specs += [{'suite': 'Regression', 'batch_label': f"{g['module']} · batch {i+1}", **g} for i, g in enumerate(batches(reqs.requirements, nav))]
        for spec in specs:
            if spec['suite'] == 'Regression':
                spec['case_count_guidance'] = max(0, body.target_case_count // max(1, len(specs) - 1))
        outputs = {}
        rejected_candidates = {}
        async def design(index, feedback=None):
            spec = specs[index]
            # Each designer gets full source evidence but a bounded obligation batch.
            data = {**context, **spec}
            data['imported_case_ids'] = [c.id for c in existing]
            data['tester_style'] = MANUAL
            data['coverage_charter'] = 'Regression must cover every required_type as its own case. Numeric limits need separate valid-limit and invalid-limit Boundary cases (min, max, just below, just above, empty when the field can be cleared). Smoke stays a short happy-path walk a tester can execute before release.'
            data['provenance_rules'] = 'existing_case_ids may ONLY cite imported_case_ids. previous_cases are generated drafts, not imported cases. Repairing a generated draft does not make origin Improved. When imported_case_ids is empty EVERY case must have origin New and existing_case_ids [].'
            if feedback:
                data.update(repair_findings=[f.model_dump() for f in feedback], previous_cases=[c.model_dump() for c in outputs[index]])
            def validate(parsed):
                if any(c.suite != spec['suite'] for c in parsed.cases): raise ValueError('Wrong suite for this designer.')
                for c in parsed.cases:
                    if c.assumptions: c.status = 'Needs clarification'
                # Unsupported ideas are excluded from coverage, preserved as review gaps.
                rejected_candidates[index] = [c for c in parsed.cases if not c.requirement_ids and not c.edge_ids]
                parsed.cases = [c for c in parsed.cases if c.requirement_ids or c.edge_ids]
                validate_references(reqs.requirements, nav, parsed.cases, evidence)
                if feedback and index in outputs:
                    before = coverage_report(reqs.requirements, nav, outputs[index])
                    after = coverage_report(reqs.requirements, nav, parsed.cases)
                    covered_before = {o['id'] for o in before['obligations'] if o['status'] == 'Linked'}
                    covered_after = {o['id'] for o in after['obligations'] if o['status'] == 'Linked'}
                    if covered_before - covered_after:
                        raise ValueError('Repair dropped previously linked obligations: ' + ', '.join(sorted(covered_before - covered_after)) + '. Preserve valid coverage while correcting the flagged assertions.')
                existing_ids = {c.id for c in existing}
                for c in parsed.cases:
                    if set(c.existing_case_ids) - existing_ids:
                        raise ValueError(f'Unknown imported case reference {c.existing_case_ids}. Allowed imported IDs: {sorted(existing_ids)}. previous_cases are generated drafts, not imports. Use origin=New and existing_case_ids=[] for newly generated or repaired drafts with no imported source.')
                    if (c.origin == 'Improved') != bool(c.existing_case_ids): raise ValueError('Improved cases must cite existing_case_ids; New cases must not.')
            parsed = await team.ask(spec['suite'] + ' designer', Cases, data, validate)
            outputs[index] = parsed.cases
        await parallel(*(design(i) for i in range(len(specs))))
        cases = [c for i in range(len(specs)) for c in outputs[i]]
        assign_ids(cases)
        for round_no in range(body.max_repairs + 1):
            report = coverage_report(reqs.requirements, nav, cases)
            await team.event('Coverage reviewer', 'Running', f"Review {round_no+1}: {report['missing']} unlinked obligations; checking semantic coverage.")
            def check_review(review):
                reviewed = [x.existing_case_id for x in review.existing_case_reviews]
                if set(reviewed) != {c.id for c in existing} or len(reviewed) != len(set(reviewed)):
                    raise ValueError('Review every imported existing case exactly once, using only its supplied ID.')
            review = await team.ask('Coverage reviewer', Review, {**context, 'cases': [c.model_dump() for c in cases], 'coverage_report': report, 'excluded_unsupported_scenarios': [c.model_dump() for values in rejected_candidates.values() for c in values]}, check_review)
            existing_reviews = [x.model_dump() for x in review.existing_case_reviews]
            findings = missing_findings(report) + review.findings
            review_history.append({'round': round_no + 1, 'decision': review.decision, 'findings': [f.model_dump() for f in findings]})
            repairable = [f for f in findings if f.owner in ('Smoke designer', 'Regression designer')]
            if not repairable or round_no == body.max_repairs: break
            jobs = []
            for i, spec in enumerate(specs):
                target_ids = {r['id'] for r in spec['requirements']} | {e['id'] for e in spec['edges']} | {c.id for c in outputs[i]}
                relevant = [f for f in repairable if f.owner == spec['suite'] + ' designer' and (not f.target_ids or target_ids.intersection(f.target_ids) or spec['suite'] == 'Smoke')]
                if relevant: jobs.append(design(i, relevant))
            if not jobs: break
            repairs += 1
            await team.event('Coverage reviewer', 'Repairing', f'Sending findings back to {len(jobs)} designer batch(es); repair round {repairs}.')
            await parallel(*jobs)
            cases = [c for i in range(len(specs)) for c in outputs[i]]
            assign_ids(cases)
    if body.mode == 'live':
        gaps.extend(f'Unsupported scenario excluded from coverage: {c.name}. It had no source or navigation reference.' for values in rejected_candidates.values() for c in values)
    validate_references(reqs.requirements, nav, cases, evidence)
    gaps += reqs.questions + nav.questions
    source_lines = inventory(body, reqs.requirements)
    unlinked_lines = [row for row in source_lines if row['status'] != 'Linked']
    if unlinked_lines: gaps.append(f'{len(unlinked_lines)} source lines have no explicit requirement link. Inspect the source-line checklist before approval.')
    report = coverage_report(reqs.requirements, nav, cases)
    if body.mode == 'offline': findings = missing_findings(report)
    if not nav.edges: gaps.append('No navigation edges identified; E2E completeness cannot be assessed.')
    if not any(j.critical for j in nav.journeys): gaps.append('No critical E2E journey identified. Review the primary release path.')
    gaps.append('No generated test has been executed. Linked obligations are traceability coverage, not proof of correctness or exhaustive application coverage.')
    if body.target_case_count and len(cases) < body.target_case_count:
        gaps.append(f'Requested planning target: {body.target_case_count} cases; produced {len(cases)} grounded drafts. Further scenarios require richer evidence or another review; the count was not padded.')
    if body.mode == 'live':
        def check_plan(plan):
            if set(plan.case_ids) - {c.id for c in cases}: raise ValueError('Documentation references unknown case IDs.')
        document = await team.ask('Test plan writer', TestPlan, {'strategy': strategy.model_dump(), 'modules': [m.name for m in body.modules], 'coverage': report, 'cases': [c.model_dump() for c in cases], 'findings': [f.model_dump() for f in findings], 'gaps': gaps}, check_plan)
    else:
        document = TestPlan(title='Shift-left QA test plan — offline draft', overview='Template planning document for the supplied module requirements. No tests were executed.', scope_in=[m.name for m in body.modules] or ['Supplied requirements'], scope_out=['Unspecified behavior and unobserved runtime states'], approach=['Review critical E2E smoke journeys.', 'Review module-wise regression obligations and refine template steps.'], environments=['Confirm the intended test environment, fixtures and roles.'], entry_criteria=['Requirements and expected results have been reviewed.'], exit_criteria=['All approved cases executed; defects triaged against agreed release criteria.'], risks=['Offline templates have not received semantic model review.'], deliverables=['Smoke suite', 'Regression suite', 'Coverage matrix', 'Open findings'], assumptions=gaps, case_ids=[c.id for c in cases])
    await team.event('Coverage reviewer', 'Complete', f"Plan ready for review: {report['smoke']} smoke, {report['regression']} regression, {report['missing']} missing obligations.")
    return {'source_lines': source_lines, 'mode': body.mode, 'model': body.model or (team.llm.model if team.llm and hasattr(team.llm, 'model') else ''), 'strategy': strategy.model_dump() if strategy else None, 'test_plan': document.model_dump(), 'requirements': [r.model_dump() for r in reqs.requirements], 'edges': [e.model_dump() for e in nav.edges], 'journeys': [j.model_dump() for j in nav.journeys], 'cases': [c.model_dump() for c in cases], 'coverage': report, 'findings': [f.model_dump() for f in findings], 'gaps': gaps, 'trace': team.trace, 'evidence': evidence, 'decisions': decisions, 'review_history': review_history, 'repairs': repairs, 'existing_cases': [c.model_dump() for c in existing], 'existing_case_reviews': existing_reviews, 'execution_status': 'Not executed', 'readiness': 'Needs review' if gaps or findings or report['clarifications'] else 'Draft'}
