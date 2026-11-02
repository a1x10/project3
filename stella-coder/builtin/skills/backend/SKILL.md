---
name: backend
description: Designing and implementing backend services and HTTP APIs — routing, validation, persistence, auth, error handling (Express, FastAPI, NestJS, Django, Go).
when_to_use: building or changing API endpoints, services, middleware, background jobs
---
# Backend development

1. Map the request path: router → middleware (auth, validation) → handler/controller → service → data layer. Change the right layer.
2. Validate all input at the boundary (zod/pydantic/class-validator); return consistent error shapes with correct status codes (400 validation, 401/403 auth, 404, 409 conflict, 422, 500).
3. Never trust the client: authorize every resource access (owner checks), parameterized queries only, no string-built SQL/shell.
4. Keep handlers thin; business logic in services; side effects (email, queues) behind interfaces for testability.
5. Idempotency and transactions for multi-step writes; handle concurrency (unique constraints, optimistic locking).
6. Config from environment, never hard-coded secrets; log with context but without secrets/PII.
7. Tests: unit tests for services, integration tests hitting the HTTP layer (supertest/httpx TestClient) with a test database.
8. Verify by starting the server with StartProcess and exercising endpoints with curl, then stop it.
