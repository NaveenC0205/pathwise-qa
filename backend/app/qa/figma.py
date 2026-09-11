"""Read Figma design structure as shift-left evidence, without claiming runtime behavior."""
import json
import re
from urllib.parse import urlsplit, parse_qs
import httpx
from app.config import get_settings


def parse_figma_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('figma.com', 'www.figma.com') or parsed.username or parsed.password:
        raise ValueError('Use an HTTPS Figma design, file or prototype URL.')
    match = re.match(r'^/(?:design|file|proto)/([a-zA-Z0-9]+)(?:/|$)', parsed.path)
    if not match: raise ValueError('The Figma URL must contain a design, file or prototype key.')
    node = parse_qs(parsed.query).get('node-id', [''])[0].replace('-', ':')
    if node and not re.fullmatch(r'[\d:]+', node): raise ValueError('Invalid Figma node ID.')
    return match.group(1), node


def design_lines(data, max_nodes=500):
    rows = []
    roots = [item['document'] for item in data.get('nodes', {}).values() if item and item.get('document')] or [data.get('document', {})]
    pending = [(root, '') for root in roots]
    count = 0
    while pending and count < max_nodes:
        node, parent = pending.pop(0)
        count += 1
        node_id = node.get('id', '')
        pieces = [f"Node {node_id}: {node.get('type', 'UNKNOWN')} {node.get('name', '')}"]
        if parent: pieces.append('parent=' + parent)
        if node.get('characters'): pieces.append('text=' + node['characters'])
        if node.get('visible') is False: pieces.append('hidden in design')
        for key in ('reactions', 'interactions', 'transitionNodeID', 'prototypeStartNodeID', 'flowStartingPoints'):
            if node.get(key): pieces.append(f'{key}=' + json.dumps(node[key], ensure_ascii=False))
        rows.append(' | '.join(pieces))
        pending.extend((child, node_id) for child in node.get('children', []))
    return '\n'.join(rows), bool(pending), count


async def read_design(url):
    key, node = parse_figma_url(url)
    token = get_settings().figma_access_token
    if not token: raise ValueError('Figma API access is not configured. Paste a design export or configure FIGMA_ACCESS_TOKEN; public prototype exploration may still provide partial evidence.')
    endpoint = f'https://api.figma.com/v1/files/{key}' + ('/nodes' if node else '')
    params = {'ids': node} if node else {'depth': 6}
    chunks = bytearray()
    async with httpx.AsyncClient(timeout=40, follow_redirects=False) as client:
        async with client.stream('GET', endpoint, params=params, headers={'X-Figma-Token': token}) as response:
            if response.status_code != 200: raise ValueError(f'Figma returned HTTP {response.status_code}; verify file access and read scope.')
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > 5_000_000: raise ValueError('Figma response exceeds 5 MB. Use a URL for a specific module frame/node.')
    text, truncated, count = design_lines(json.loads(chunks))
    if len(text) > 30000: text = text[:30000]; truncated = True
    gaps = []
    if truncated: gaps.append('Figma design extraction was truncated; narrow the URL to the module frame for full detail.')
    if not node: gaps.append('Figma extraction is limited to six node levels. Use a module frame URL to include its full subtree.')
    return text, count, gaps
