## Summary of Changes
<!-- Provide a concise description of what this PR changes and why. Link to relevant issues or design decisions. -->

## Type of Change
- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature (non-breaking change adding functionality)
- [ ] Breaking change (fix or feature that causes existing functionality to change)
- [ ] Infrastructure / CI / Deployment update
- [ ] Documentation update

## Pre-Merge Verification Checklist
Please ensure all of the following checks pass before requesting review:

### Backend
- [ ] Go formatting verified (`gofmt -l .` returns zero files)
- [ ] Go vet clean (`go vet ./...` passes without warnings)
- [ ] All unit and integration tests pass (`go test -race ./internal/... ./tests/admin/... ./eval/gusby/...`)
- [ ] Backend binary builds cleanly (`CGO_ENABLED=0 go build -o bin/gusby ./cmd/gusby`)
- [ ] No secrets, passwords, or personal API keys embedded in code

### Frontend
- [ ] Dependency lockfile respected (`package-lock.json` committed)
- [ ] TypeScript typecheck passes (`npm run typecheck` in `frontend/`)
- [ ] Production static bundle generates cleanly (`npm run generate` in `frontend/`)

### Database (if schema or migrations were modified)
- [ ] Migration is backward-compatible (follows expand-and-contract pattern)
- [ ] Migration is recorded in `gusby.schema_migrations`
- [ ] Migration tested on clean PostgreSQL instance (`./scripts/migrate.sh`)
- [ ] Does not touch or modify the external `server_lab` database

### Security & Reliability
- [ ] No hardcoded tokens, passwords, or unmasked database URLs
- [ ] User input sanitized (SSRF checks, request body limits, CORS/CSRF headers)
- [ ] Graceful shutdown and error handling preserved
