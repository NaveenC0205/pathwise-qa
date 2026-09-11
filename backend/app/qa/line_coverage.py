"""Line inventory exposes omissions; lexical traceability is not semantic proof."""
def inventory(body, requirements):
    rows = []
    for module in body.modules or [body]:
        name = getattr(module, 'name', 'General')
        for source in ('story', 'success_criteria', 'navigation', 'confluence', 'figma'):
            for index, raw in enumerate(getattr(module, source).splitlines(), 1):
                text = raw.strip()
                if not text or text.startswith('#'): continue
                linked = [r.id for r in requirements if r.source == source and (not body.modules or r.module == name) and (r.source_quote in text or text in r.source_quote)]
                rows.append({'id': f'{getattr(module,"id","project")}:{source}:{index}', 'module': name, 'source': source, 'line': index, 'text': text, 'requirement_ids': linked, 'status': 'Linked' if linked else 'Needs review'})
    return rows
