# Notes for AI agents

Read these first, in order:

1. `docs/ARCHITECTURE.md`: how the app runs (GitHub Actions + Neon + OpenRouter, plus the local Docker mode), secrets, limits, code map, and the rules that must not break.
2. `PRODUCT.md`: who the owner is and what the product must do.
3. `docs/ROADMAP.md`: what is built and what is next.
4. `DESIGN.md`: the dashboard's visual system, if you touch `web/`. It may lag the current look.

Working rules:

- The owner is not a trader. Explain results in plain words; keep technical detail secondary.
- Never print or commit secrets. `.env` is local only; cloud secrets live in GitHub repo secrets.
- Neon is the live database. Treat writes and migrations against `NEON_DATABASE_URL` as production. Do not drop or rewrite data; the local `db` container is a backup, so ask before removing it.
- Keep collectors idempotent and every source's failure isolated.
- Free sources and free AI models only, unless the owner approves otherwise.
- Some files were changed by other agents or the owner (for example `0004_assets`, multi-asset support, `runner/openrouter.py`). Read before overwriting.
