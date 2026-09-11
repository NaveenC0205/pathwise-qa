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
5. Click **Analyze modules & propose test strategy**. Live agents explain the application, requirements, source quotes, navigation and proposed smoke/regression coverage. No test cases are generated at this stage.
6. Edit the understanding and strategy, add corrections, and explicitly approve. Source edits require a new analysis. The saved LangGraph checkpoint resumes into generation only after approval.
7. Follow real model events through generation and review/repair. Large module batches have a 60-minute overall limit.
8. Review suites, step-level expected results, source-line traceability, navigation journeys, existing-case assessments, unresolved findings and the test plan. Export filtered CSV, full JSON or test-plan Markdown.

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

`browser_decision.py` is the Figma explorer's bounded next-action policy, not an additional claimed specialist. `workflow.py` uses a compiled LangGraph StateGraph with a durable SQLite checkpoint and human-approval interrupt. Each specialist runs a LangGraph reasoning/validation/correction loop in `agents/runtime.py`. `pipeline.py` coordinates dependencies, two concurrent model calls, small regression batches, structured-output correction and up to two designer repair rounds. Source-line omissions trigger an additional analyst pass. Model responses never execute Python, shell or arbitrary browser code.

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

The UI and API accept live model runs only; missing credentials or provider failures return errors, never template cases. The old offline helper remains solely for regression fixtures and is not exposed by the API. All cases remain drafts and include names, descriptions, module, suite, testing type, priority, level, role, setup, data, per-step expected results, overall result, traceability, provenance and assumptions. The application does not execute generated tests or guarantees exhaustive correctness. A fully linked matrix is not a QA approval.

## Validation

```sh
uv run pytest
npm --prefix frontend test
npm --prefix frontend run build
```

Tests cover module isolation, exact source inventories, 100+ case output, imports (CSV and XLSX), formula exclusion, reference validation, streamed events, existing-case assessment, deterministic coverage repair and browser action restrictions. Workflow tests additionally verify that designers never run before approval, SQLite state survives reopening, approved edits reach generation, and invalid citations or model failures cannot produce a successful draft. Playwright MCP is checked against a local navigation fixture. Real Figma account access is not verified without a supplied accessible design.

## Deployment scope

This is a local, single-user tool. Workflow inputs, analyses, approved interpretations and completed results are saved under `outputs/agent-checkpoints.sqlite` (ignored by Git). The browser remembers the latest run ID to restore pending approval after refresh. Unsaved edits are not persisted. Failed generation can retry from the approved checkpoint; the generation stage restarts, while approved analysis stays fixed. Run a single API worker: the local duplicate-resume lock is process-local. Bind to loopback by default. Before shared hosting, add identity, per-user model budgets, persistent project storage and stronger outbound browser isolation. The Python service and Playwright runtime require Python-capable hosting; this is not a static-only Sites deployment.

## Framework and API

- `POST /api/qa/generate/stream`: starts live analysis and returns an `awaiting_approval` run.
- `GET /api/qa/runs/{run_id}`: retrieves the saved run.
- `POST /api/qa/runs/{run_id}/approve/stream`: validates reviewed requirements, navigation and strategy, then resumes the LangGraph interrupt with explicit approval.
- `POST /api/qa/runs/{run_id}/retry/stream`: retries a failed generation stage using its saved approval; it cannot bypass initial approval.
- Agent decisions, repair events and model identity stream to the UI as newline-delimited JSON. This is stage/event streaming, not token-by-token text streaming.
- No LangSmith tracing or third-party tracing is enabled by this application.

Framework reference: [LangGraph interrupts and resuming saved state](https://docs.langchain.com/oss/python/langgraph/interrupts).
