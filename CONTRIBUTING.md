# Contributing to Gusby

Thank you for contributing to Gusby! This document outlines our standard development lifecycle, branch strategies, pull request processes, continuous integration gates, and code-review guidelines.

---

## 1. Branch Strategy & Development Workflow

Gusby follows a structured Trunk-Based Development workflow with short-lived feature branches:

1. **Main Branch (`main`)**:
   - The single source of truth for production-eligible code.
   - Protected: Direct pushes to `main` are prohibited.
   - Every commit on `main` must pass all CI checks before being eligible for production deployment to the Android Xperia host.

2. **Feature & Bugfix Branches**:
   - Branch naming conventions:
     - `feat/<short-description>` (e.g., `feat/metrics-endpoint`)
     - `fix/<short-description>` (e.g., `fix/chunker-boundary`)
     - `infra/<short-description>` (e.g., `infra/github-actions-ci`)
     - `docs/<short-description>` (e.g., `docs/sdlc-guide`)
   - Rebase or merge from `main` frequently to prevent drift.

---

## 2. Local Verification Before Opening a PR

Before opening a Pull Request, run the local verification suite:

```bash
# 1. Verify Go formatting
test -z "$(gofmt -l .)" || (echo "Run gofmt -w ." && exit 1)

# 2. Run Go vet
go vet ./...

# 3. Run unit tests
SKIP_LIVE_GROQ_TEST=true go test -race -v ./internal/... ./tests/admin/... ./eval/gusby/...

# 4. Verify Go binary build
CGO_ENABLED=0 go build -o bin/gusby ./cmd/gusby

# 5. Verify Frontend TypeScript types & production generation
cd frontend
npm ci
npm run typecheck
npm run generate
cd ..
```

---

## 3. Pull Request & Code Review Lifecycle

1. **Open a PR against `main`**:
   - Fill out the PR template completely.
   - Ensure the PR title follows conventional commits (`feat: ...`, `fix: ...`, `chore: ...`).
2. **Automated CI Checks**:
   - The `Gusby Production CI` GitHub Action will trigger automatically.
   - Required status checks:
     - `Backend CI (Go 1.27)`
     - `Frontend CI (Nuxt 4 SPA)`
     - `Database Migration Validation`
     - `Security & Vulnerability Scans`
     - `CI Passed / Merge Ready` (`ci-gate`)
3. **Peer Review Expectations**:
   - At least 1 approving review from a maintainer.
   - Verification of backward-compatible database migrations (see `docs/engineering/SDLC.md`).
   - Zero hardcoded secrets, plain passwords, or unmasked database URLs.
4. **Merge**:
   - Use "Squash and merge" or "Rebase and merge" to maintain a clean Git history.

---

## 4. GitHub Branch Protection Configuration Guide

Branch protection must be configured in repository settings (GitHub UI: `Settings` → `Branches` → `Add branch ruleset` or `Branch protection rule` for `main`):

1. **Require a pull request before merging**:
   - Require approvals: minimum 1.
   - Dismiss stale pull request approvals when new commits are pushed.
2. **Require status checks to pass before merging**:
   - Require branches to be up to date before merging.
   - Required check: `CI Passed / Merge Ready` (or individual jobs `Backend CI (Go 1.27)`, `Frontend CI (Nuxt 4 SPA)`, `Database Migration Validation`, `Security & Vulnerability Scans`).
3. **Do not allow bypassing the above settings**:
   - Include administrators.
4. **Require signed commits** (recommended).

---

## 5. Security & Sensitive Data Policy

- Never commit real `.env` files, production credentials, SSH private keys, or API tokens.
- Keep all local test database passwords confined to development mock configurations (matching `.env.example`).
- If a secret is accidentally committed, immediately revoke it, rotate credentials, and notify the repository owner.
