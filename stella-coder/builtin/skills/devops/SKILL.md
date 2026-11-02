---
name: devops
description: CI/CD pipelines, Docker, docker-compose, Kubernetes manifests, deployment scripts, GitHub Actions, infrastructure configuration.
when_to_use: Dockerfiles, CI workflows, deployment, environment/infra configuration
---
# DevOps

1. Read existing pipelines and infra files first; keep changes minimal and consistent with them.
2. Docker: pinned base image tags, multi-stage builds, non-root user, `.dockerignore`, layer caching (copy manifests → install → copy source), no secrets in images or build args.
3. CI (GitHub Actions etc.): pin action versions, least-privilege `permissions:`, cache dependencies, matrix for OS/versions when relevant, fail fast on lint/type/test.
4. Kubernetes: resource requests/limits, liveness/readiness probes, secrets via Secret objects/external secret stores, no `latest` tags.
5. Scripts: `set -euo pipefail` for bash, idempotent steps, clear logging, cross-platform paths when Windows is supported.
6. Never apply changes to real infrastructure (kubectl apply, terraform apply, deploys) without explicit user confirmation; prefer dry runs (`--dry-run`, `terraform plan`).
7. Verify locally where possible: `docker build`, `actionlint`, `kubectl apply --dry-run=client`.
