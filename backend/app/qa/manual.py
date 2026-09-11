"""Manual-tester style and source-implied edge obligations."""
import re
from .models import TestingType

MANUAL = (
    'Write every case the way a sitting manual tester would execute it. One scenario per case. '
    'Preconditions: start screen, account/role, and data already in the system. '
    'Test data: exact values (valid min, valid max, just below, just above, blank, duplicate). '
    'Each step is one user action: open, click, type, clear, select, submit, go back, refresh. '
    'Each expected_result is what the tester sees next: screen, field value, enabled/disabled control, message, or unchanged state. '
    'Never write "verify the behavior", "appropriate result", or "system handles it". '
    'Cover every source-supported path: happy path, invalid/missing input, empty/blank, documented min and max, just outside those limits, alternate navigation, back/refresh, retry/duplicate, and role restrictions. '
    'Do not merge those into one omnibus case. Do not invent limits, messages, or buttons that are not in the sources; mark Needs clarification instead.'
)


def infer_types(text: str) -> list[TestingType]:
    """Minimum testing types a manual tester would schedule from this source line."""
    types: list[TestingType] = ['Functional']
    if re.search(r'invalid|cannot|must not|denied|reject|required|mandatory|missing|blank|empty|not allowed|only .{1,40} can|must (?:be|sign|log|have|contain|include|use|enter|select)', text, re.I):
        types.append('Negative')
    if re.search(r'\d|limit|min(?:imum)?|max(?:imum)?|between|at most|at least|inclusive|exclusive|\blength\b|\brange\b|up to', text, re.I):
        types.append('Boundary')
    if re.search(r'\b(role|guest|permission|admin|unauthori[sz]ed|sign in|log in)\b', text, re.I):
        types.append('Security')
    if re.search(r'\b(fail|retry|error|timeout|recover)\b', text, re.I):
        types.append('Recovery')
    if re.search(r'\b(preserv|retain|duplicate|reset|refresh|go back|return to|persist)\b', text, re.I):
        types.append('State')
    return list(dict.fromkeys(types))


def boundary_min_cases(text: str) -> int:
    """Numeric limits need separate valid-limit and invalid-limit cases."""
    return 2 if 'Boundary' in infer_types(text) and re.search(r'\d', text) else 1


def implied_types(quote: str, assigned: list[str]) -> list[str]:
    return [t for t in infer_types(quote) if t not in assigned]
