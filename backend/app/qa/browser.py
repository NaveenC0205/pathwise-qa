"""Actual Playwright MCP tool loop. Only allowlisted observed controls are offered."""
import os
import re
import shutil
import importlib.util
from pathlib import Path
from datetime import timedelta
from urllib.parse import urlsplit
from .models import BrowserDecision

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / 'qa-browser/node_modules/@playwright/mcp/cli.js'
GUARD = ROOT / 'qa-browser/guard.cjs'
UNSAFE = re.compile(r'\b(buy|pay|purchase|order now|checkout|delete|remove|send|submit|save|create|add|approve|refund|cancel|sign out|log out|sign in|log in|login|subscribe|accept|confirm|execute|run|generate|download|export|upload)\b', re.I)
SAFE_BUTTON = re.compile(r'\b(menu|navigation|tab|expand|collapse|show|view|details|next|previous|back|close|open|more|filter|sort|search)\b', re.I)


def allowed_origins():
    return [s.strip().rstrip('/') for s in os.environ.get('QA_ALLOWED_ORIGINS', 'https://www.figma.com,https://figma.com').split(',') if s.strip()]


def origin_for(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use an HTTP(S) test application URL without embedded credentials.')
    port = parsed.port
    return f'{parsed.scheme}://{parsed.hostname}' + (f':{port}' if port and port != (443 if parsed.scheme == 'https' else 80) else '')


def check_target(url):
    origin = origin_for(url)
    if origin not in allowed_origins():
        raise ValueError('This test origin is not enabled. Add its exact origin to the server QA_ALLOWED_ORIGINS setting.')
    if origin not in ('https://www.figma.com', 'https://figma.com') and UNSAFE.search(urlsplit(url).path):
        raise ValueError('Start exploration from a read-only application entry page.')
    return origin


def capabilities():
    return {'installed': CLI.exists() and bool(shutil.which('node')) and importlib.util.find_spec('mcp') is not None, 'allowed_origins': allowed_origins(), 'transport': 'Playwright MCP · isolated stdio', 'policy': 'Read-only Figma/prototype exploration. Canvas and authenticated content may require a Figma API token or export.'}


def candidates(snapshot, prototype=False):
    found = []
    # MCP uses refs such as e12 or s1e12. Never forward arbitrary selectors from a model.
    for line in snapshot.splitlines():
        match = re.search(r'- (link|button|tab|menuitem) "([^"]+)".*?\[ref=([\w-]+)\]', line)
        if not match: continue
        role, label, ref = match.groups()
        if '[disabled]' in line: continue
        if prototype:
            if re.search(r'\b(delete file|delete account|share file|publish|sign in|log in|subscribe)\b', label, re.I): continue
        else:
            if UNSAFE.search(label): continue
            if role == 'button' and not SAFE_BUTTON.search(label): continue
        found.append({'ref': ref, 'role': role, 'label': label})
    return found


def snapshot_url(text, fallback):
    match = re.search(r'Page URL:\s*(https?://\S+)', text)
    return match.group(1) if match else fallback


async def explore(body, ask, emit):
    origin = check_target(body.target_url)
    if not capabilities()['installed']:
        raise ValueError('Playwright MCP is not installed. Install the qa-browser package and Python qa extra.')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    evidence, decisions, gaps = [], [], []
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'TMPDIR', 'SYSTEMROOT', 'DISPLAY')}
    env['QA_BROWSER_ORIGIN'] = origin
    parameters = StdioServerParameters(command=shutil.which('node'), args=[str(CLI), '--headless', '--isolated', '--browser', 'chrome', '--block-service-workers', '--init-page', str(GUARD), '--timeout-navigation', '15000', '--timeout-action', '5000'], cwd=str(ROOT / 'qa-browser'), env=env)
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=35)) as session:
            await session.initialize()
            tools = {t.name: t.inputSchema for t in (await session.list_tools()).tools}
            async def call(name, args):
                response = await session.call_tool(name, args)
                text = '\n'.join(c.text for c in response.content if getattr(c, 'type', '') == 'text')
                if response.isError: raise ValueError('Playwright action failed: ' + text[:300])
                return text
            try:
                text = await call('browser_navigate', {'url': body.target_url})
                visited = set()
                for index in range(body.max_actions + 1):
                    snapshot = await call('browser_snapshot', {})
                    url = snapshot_url(snapshot, snapshot_url(text, body.target_url))
                    current_origin = origin_for(url)
                    figma_origins = {'https://figma.com', 'https://www.figma.com'}
                    if current_origin != origin and not ({current_origin, origin} <= figma_origins):
                        gaps.append('Exploration stopped at an out-of-scope redirect.'); break
                    eid = f'UI-{len(evidence)+1:03}'
                    truncated = len(snapshot) > 16000
                    evidence.append({'id': eid, 'url': url, 'snapshot': snapshot[:16000], 'truncated': truncated, 'observation': 'Navigation snapshot; no test executed.'})
                    await emit({'agent': 'Figma explorer', 'status': 'Running', 'detail': f'Captured {eid}: {url}', 'evidence_id': eid})
                    if truncated: gaps.append(f'{eid} exceeded snapshot size; omitted content is not covered.')
                    if index == body.max_actions:
                        gaps.append(f'Exploration stopped at the {body.max_actions}-action budget; remaining UI paths may be unvisited.'); break
                    prototype = urlsplit(url).hostname in ('figma.com', 'www.figma.com') and urlsplit(url).path.startswith('/proto/')
                    options = [c for c in candidates(snapshot[:16000], prototype) if (url, c['ref'], snapshot[:16000]) not in visited]
                    decision = await ask('Browser decision', BrowserDecision, {'story': body.story or '\n'.join(m.name + ': ' + m.story for m in body.modules), 'snapshot': snapshot[:16000], 'surface': 'Figma prototype simulation' if prototype else 'Design document / navigation', 'candidates': options, 'history': decisions, 'remaining_actions': body.max_actions - index})
                    decisions.append({'evidence_id': eid, **decision.model_dump()})
                    await emit({'agent': 'Figma explorer', 'status': 'Running', 'detail': decision.reason, 'action': decision.action})
                    if decision.action == 'stop':
                        gaps.append('Explorer stopped: ' + decision.reason); break
                    if decision.action == 'back':
                        text = await call('browser_navigate_back', {}); continue
                    choice = next((c for c in options if c['ref'] == decision.ref), None)
                    if choice is None:
                        gaps.append('Explorer proposed a non-allowed or stale control; it was not clicked.'); break
                    visited.add((url, choice['ref'], snapshot[:16000]))
                    field = 'target' if 'target' in tools['browser_click'].get('properties', {}) else 'ref'
                    text = await call('browser_click', {field: choice['ref'], 'element': choice['label']})
            finally:
                try: await session.call_tool('browser_close', {})
                except Exception: pass
    gaps.append('Figma/prototype evidence supports shift-left design review only. It does not prove implemented navigation, backend behavior or executed test results.')
    return evidence, decisions, gaps
