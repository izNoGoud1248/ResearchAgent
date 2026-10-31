# Contributing

Pick an item from the Roadmap in the README, or open an issue first for anything larger than a fix.

## Getting started

Needs Docker Desktop, uv and Node.js.

```
uv sync
uv run scripts/initEnv.py
docker compose --profile app up -d --build --wait
```

`initEnv.py` creates `.env` with generated secrets. Add your own `OPENAI_API_KEY` to it. Never commit `.env`.

## Before opening a pull request

```
uv run pytest -m "not llm"
cd services/web && npm run build
```

If your change affects research quality, run the evaluation for the researcher you touched and include the summary table:

```
uv run python -m evals.evalHarness --researcher workflow
```

## Code style

- Python runs through `uv run`, never bare `python` or `pip`.
- Class based: no loose functions apart from small entry points.
- camelCase names, no underscores, unless a library fixes the name.
- Handle exceptions only at real boundaries: network, LLM calls and untrusted input.
- Tests use real Redis, Postgres and APIs. No mocks of this project's own code.
- TypeScript in strict mode, never `any`.
- Comments only where the reason is not obvious from the code.
- Secrets only through `.env`: never printed, logged or committed.
