# Gusby Release & Artifact Management

This document defines how releases are identified, packaged, cryptographically signed, and verified.

---

## 1. Principles of Release Management

1. **Exact Git Commit SHA Anchoring**:
   Every production release is permanently tied to an immutable 40-character Git commit SHA. Gusby never deploys an untracked moving branch pointer (e.g. `latest` or `head`).
2. **CI Verification Prerequisite**:
   The deployment agent only selects commits where the required CI workflow (`Gusby Production CI`) has succeeded.
3. **Cryptographic Checksum Verification**:
   All compiled binaries (`gusby-linux-arm64`, `gusby-linux-amd64`) and the static frontend SPA bundle (`gusby-frontend-spa.tar.gz`) are accompanied by a `checksums.sha256` digest file.
4. **Reproducible Release Metadata**:
   Each release produces a `release-metadata.json` documenting exact build time, compiler versions, commit SHA, and artifact sizes.

---

## 2. Release Workflow (`release.yml`)

Releases are triggered when a semantic version tag is pushed (e.g. `git tag v1.0.0 && git push origin v1.0.0`) or via manual `workflow_dispatch`:

```bash
dist/
├── checksums.sha256                 # SHA-256 hashes of all artifacts
├── gusby-frontend-spa.tar.gz       # Static Nuxt 4 SPA bundle
├── gusby-linux-amd64                # Pre-compiled 64-bit x86 Go binary
├── gusby-linux-arm64                # Pre-compiled ARM64 Go binary (Xperia)
└── release-metadata.json            # Release audit manifest
```

---

## 3. Sample `release-metadata.json`

```json
{
  "version": "v1.0.0",
  "commit_sha": "b3c491f8899116172fd33081242685a2c4d12345",
  "short_sha": "b3c491f",
  "built_at": "2026-11-04T00:00:00Z",
  "go_version": "go version go1.27.3 linux/amd64",
  "ci_verified": true,
  "artifacts": {
    "gusby-linux-arm64": {
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "bytes": 24117248
    },
    "gusby-frontend-spa.tar.gz": {
      "sha256": "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
      "bytes": 1048576
    }
  }
}
```

---

## 4. Querying CI-Verified Commits via GitHub API

The Android deployment runner identifies the latest eligible commit with:

```bash
gh run list \
  --repo FatPandaC8/KBA \
  --branch main \
  --workflow "Gusby Production CI" \
  --status success \
  --limit 1 \
  --json headSha \
  -q '.[0].headSha'
```

If the latest commit on `main` failed or has an in-progress CI run, the deployment agent will not deploy it until all required checks are green.
