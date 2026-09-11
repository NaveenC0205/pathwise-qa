# Pathwise QA

A standalone shift-left QA design workspace. Build module-wise smoke and regression suites from user stories, success criteria, navigation, Confluence content, Figma designs and existing CSV/XLSX cases.

## Run locally

```sh
uv sync --extra test
npm --prefix frontend ci
npm --prefix qa-browser ci
cp .env.example .env  # For a fresh installation only; retain an existing .env.
# Set your provider/model in .env. Credentials remain server-side.
uv run uvicorn app.main:app --host 127.0.0.1 --port 8010
# In another terminal:
npm --prefix frontend run dev
```

Open http://127.0.0.1:5174/. The application is independent of RetailMind and Shop QA. Production static assets can be built with `npm --prefix frontend run build`; the Python service then serves the built UI from `/` on port 8010.

## Workflow

1. Add modules. Each module has a name, user stories, success criteria, navigation, Confluence text, Figma text/JSON and a Figma URL. Select which modules to include.
2. Import existing `.csv` or `.xlsx` cases. A Module column assigns rows to matching modules; unmatched modules are created for you to complete. Rows without a module belong to the active module. Review file/row references and import warnings.
3. Select a server-enabled model and an optional scenario planning target (100, 200 or 500+). Targets guide planning; unsupported filler is not counted as coverage.
4. Optionally enable per-module Figma exploration. No deployed application is required.
5. Follow real agent events through generation and review/repair. A run can be stopped. Large module batches have a 60-minute overall limit.
6. Review suites, step-level expected results, source-line traceability, navigation journeys, existing-case assessments, unresolved findings and the test plan. Export filtered CSV, full JSON or test-plan Markdown.

## Seven specialist agents

Each agent is defined separately in `backend/app/qa/agents/`:

| Agent | File | Responsibility |
|---|---|---|
| QA supervisor | `supervisor.py` | Plan selected module priorities, test focus and scenario estimates |
| Requirements analyst | `requirements.py` | Atomic requirements, success criteria, source quotes, test obligations and omitted-line repair |
| Figma explorer | `figma_explorer.py` | Grounded design navigation, branches, journeys and evidence gaps |
| Smoke designer | `smoke.py` | Critical end-to-end release-confidence cases |
| Regression designer | `regression.py` | Granular module/batch scenarios and existing-case improvements |
| Coverage reviewer | `reviewer.py` | Semantic review, imported-case assessment, missing obligations and repair requests |
| Test plan writer | `test_plan.py` | Scope, approach, environments, entry/exit criteria, risks and deliverables |

`browser_decision.py` is the Figma explorer's bounded next-action policy, not an additional claimed specialist. `pipeline.py` coordinates dependencies, two concurrent model calls, small regression batches, structured-output correction and up to two designer repair rounds. Source-line omissions trigger an additional analyst pass. Model responses never execute Python, shell or arbitrary browser code.

## Figma evidence

- Paste module design descriptions or exported JSON to work without external credentials.
- For private design structure, configure `FIGMA_ACCESS_TOKEN` with `file_content:read` access to the relevant file. Only official `https://api.figma.com` read endpoints receive this token. Use a module frame URL (`node-id`) to avoid broad-file truncation.
- The official `@playwright/mcp` package explores public/accessibly exposed prototype navigation in an isolated Chrome session. Install Chrome on the server host. It offers only observed navigation references to the model, blocks mutation requests and arbitrary origins, and never attaches to your personal browser profile.
- Figma canvas internals may not appear in accessibility snapshots; authenticated or canvas-only content requires the API or an export. Blocked, unvisited and truncated content stays in the review gaps. Design evidence is not proof of implemented behavior.
- Confluence URLs are not fetched in this version; paste the content for each module.

References: [Figma file endpoints](https://developers.figma.com/docs/rest-api/file-endpoints/), [Figma authentication](https://developers.figma.com/docs/rest-api/authentication/), [official Playwright MCP](https://github.com/microsoft/playwright-mcp).

## Models and bounds

`LLM_PROVIDER=openai` uses an OpenAI-compatible server endpoint; `LLM_PROVIDER=ollama` uses a local Ollama model. `QA_MODELS` lists models enabled in the UI; the server rejects arbitrary unconfigured model names. Secrets are read only from `.env`/server environment. The local installation retains its already configured model credential in its own ignored `.env`.

The engine supports suites over 100 cases through module batches, not one giant model response. Input bounds: 20 modules, 180,000 combined module characters, 200 imported cases per file, 2 MB files, and 100 atomic requirements per analysis response. Oversized analysis is not silently accepted as complete. Model/provider/context limits and semantic ambiguity may still require splitting a project.

Offline mode is transparent template scaffolding. Live mode is the actual specialist-model workflow. All cases remain drafts and include names, descriptions, module, suite, testing type, priority, level, role, setup, data, per-step expected results, overall result, traceability, provenance and assumptions. Neither mode executes generated tests or guarantees exhaustive correctness. A fully linked matrix is not a QA approval.

## Validation

```sh
uv run pytest
npm --prefix frontend test
npm --prefix frontend run build
```

Tests cover module isolation, exact source inventories, 100+ case output, imports (CSV and XLSX), formula exclusion, reference validation, streamed events, existing-case assessment, deterministic coverage repair and browser action restrictions. Local browser checks cover the editor, offline generation, documentation, CSV import and mobile layout. Playwright MCP is checked against a local navigation fixture. Real Figma account access is not verified without a supplied accessible design.

## Deployment scope

This is a local, single-user tool. Inputs/results are held for the active run and downloadable; projects and run history are not persisted. Bind to loopback by default. Before shared hosting, add identity, per-user model budgets, persistent project storage and stronger outbound browser isolation. The Python service and Playwright runtime require Python-capable hosting; this is not a static-only Sites deployment.
