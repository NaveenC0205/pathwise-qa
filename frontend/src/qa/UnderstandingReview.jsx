import { useState } from 'react'

export default function UnderstandingReview({ pending, onApprove, disabled }) {
  const [draft, setDraft] = useState(() => ({
    requirements: structuredClone(pending.analysis.requirements),
    navigation: structuredClone(pending.analysis.navigation),
    strategy: structuredClone(pending.analysis.strategy), notes: '',
  }))
  const [confirmed, setConfirmed] = useState(false)
  function update(change) { setConfirmed(false); setDraft(current => change(current)) }
  const strategyField = (key, value) => update(d => ({ ...d, strategy: { ...d.strategy, [key]: value } }))
  const requirementField = (id, key, value) => update(d => ({ ...d, requirements: { ...d.requirements, requirements: d.requirements.requirements.map(r => r.id === id ? { ...r, [key]: value } : r) } }))
  const edgeField = (id, key, value) => update(d => ({ ...d, navigation: { ...d.navigation, edges: d.navigation.edges.map(e => e.id === id ? { ...e, [key]: value } : e) } }))
  return <section className="qa-understanding">
    <h2>Review what the agents understood</h2>
    <p>No test cases have been generated. Edit the interpretation and proposed strategy below, then approve this saved analysis.</p>
    <fieldset disabled={disabled}>
      <label>Overall application functionality<textarea value={draft.strategy.application_understanding} onChange={e => strategyField('application_understanding', e.target.value)} /></label>
      {[['smoke_approach', 'Proposed smoke journeys'], ['regression_approach', 'Proposed regression coverage']].map(([key, label]) => <label key={key}>{label}<textarea value={draft.strategy[key].join('\n')} onChange={e => strategyField(key, e.target.value.split('\n'))} /></label>)}
      {draft.strategy.modules.map(m => <details key={m.module} open><summary><b>{m.module}</b> · {m.priority} · approximately {m.estimated_case_count} cases</summary>
        <label>Module test focus<textarea value={m.test_focus.join('\n')} onChange={e => strategyField('modules', draft.strategy.modules.map(x => x.module === m.module ? { ...x, test_focus: e.target.value.split('\n') } : x))} /></label>
        {draft.requirements.requirements.filter(r => r.module === m.module).map(r => <article key={r.id} className="qa-understanding-requirement">
          <b>{r.id} · {r.source.replaceAll('_', ' ')}</b><blockquote>{r.source_quote}</blockquote>
          <label>Understood functionality<textarea value={r.text} onChange={e => requirementField(r.id, 'text', e.target.value)} /></label>
          <label>Why this needs testing<textarea value={r.rationale} onChange={e => requirementField(r.id, 'rationale', e.target.value)} /></label>
          <label className="qa-check"><input type="checkbox" checked={r.critical} onChange={e => requirementField(r.id, 'critical', e.target.checked)} />Critical functionality for smoke coverage</label>
        </article>)}
        {draft.navigation.edges.filter(e => e.module === m.module).map(edge => <article key={edge.id}><b>{edge.id} · Navigation</b>{[['origin', 'From screen'], ['destination', 'To screen'], ['action', 'User action'], ['condition', 'Condition']].map(([key, label]) => <label key={key}>{label}<input value={edge[key]} onChange={e => edgeField(edge.id, key, e.target.value)} /></label>)}</article>)}
      </details>)}
      <details><summary>Source-line coverage and open questions</summary>
        <p>Unresolved questions remain gaps after approval. Add answers in the reviewed interpretation or reviewer notes.</p>
        <ul>{[...new Set(pending.analysis.gaps)].map((g, i) => <li key={i}>{g}</li>)}</ul>
        {pending.analysis.source_lines.map(line => <p key={line.id}><b>{line.module} · {line.source}:{line.line} · {line.status}</b><br />{line.text}</p>)}
      </details>
      <details><summary>Proposed journeys and captured evidence</summary>
        {draft.navigation.journeys.map(j => <p key={j.id}><b>{j.name}</b> · {j.critical ? 'Critical journey' : 'Alternate journey'}<br />{j.edge_ids.join(' → ')}</p>)}
        {pending.analysis.evidence.map(e => <article key={e.id}><b>{e.id} · {e.module}</b><p>{e.url}</p><pre className="qa-snapshot">{e.snapshot}</pre></article>)}
        {pending.analysis.decisions.map((d, i) => <p key={i}>{d.action}: {d.reason}</p>)}
        {!pending.analysis.evidence.length && <p>No live design observations were captured. The analysis uses supplied source text.</p>}
      </details>
      <label>Reviewer corrections and answers<textarea value={draft.notes} maxLength={10000} onChange={e => update(d => ({ ...d, notes: e.target.value }))} /></label>
      <label className="qa-check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I approve this understanding and strategy, with the listed gaps remaining explicit.</label>
      <button type="button" className="qa-primary" disabled={!confirmed || disabled} onClick={() => onApprove({ ...draft, approved: true })}>Approve & generate functional test suites →</button>
    </fieldset>
  </section>
}
