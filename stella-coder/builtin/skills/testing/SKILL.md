---
name: testing
description: Writing and fixing automated tests — unit, integration, end-to-end; test design, fixtures, mocking, flaky tests, coverage.
when_to_use: adding tests, a failing or flaky test, test infrastructure, TDD requests
---
# Testing

1. Use the existing framework, file layout and naming (`*.test.ts`, `tests/test_*.py`, `_test.go`). Read neighbouring tests and copy their patterns and helpers.
2. Test behavior through public interfaces, not implementation details. One concern per test; descriptive names stating expected behavior.
3. Cover: happy path, edge cases (empty, boundaries, unicode, large input), error paths, and the specific bug being fixed (regression test that fails before the fix).
4. Isolation: temp directories, fresh fixtures, no shared mutable state, no real network; fake time where needed.
5. Mock only at system boundaries. Never assert on mocks you configured to return the asserted value.
6. Flaky tests: find the race/order dependency/time dependency; never "fix" by adding sleeps or retries blindly; never skip or delete tests to get green.
7. Run the narrowest test first (`TestRunner` with filter), then the full suite. Report exact pass/fail counts.
