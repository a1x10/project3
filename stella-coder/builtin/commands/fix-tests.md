---
description: Run the test suite and fix failing tests
argument-hint: [test filter]
---
Run the project's tests ($ARGUMENTS). For each failure: read the error, find the root cause in the code (not the test, unless the test is wrong), fix it, and re-run until the suite passes. Never skip, delete or weaken tests to make them pass. Finish with the exact test results.
