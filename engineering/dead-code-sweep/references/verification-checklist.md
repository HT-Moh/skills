# Six-class reference search (convict-or-acquit checklist)

You have grep, not an AST. One grep never proves death. Run all six classes
per candidate symbol/file before writing DEAD:

1. **Direct references** — `grep -rn "<name>"` across all source roots,
   excluding the defining file and its own tests.
2. **Type-level references** — interfaces, generics, `typeof`, `Parameters<>`,
   annotations importing only the type (TS `import type`, Python `TYPE_CHECKING`).
3. **String literals** — route paths, event names, registry keys, config
   strings, CLI arguments that resolve to the symbol at runtime.
4. **Dynamic imports** — `import()`, `require()`, `importlib`, plugin loaders,
   `getattr`-style dispatch.
5. **Re-exports and barrels** — `export * from`, `__init__.py` re-exports,
   index files; a barrel hit means the search restarts from the barrel's
   consumers.
6. **Tests and mocks** — a symbol referenced ONLY by its own tests/mocks is
   still dead (delete both); referenced by another module's tests, it is alive.

Build/deploy references detectors miss (check before any file deletion):
- Dockerfile `COPY`/`RUN`/entrypoint targets
- CI workflow steps
- package.json scripts / Makefile targets
- Framework convention files (instrumentation, middleware, migrations dir)
- Compose/K8s volume mounts and commands

Known false-positive producers: knip on build-time entry scripts; vulture on
FastAPI/pytest decorators, Protocol members, and `__all__`-driven APIs (use
`--min-confidence 80` and treat anything decorator-adjacent as ALIVE unless
proven otherwise); ruff F401 on re-export `__init__.py` files.
