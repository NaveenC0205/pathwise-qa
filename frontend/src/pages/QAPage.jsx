import { useEffect, useRef, useState } from 'react'
import { generatePlan, downloadPlan, downloadTestPlan, sample } from '../qa/client'
import './qa.css'
import UnderstandingReview from '../qa/UnderstandingReview'

const labels = { story: 'User stories', success_criteria: 'Success criteria', navigation: 'Navigation', confluence: 'Confluence', figma: 'Figma' }
const emptyModule = (name = 'Module 1') => ({ id: crypto.randomUUID(), selected: true, name, figma_url: '', story: '', success_criteria: '', navigation: '', confluence: '', figma: '', existing_cases: [] })
const roles = [
  ['QA supervisor', 'Plan and coordinate selected modules'],
  ['Requirements analyst', 'Define module coverage obligations'],
  ['Figma explorer', 'Read design & prototype evidence'],
  ['Smoke designer', 'Protect critical E2E journeys'],
  ['Regression designer', 'Design granular module test cases'],
  ['Coverage reviewer', 'Find omissions and request repairs'],
  ['Test plan writer', 'Write the QA plan & documentation'],
]
const types = ['Functional', 'Negative', 'Boundary', 'Navigation', 'Accessibility', 'Security', 'Recovery', 'State']

function CaseDetail({ test, requirements }) {
  return <details className="qa-test-case">
    <summary><small>{test.id}</small><strong>{test.name}<span className="qa-case-meta">{test.module} · {test.suite} · {test.testing_type} · {test.level}</span></strong><span className="qa-priority">{test.priority}</span></summary>
    <article>
      <p>{test.description}</p><details><summary>Why was this test generated?</summary>{requirements.filter(r => test.requirement_ids.includes(r.id)).map(r => <p key={r.id}><b>{r.id} · {r.module} · {r.source}</b><br />{r.text}<br />{r.rationale}</p>)}{test.edge_ids.length > 0 && <p>Navigation coverage: {test.edge_ids.join(', ')}</p>}<p>{test.suite === 'Smoke' ? 'Smoke scope: critical requirements and end-to-end journeys in the approved strategy.' : 'Regression scope: detailed requirements and transitions in the approved strategy.'}</p></details><p className="qa-note">{test.origin} case{test.existing_case_ids.length > 0 ? ` · Based on ${test.existing_case_ids.join(', ')}` : ''}</p><p><b>Role:</b> {test.role} <span className="qa-status-pill">{test.status} · Not executed</span></p>
      <div className="qa-case-setup"><section><b>Preconditions</b><ul>{test.preconditions.map((s, i) => <li key={i}>{s}</li>)}</ul></section><section><b>Test data</b><ul>{test.test_data.map((s, i) => <li key={i}>{s}</li>)}</ul></section></div>
      <div className="qa-step-table"><table><thead><tr><th>#</th><th>Test step</th><th>Expected result</th></tr></thead><tbody>{test.steps.map((step, i) => <tr key={i}><td>{i + 1}</td><td>{step.action}</td><td>{step.expected_result}</td></tr>)}</tbody></table></div>
      <p><b>Overall expected result</b><br />{test.expected_result}</p>
      {test.assumptions.length > 0 && <div className="qa-assumptions"><b>Clarify before execution</b><ul>{test.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></div>}
      <p className="qa-trace-links">Requirements: {test.requirement_ids.join(', ') || '—'} · Navigation: {test.edge_ids.join(', ') || '—'}<br />Journeys: {test.journey_ids.join(', ') || '—'} · UI evidence: {test.evidence_ids.join(', ') || 'Not observed'}</p>
    </article>
  </details>
}

export default function QAPage() {
  const [inputModules, setInputModules] = useState(() => [emptyModule()])
  const [activeModule, setActiveModule] = useState(null)
  const inputs = inputModules.find(m => m.id === activeModule) || inputModules[0]
  const setInputs = value => setInputModules(current => current.map(m => m.id === inputs.id ? (typeof value === 'function' ? value(m) : value) : m))
  const [importing, setImporting] = useState(false), [importNotice, setImportNotice] = useState(null)
  const allExisting = inputModules.flatMap(m => m.existing_cases)
  const selectedModules = inputModules.filter(m => m.selected !== false)
  const invalidModules = !selectedModules.length || selectedModules.some(m => !m.name.trim() || m.story.trim().length < 10)
  function loadExample() {
    const names = ['Catalog', 'Cart', 'Checkout', 'Payment']
    const records = names.map(name => ({ ...emptyModule(name), story: sample.story.split('\n').filter(s => s.startsWith(`[${name}]`)).map(s => s.replace(/^\[[^\]]+\] /, '')).join('\n'), success_criteria: name === 'Cart' ? 'Only available products can be added. Quantity must be 1–10 inclusive.' : name === 'Payment' ? 'Success creates one order. Failure creates no order and offers retry.' : name === 'Checkout' ? 'A valid address and signed-in user are required to continue.' : 'The selected product and its stock availability are displayed.', navigation: name === 'Catalog' ? 'Home → Product' : name === 'Cart' ? 'Product → Cart → Checkout' : name === 'Checkout' ? 'Cart → Sign in → Checkout → Payment\nCheckout → Cart' : 'Payment → Confirmation → Order details\nPayment → Payment error → Payment', confluence: sample.confluence.split(`# ${name}\n`)[1]?.split('\n# ')[0] || '', figma: sample.figma.split(`# ${name}\n`)[1]?.split('\n# ')[0] || '' }))
    setPending(null); setFailedRun(null); localStorage.removeItem('pathwise-run'); setInputModules(records); setActiveModule(records[0].id); setResult(null); setError(''); setEvents([]); setExplore(false); setImportNotice(null)
  }
  function addModule() {
    let number = inputModules.length + 1
    while (inputModules.some(m => m.name === `Module ${number}`)) number++
    const next = emptyModule(`Module ${number}`)
    setInputModules(current => [...current, next]); setActiveModule(next.id)
  }
  function removeModule() {
    setInputModules(current => current.filter(m => m.id !== inputs.id)); setActiveModule(null); setImportNotice(null)
  }
  async function importExisting(e) {
    const file = e.target.files[0]; if (!file) return
    e.target.value = ''
    if (file.size > 2000000) { setError('Use a CSV or XLSX file smaller than 2 MB.'); return }
    setImporting(true); setError('')
    const destinationId = inputs.id
    try {
      const form = new FormData(); form.append('file', file)
      const response = await fetch('/api/qa/import-cases', { method: 'POST', body: form })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The file could not be imported.')
      setInputModules(current => {
        const next = current.map(m => ({ ...m, existing_cases: [...m.existing_cases] }))
        for (const test of data.cases) {
          if (next.some(m => m.existing_cases.some(c => c.id === test.id))) continue
          let destination = test.module.trim() ? next.find(m => m.name.trim().toLowerCase() === test.module.trim().toLowerCase()) : next.find(m => m.id === destinationId)
          if (!destination) { destination = emptyModule(test.module.trim()); next.push(destination) }
          destination.existing_cases.push(test)
        }
        return next
      })
      setImportNotice({ ...data, warnings: [...data.warnings, 'Module-column values are matched by name. Add a story and criteria for any newly created module.'] })
    } catch (e) { setError(e.message) }
    finally { setImporting(false) }
  }
  const [source, setSource] = useState('story')
  const mode = 'live'
  const [pending, setPending] = useState(null)
  const [failedRun, setFailedRun] = useState(null)
  const [explore, setExplore] = useState(false), [budget, setBudget] = useState(12)
  const [model, setModel] = useState(''), [targetCount, setTargetCount] = useState(0)
  const [capabilities, setCapabilities] = useState(null), [result, setResult] = useState(null)
  const [generatedInputs, setGeneratedInputs] = useState('')
  const inputSignature = JSON.stringify({ modules: inputModules, mode, model, targetCount, explore, budget })
  const inputsChanged = (result || pending || failedRun) && generatedInputs !== inputSignature
  const [running, setRunning] = useState(false), [error, setError] = useState(''), [events, setEvents] = useState([])
  const [view, setView] = useState('cases'), [search, setSearch] = useState(''), [suite, setSuite] = useState('All')
  const [kind, setKind] = useState('All'), [module, setModule] = useState('All')
  const controller = useRef(null)
  useEffect(() => {
    const abort = new AbortController()
    fetch('/api/qa/capabilities', { signal: abort.signal }).then(r => r.ok ? r.json() : null).then(setCapabilities).catch(() => {})
    const saved = localStorage.getItem('pathwise-run')
    if (saved) fetch('/api/qa/runs/' + encodeURIComponent(saved), { signal: abort.signal })
      .then(r => r.ok ? r.json() : null).then(data => {
        if (abort.signal.aborted || !data) return
        if (data.input?.modules?.length) {
          const restored = data.input.modules.map(m => ({ ...m, selected: true }))
          setInputModules(restored); setModel(data.input.model); setTargetCount(data.input.target_case_count)
          setExplore(data.input.explore_ui); setBudget(data.input.max_actions)
          setGeneratedInputs(JSON.stringify({ modules: restored, mode: 'live', model: data.input.model, targetCount: data.input.target_case_count, explore: data.input.explore_ui, budget: data.input.max_actions }))
        }
        if (data.status === 'awaiting_approval') {
          setPending(data); setEvents(data.analysis.trace); setView('understanding')
        } else if (data.status === 'complete') {
          setResult(data.result); setEvents(data.result.trace); setView('cases')
        } else if (data.can_retry) {
          setFailedRun(data.run_id); setError('The previous generation stopped. Retry using the saved approved understanding.')
        } else setError('The previous analysis was interrupted. Start a new analysis to continue.')
      }).catch(() => {})
    return () => { abort.abort(); controller.current?.abort() }
  }, [])
  async function generate(e) {
    e.preventDefault(); setPending(null); localStorage.removeItem('pathwise-run'); setRunning(true); setError(''); setResult(null); setEvents([]); setView('activity')
    setSuite('All'); setModule('All'); setKind('All'); setSearch('')
    controller.current = new AbortController()
    try {
      const plan = await generatePlan({ modules: selectedModules.map(({ selected: _selected, ...m }) => ({ ...m, existing_cases: m.existing_cases.map(c => ({ ...c, module: m.name })) })), mode, model, target_case_count: targetCount, explore_ui: explore, max_actions: budget, max_repairs: 2 }, row => { setEvents(current => [...current, row]); if (row.run_id) localStorage.setItem('pathwise-run', row.run_id) }, controller.current.signal)
      setPending(plan); setGeneratedInputs(inputSignature); setView('understanding')
    } catch (e) { setError(e.name === 'AbortError' ? 'Run stopped. No incomplete plan is marked as ready.' : e.message) }
    finally { setRunning(false) }
  }
  async function approve(draft) {
    if (inputsChanged || !pending) return
    setRunning(true); setError(''); setView('activity')
    controller.current = new AbortController()
    try {
      const data = await generatePlan(draft, row => setEvents(current => [...current, row]), controller.current.signal,
        '/api/qa/runs/' + encodeURIComponent(pending.run_id) + '/approve/stream')
      setResult(data.result); setPending(null); setView('cases')
    } catch (e) {
      setError(e.name === 'AbortError' ? 'Generation stopped. Retry the approved generation or start a new analysis.' : e.message)
      setFailedRun(pending.run_id); setPending(null)
    } finally { setRunning(false) }
  }
  async function retryApproved() {
    if (!failedRun || inputsChanged) return
    setRunning(true); setError(''); setView('activity')
    controller.current = new AbortController()
    try {
      const data = await generatePlan({}, row => setEvents(current => [...current, row]), controller.current.signal,
        '/api/qa/runs/' + encodeURIComponent(failedRun) + '/retry/stream')
      setResult(data.result); setFailedRun(null); setView('cases')
    } catch (e) { setError(e.name === 'AbortError' ? 'Generation stopped.' : e.message) }
    finally { setRunning(false) }
  }
  async function upload(e) {
    const file = e.target.files[0]; if (!file) return
    if (file.size > 120000) { setError('Use a text or JSON export smaller than 120 KB.'); return }
    const text = await file.text()
    if (text.length > 40000) { setError('Use at most 40,000 characters per source.'); return }
    setInputs(current => ({ ...current, [source]: text })); e.target.value = ''
  }
  const cases = result?.cases.filter(c => (suite === 'All' || c.suite === suite) && (kind === 'All' || c.testing_type === kind) && (module === 'All' || c.module === module) && `${c.id} ${c.name} ${c.description}`.toLowerCase().includes(search.toLowerCase())) || []
  const modules = [...new Set(result?.cases.map(c => c.module) || [])]
  const lastEvent = events.at(-1)
  return <div className="qa-app">
    <aside className="qa-sidebar"><a className="qa-brand" href="/"><b>q</b> pathwise <small>QA</small></a><div className="qa-workspace">N <span>My workspace<small>Quality engineering</small></span></div><small className="qa-nav-label">WORKSPACE</small><a className="qa-active" href="/">◈ &nbsp; Test generation</a><div className="qa-sidebar-note">● LangGraph agent workflow<p>Analyze → your approval → design → review.</p></div><span className="qa-back">Standalone QA workspace</span></aside>
    <div className="qa-content"><header className="qa-top">Workspace <span>/</span> Agentic test design <b>N</b></header><main className="qa-main">
      <div className="qa-heading"><div><small>STANDALONE SHIFT-LEFT QA</small><h1>Design quality.<br className="qa-mobile-break" /> Before the first build.</h1><p>Critical E2E smoke tests. Granular regression suites. Source traceability. Test plans and documentation.</p></div><button disabled={running || importing} onClick={loadExample}>↗ Load example</button></div>
      <div className="qa-agents qa-team-agents">{roles.map(([name, description], i) => {
        const event = events.findLast(e => e.agent === name)
        return <div key={name} className={event?.status === 'Running' || event?.status === 'Repairing' ? 'qa-agent-working' : ''}><b>0{i + 1}</b><span><strong>{name}</strong><small>{event ? (running ? event.status : result ? 'Complete' : pending ? event.status : 'Stopped') : description}</small></span><em>{event?.status === 'Complete' ? '✓' : '·'}</em></div>
      })}</div>
      <div className="qa-grid"><section className="qa-panel"><div className="qa-panel-title"><h2>Modules & requirements</h2><small>01 — INPUT</small></div>
        <form onSubmit={generate}>
          <div className="qa-module-inputs"><div className="qa-module-toolbar"><b>{inputModules.length} modules · {selectedModules.length} selected</b><button type="button" disabled={running || importing || inputModules.length >= 20} onClick={addModule}>+ Add module</button></div><div className="qa-module-picker">{inputModules.map(m => <button type="button" key={m.id} className={m.id === inputs.id ? 'active' : ''} onClick={() => setActiveModule(m.id)}>{m.name || 'Unnamed module'}<small>{m.story.trim().length >= 10 ? '✓' : '•'}</small></button>)}</div><label className="qa-check qa-module-include"><input type="checkbox" checked={inputs.selected !== false} disabled={running || importing} onChange={e => setInputs({ ...inputs, selected: e.target.checked })} />Include this module in generation</label><label htmlFor="qa-module-name">Module name</label><div className="qa-module-name-row"><input id="qa-module-name" value={inputs.name} maxLength={200} disabled={running || importing} onChange={e => setInputs({ ...inputs, name: e.target.value })} placeholder="e.g. Payments" />{inputModules.length > 1 && <button type="button" disabled={running || importing} aria-label="Remove current module" onClick={removeModule}>Remove</button>}</div></div>
          <div className="qa-tabs" role="tablist">{Object.entries(labels).map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={source === key} className={source === key ? 'active' : ''} onClick={() => setSource(key)}>{label}{inputs[key] ? ' ·' : ''}</button>)}</div>
          {source === 'figma' && <div className="qa-figma-url"><label htmlFor="qa-figma-url">Figma design / prototype URL for {inputs.name}</label><input id="qa-figma-url" type="url" disabled={running} value={inputs.figma_url} onChange={e => setInputs({ ...inputs, figma_url: e.target.value })} placeholder="https://www.figma.com/design/…?node-id=…" /><p className="qa-note">Use the module frame link. Pasted design text or JSON below remains usable without Figma access.</p></div>}
          <label htmlFor="qa-source">{labels[source]}<small>{source === 'story' ? 'Required' : 'Optional'}</small></label><textarea id="qa-source" disabled={running} maxLength={['story', 'success_criteria', 'navigation'].includes(source) ? 20000 : 40000} value={inputs[source]} onChange={e => setInputs({ ...inputs, [source]: e.target.value })} placeholder={source === 'story' ? '[Module name] As a user, I want to…\n\nAdd acceptance criteria, roles, rules, limits and failure behavior.' : source === 'success_criteria' ? 'List observable outcomes for this module.\nInclude exact limits, required fields, role restrictions and error behavior.' : source === 'navigation' ? 'One complete flow per line:\nHome → Product → Cart → Checkout\nCheckout → Error → Checkout' : `Paste ${labels[source]} text or exported design/interaction JSON. Use # headings to separate modules.`} />
          <div className="qa-input-footer"><span>{inputs[source].length.toLocaleString()} characters</span>{['confluence', 'figma'].includes(source) && <label className="qa-upload">↑ Import text / JSON<input type="file" accept=".txt,.md,.json" disabled={running} onChange={upload} /></label>}</div>
          <p className="qa-info">{['confluence', 'figma'].includes(source) ? source === 'figma' ? 'Enable Figma exploration to read this module’s link; otherwise paste its design text or JSON.' : 'Paste Confluence content for this module. Confluence links are not fetched.' : 'Include alternate paths, roles and edge conditions. Unspecified behavior becomes a clarification, not an invented assertion.'}</p>
          <div className="qa-existing-input"><div className="qa-module-toolbar"><b>Existing test cases</b><label className="qa-upload">{importing ? 'Importing…' : '↑ CSV / Excel'}<input type="file" accept=".csv,.xlsx" disabled={running || importing} onChange={importExisting} /></label></div><p className="qa-note">Import existing cases for analysis and improvement. A Module column assigns rows automatically; rows without it belong to this module.</p><small>{inputs.existing_cases.length} in {inputs.name} · {allExisting.length} total</small>{inputs.existing_cases.length > 0 && <details><summary>Review imported cases</summary><div className="qa-import-list">{inputs.existing_cases.map(c => <article key={c.id}><b>{c.name}</b><small>{c.source_file} · {c.source_sheet} · row {c.source_row}</small><p>{c.steps || 'Missing steps'}<br />Expected: {c.expected_result || 'Not specified'}</p><button type="button" disabled={running || importing} onClick={() => setInputs({ ...inputs, existing_cases: inputs.existing_cases.filter(x => x.id !== c.id) })}>Remove case</button></article>)}</div></details>}{importNotice && <div className="qa-import-notice" role="status">Read {importNotice.count} cases from {importNotice.filename}.{importNotice.warnings.map((w, i) => <p key={i}>{w}</p>)}</div>}</div>
          <p className="qa-info">Live agents · LangGraph · saved approval checkpoint</p>
          {mode === 'live' && <><label htmlFor="qa-model">Connected model</label><select id="qa-model" disabled={running} value={model} onChange={e => setModel(e.target.value)}><option value="">Server default{capabilities?.model ? ` · ${capabilities.model}` : ''}</option>{capabilities?.models?.map(m => <option key={m} value={m}>{m}</option>)}</select><label htmlFor="qa-case-target">Scenario planning target</label><select id="qa-case-target" disabled={running} value={targetCount} onChange={e => setTargetCount(Number(e.target.value))}><option value={0}>Evidence-led · no fixed count</option>{[100, 200, 500].map(n => <option key={n} value={n}>{n}+ cases when supported by evidence</option>)}</select><p className="qa-note">Large suites run in module batches. Missing source details are flagged; duplicate cases are not added to meet a count.</p></>}
          <p className="qa-note">{mode === 'live' ? capabilities?.live_available ? `Server model: ${capabilities.model}. Up to two review/repair rounds.` : 'A real server model is required. No silent switch to template output.' : 'No model decisions or semantic review. Drafts require manual refinement.'}</p>
          <div className="qa-browser-config"><label className="qa-check"><input type="checkbox" disabled={running || mode === 'offline'} checked={explore} onChange={e => setExplore(e.target.checked)} /><span><b>Explore each module’s Figma</b><small>Shift-left design & prototype evidence</small></span></label>
            {explore && <><label htmlFor="qa-budget">Prototype exploration budget per module</label><select id="qa-budget" value={budget} disabled={running} onChange={e => setBudget(Number(e.target.value))}>{[6, 12, 20, 30].map(n => <option key={n} value={n}>{n} navigation actions</option>)}</select><p className="qa-note">{capabilities?.browser.installed ? 'MCP installed.' : 'MCP needs verification.'} {capabilities?.figma_api_available ? 'Figma API configured.' : 'Private design structure needs a Figma API token or export.'} Add a Figma URL separately in each module.</p></>}
          </div><button className="qa-primary" disabled={running || importing || invalidModules}>{running ? 'Agents are working…' : '✦ Analyze modules & propose test strategy'}<span>→</span></button>{running && <button type="button" className="qa-stop" onClick={() => controller.current?.abort()}>Stop run</button>}{error && <p role="alert" className="qa-error">{error}</p>}
        </form></section>
        <section className="qa-panel qa-results"><div className="qa-panel-title"><h2>Test design workspace</h2><small>{pending ? running ? 'GENERATING APPROVED SUITES' : 'REVIEW — APPROVAL REQUIRED' : result ? `${result.mode.toUpperCase()} · ${result.readiness.toUpperCase()}` : '02 — OUTPUT'}</small></div>
          {pending && !running && <UnderstandingReview key={pending.run_id} pending={pending} onApprove={approve} disabled={running || !!inputsChanged} />}
          {failedRun && <button type="button" className="qa-primary" disabled={running || !!inputsChanged} onClick={retryApproved}>Retry approved generation →</button>}
          {inputsChanged && <p className="qa-info qa-stale" role="status">Inputs changed after this analysis. Analyze again before approval or generation.</p>}
          {(running || result || events.length > 0) && <div className="qa-result-tabs">{[['cases', 'Test suites'], ['documentation', 'Test plan'], ['coverage', 'Coverage'], ['navigation', 'Journeys'], ['review', 'Review'], ['existing', 'Existing tests'], ['evidence', 'Figma evidence'], ['activity', 'Agent activity']].map(([key, label]) => <button key={key} disabled={!result && key !== 'activity'} className={view === key ? 'active' : ''} onClick={() => setView(key)}>{label}</button>)}</div>}
          {view === 'activity' && events.length > 0 ? <div className="qa-activity" aria-live="polite">{events.map((event, i) => <article key={i}><span>{String(i + 1).padStart(2, '0')}</span><div><b>{event.agent}</b><small>{event.status}</small><p>{event.detail}</p></div></article>)}{running && <p className="qa-info">{lastEvent?.agent} is working. Results appear after coverage review.</p>}</div> : !result ? (!pending && <div className="qa-empty" role="status"><div>✦</div><h3>{running ? 'The team is getting started' : 'Your shift-left QA team'}</h3><p>Give the team your requirements and navigation. Seven specialists analyze each module, design smoke and regression cases, repair gaps, and write the test plan.</p><footer><span>Step-level expected results</span><span>Coverage obligations</span><span>Review & repair</span></footer></div>) : <>
            <div className="qa-metrics qa-four-metrics"><div><b>{result.coverage.smoke}</b><small>Smoke cases</small></div><div><b>{result.coverage.regression}</b><small>Regression cases</small></div><div><b>{result.coverage.linked}/{result.coverage.total}</b><small>Obligations linked</small></div><div><b>{result.repairs}</b><small>Repair rounds</small></div></div>
            {view === 'cases' && <><div className="qa-suite-picker">{['All', 'Smoke', 'Regression'].map(s => <button key={s} className={suite === s ? 'active' : ''} onClick={() => setSuite(s)}>{s === 'All' ? 'All suites' : s}</button>)}</div><div className="qa-tools qa-filter-tools"><input aria-label="Search cases" placeholder="Search name or description…" value={search} onChange={e => setSearch(e.target.value)} /><select aria-label="Module" value={module} onChange={e => setModule(e.target.value)}><option value="All">All modules</option>{modules.map(m => <option key={m}>{m}</option>)}</select><select aria-label="Testing type" value={kind} onChange={e => setKind(e.target.value)}><option value="All">All testing types</option>{types.map(t => <option key={t}>{t}</option>)}</select></div><div className="qa-list qa-suite-list">{[...new Set(cases.map(c => c.module))].map(m => <section key={m}><h3 className="qa-module-heading">{m}<small>{cases.filter(c => c.module === m).length} cases</small></h3>{cases.filter(c => c.module === m).map(c => <CaseDetail key={c.id} test={c} requirements={result.requirements} />)}</section>)}{!cases.length && <p>No matching test cases.</p>}</div></>}
            {view === 'documentation' && <div className="qa-list qa-document"><h2>{result.test_plan.title}</h2><p>{result.test_plan.overview}</p>{[['scope_in', 'In scope'], ['scope_out', 'Out of scope'], ['approach', 'Test strategy'], ['environments', 'Environment & data'], ['entry_criteria', 'Entry criteria'], ['exit_criteria', 'Exit criteria'], ['risks', 'Risks'], ['deliverables', 'Deliverables'], ['assumptions', 'Open assumptions']].map(([key, label]) => <section key={key}><h3>{label}</h3><ul>{result.test_plan[key].map((text, i) => <li key={i}>{text}</li>)}</ul></section>)}<button onClick={() => downloadTestPlan(result)}>↓ Download test plan (.md)</button>{result.strategy && <><h3>Supervisor decisions</h3>{result.strategy.decisions.map((d, i) => <p key={i}>{d}</p>)}</>}</div>}
            {view === 'coverage' && <div className="qa-list"><p className="qa-info">Linked obligations measure traceability. Semantic findings and assumptions still need review, even when every obligation is linked.</p>{result.coverage.modules.map(m => <div className="qa-module-coverage" key={m.name}><b>{m.name}</b><span>{m.linked}/{m.total} linked · {m.smoke} smoke · {m.regression} regression</span><progress aria-label={`${m.name} traceability`} value={m.linked} max={m.total} /></div>)}<div className="qa-step-table"><table><thead><tr><th>Source / obligation</th><th>Suite / type</th><th>Cases</th></tr></thead><tbody>{result.coverage.obligations.map(o => <tr key={o.id}><td>{o.target_id}<small>{o.module}</small></td><td>{o.suite}<small>{o.testing_type}</small></td><td>{o.case_ids.join(', ') || <b className="qa-error">Missing</b>}{o.needs_clarification && <small>Needs clarification</small>}</td></tr>)}</tbody></table></div><h3>Line-by-line source checklist</h3><p className="qa-note">Every nonempty source line is listed. A link is not semantic proof; unlinked lines require review.</p>{result.source_lines.map(line => <details key={line.id}><summary><small>{line.module} · {line.source}:{line.line}</small><strong>{line.status}</strong></summary><article><p>{line.text}</p><small>{line.requirement_ids.join(", ") || "No requirement link"}</small></article></details>)}<h3>Source requirements</h3>{result.requirements.map(r => <article key={r.id}><b>{r.id} · {r.module}</b><p>{r.text}</p><blockquote>{r.source_quote}</blockquote><small>{r.source} · {r.required_types.join(', ')}</small><p>{r.rationale}</p></article>)}</div>}
            {view === 'navigation' && <div className="qa-list"><h3>End-to-end journeys</h3>{result.journeys.map(j => <article key={j.id}><b>{j.id} · {j.name}</b><p>{j.critical ? 'Critical smoke journey' : 'Alternate journey'} · {j.module}</p><small>{j.edge_ids.join(' → ')}</small></article>)}<h3>Directed transitions</h3>{result.edges.map(e => <article className="qa-flow" key={e.id}><small>{e.id} · {e.module}</small><span>{e.origin}</span> → <span>{e.destination}</span><p>{e.action}<br />Condition: {e.condition || 'No condition specified'}<br />Evidence: {e.evidence_ids.join(', ') || 'Supplied sources; not UI-observed'}</p></article>)}{!result.edges.length && <p>No grounded navigation map was identified.</p>}</div>}
            {view === 'review' && <div className="qa-list"><p className="qa-info">{result.coverage.missing} missing obligations · {result.coverage.clarifications} cases need clarification · {result.findings.length} unresolved findings</p>{result.findings.map((f, i) => <article key={i}><b>{f.severity} · {f.owner}</b><p>{f.description}</p><small>{f.target_ids.join(', ')}</small></article>)}<h3>Scope and open questions</h3>{result.gaps.map((g, i) => <article key={i}><p>{g}</p></article>)}{result.review_history.map(r => <details key={r.round}><summary>Review round {r.round} · {r.findings.length} findings</summary><article><p>{r.decision}</p><ul>{r.findings.map((f, i) => <li key={i}>{f.description}</li>)}</ul></article></details>)}</div>}
            {view === 'existing' && <div className="qa-list"><p className="qa-info">Every imported case is assessed against the current module requirements. Reuse and improvement decisions are review recommendations, not execution results.</p>{result.existing_case_reviews.map(r => { const original = result.existing_cases.find(c => c.id === r.existing_case_id); const improved = result.cases.filter(c => c.existing_case_ids.includes(r.existing_case_id)); return <article key={r.existing_case_id}><b>{original?.name} · {r.disposition}</b><p>{r.reason}</p><small>{original?.source_file} · row {original?.source_row}</small><p>Linked generated cases: {improved.map(c => c.id).join(', ') || 'None — inspect whether existing intent is covered'}</p></article> })}{!result.existing_cases.length && <p>No existing test cases were imported for this run.</p>}</div>}
            {view === 'evidence' && <div className="qa-list"><p className="qa-info">Figma design/prototype observations are shift-left evidence, not an implemented UI or test execution result.</p>{result.evidence.map(e => <details key={e.id}><summary><strong>{e.id}</strong><small>{e.url}</small></summary><article><p>{e.observation}{e.truncated ? ' Snapshot truncated.' : ''}</p><pre className="qa-snapshot">{e.snapshot}</pre></article></details>)}{!result.evidence.length && <p>No UI was observed in this run. Enable Figma exploration or provide a module design export.</p>}{result.decisions.map((d, i) => <article key={i}><b>{d.evidence_id} · {d.action}</b><p>{d.reason}</p></article>)}</div>}
            <div className="qa-export"><span>{cases.length} filtered cases · Not executed</span><button disabled={!cases.length} onClick={() => downloadPlan(result, 'csv', cases)}>↓ Filtered CSV</button><button onClick={() => downloadPlan(result, 'json', result.cases)}>↓ Full JSON</button></div>
          </>}
        </section></div><footer className="qa-footnote">No finite run can guarantee every possible test. Missing evidence, unvisited paths, and unresolved findings remain explicit.</footer>
    </main></div>
  </div>
}
