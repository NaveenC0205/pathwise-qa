export async function generatePlan(input, onEvent, signal, endpoint = '/api/qa/generate/stream') {
  const response = await fetch(endpoint, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input), signal,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Check the source fields and application URL.')
  }
  if (!response.body) throw new Error('Streaming is unavailable. Please retry.')
  const reader = response.body.getReader(), decoder = new TextDecoder()
  let buffer = '', result
  function consume(line) {
    if (!line.trim()) return
    const row = JSON.parse(line)
    if (row.type === 'event') onEvent(row)
    if (row.type === 'error') throw new Error(row.message)
    if (row.type === 'result') result = row.result
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let end
      while ((end = buffer.indexOf('\n')) !== -1) {
        consume(buffer.slice(0, end)); buffer = buffer.slice(end + 1)
      }
    }
    buffer += decoder.decode(); consume(buffer)
    if (!result) throw new Error('The run ended without a complete plan. Please retry.')
    return result
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock() }
}

const exportKeys = ['id', 'name', 'description', 'module', 'suite', 'testing_type', 'priority', 'level', 'role', 'preconditions', 'test_data', 'steps', 'expected_result', 'requirement_ids', 'edge_ids', 'journey_ids', 'evidence_ids', 'assumptions', 'status', 'origin', 'existing_case_ids']
export function csvPlan(cases) {
  const cell = (value, key) => {
    let text = key === 'steps' ? value.map((s, i) => `${i + 1}. ${s.action}\nExpected: ${s.expected_result}`).join('\n\n') : Array.isArray(value) ? value.join('\n') : String(value ?? '')
    if (/^\s*[=+@\-]/.test(text) || /^[\t\r]/.test(text)) text = "'" + text
    return '"' + text.replaceAll('"', '""') + '"'
  }
  return [exportKeys.join(','), ...cases.map(c => exportKeys.map(k => cell(c[k], k)).join(','))].join('\r\n')
}
export function downloadPlan(result, format, cases) {
  const content = format === 'json' ? JSON.stringify(result, null, 2) : csvPlan(cases)
  const url = URL.createObjectURL(new Blob([content], { type: format === 'json' ? 'application/json' : 'text/csv;charset=utf-8' }))
  const a = document.createElement('a'); a.href = url; a.download = `qa-test-plan.${format}`; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const sample = {
  story: '[Catalog] As a shopper, I can open a product and see its availability.\n[Cart] I can add an available product to the cart.\n[Checkout] I can complete checkout with a valid delivery address.\n[Payment] A successful payment creates exactly one order and shows confirmation.',
  confluence: '# Cart\nQuantity is an integer between 1 and 10 inclusive.\nOut-of-stock products cannot be added.\n# Checkout\nGuests must sign in before checkout.\nReturning from checkout preserves the cart and quantities.\n# Payment\nA failed payment displays a retry option without creating an order.\nRetrying a successful payment must not create a duplicate order.',
  figma: '# Catalog\nProduct details show availability and an Add to cart button.\n# Cart\nCart has a quantity input, total and Checkout button.\n# Checkout\nAddress form shows inline required-field errors.\n# Payment\nPayment failure screen has a Retry button.\nConfirmation has an order number and View order button.',
  navigation: 'Home → Product → Cart → Sign in → Checkout → Payment → Confirmation → Order details\nPayment → Payment error → Payment\nCheckout → Cart',
}

export function downloadTestPlan(result) {
  const p = result.test_plan
  const sections = [['scope_in','In scope'],['scope_out','Out of scope'],['approach','Test strategy'],['environments','Environment and test data'],['entry_criteria','Entry criteria'],['exit_criteria','Exit criteria'],['risks','Risks'],['deliverables','Deliverables'],['assumptions','Open assumptions']]
  const content = `# ${p.title}\n\n${p.overview}\n\nStatus: Draft — no tests executed.\n\n` + sections.map(([key, label]) => `## ${label}\n\n` + p[key].map(line => `- ${line}`).join('\n')).join('\n\n') + `\n\n## Suite inventory\n\nSmoke: ${result.coverage.smoke}\nRegression: ${result.coverage.regression}\nLinked obligations: ${result.coverage.linked}/${result.coverage.total}\n\nCases: ${p.case_ids.join(', ')}\n`
  const url=URL.createObjectURL(new Blob([content],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='qa-test-plan.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
