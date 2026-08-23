# Tooling — the gates per language

The safety net (Phase 1) and the final gates (Phase 4) are only real if they run actual commands.
Detect the stack first (below), then run **test · lint · types · format** every refactor step and
in full at the end. Always prefer the project's *own* configured commands — read
`package.json` scripts, `Makefile`, `pyproject.toml`, `justfile`, CI config — over these defaults.

## Detect the stack

Look for the manifest, then use its ecosystem's tools:

| Marker file | Ecosystem |
|---|---|
| `package.json` / `tsconfig.json` | JS / TypeScript (npm, pnpm, yarn, bun) |
| `pyproject.toml` / `setup.py` / `requirements.txt` | Python |
| `go.mod` | Go |
| `Cargo.toml` | Rust |
| `pom.xml` / `build.gradle` | Java / Kotlin (JVM) |
| `Gemfile` | Ruby |
| `composer.json` | PHP |
| `*.csproj` / `*.sln` | C# / .NET |

Run the project's CI script if one exists — it usually already chains these gates.

## Gate commands (defaults — override with project config)

| Ecosystem | Test | Lint | Types | Format |
|---|---|---|---|---|
| **JS/TS** | `npm test` / `vitest run` / `jest` | `eslint .` | `tsc --noEmit` | `prettier --check .` |
| **Python** | `pytest -q` | `ruff check .` | `mypy .` / `pyright` | `ruff format --check` / `black --check .` |
| **Go** | `go test ./...` | `go vet ./...` / `golangci-lint run` | (compiler) | `gofmt -l .` |
| **Rust** | `cargo test` | `cargo clippy -- -D warnings` | (compiler) | `cargo fmt --check` |
| **Java/Kotlin** | `mvn test` / `gradle test` | `checkstyle` / `detekt` | (compiler) | `spotless:check` |
| **Ruby** | `rspec` / `rake test` | `rubocop` | `sorbet tc` (if used) | `rubocop -a` (check) |
| **PHP** | `phpunit` | `phpcs` / `phpstan analyse` | `phpstan` / `psalm` | `php-cs-fixer --dry-run` |
| **C#/.NET** | `dotnet test` | `dotnet format --verify-no-changes` | (compiler) | `dotnet format` |

## Measuring the charter thresholds

The charter has numeric limits; measure them, don't eyeball:

- **File length** — `wc -l` across source files; sort desc to find the >300-line offenders:
  `git ls-files '*.py' '*.ts' '*.js' '*.go' '*.rs' '*.java' | xargs wc -l | sort -rn | head`.
- **Function length / arg count / nesting / cyclomatic complexity** — use a complexity tool where
  available: `radon cc -s` (Python), `eslint` `complexity`/`max-lines-per-function`/`max-depth`/
  `max-params` rules (JS/TS), `gocyclo` (Go), `cargo clippy` cognitive-complexity lints (Rust),
  `lizard` (language-agnostic, covers most of the above in one run).
- **Duplication** — `jscpd` (many languages) or the linter's copy-paste detector.
- **Dead code / unused imports** — the linter's unused rules; `vulture` (Python), `ts-prune` (TS),
  `deadcode`/`staticcheck` (Go).
- **Import boundaries / cycles** — `madge --circular` (JS/TS), `import-linter` (Python),
  `go list`/`godepgraph` (Go). Use to verify charter section G (no cycles, no reach-through).

## Characterization tests (when the net is missing)

When there's no suite to protect a change, pin current behavior before refactoring:

1. Find the seams — the public functions/endpoints around the target code.
2. Call them with representative inputs; **assert whatever they currently return** — even if it
   looks wrong. You're recording behavior, not judging it.
3. For hard-to-instantiate code, characterize at the highest reachable seam (HTTP handler, CLI,
   public method) rather than deep internals.
4. Golden-master / snapshot tests are ideal for wide output: capture current output, diff against it.
5. Run them green, commit, *then* start refactoring. If a refactor turns one red, you changed
   behavior — revert and go smaller.

These tests are scaffolding to make the refactor safe. Keep the valuable ones; note in the report
which were temporary.

## If no runnable gate exists

If the project has no tests and no linter and you cannot establish any safety net, **stop and tell
the user** before mutating code — offer to set up a minimal harness first. Refactoring blind
violates the prime directive (behavior preserved *and proven*).
