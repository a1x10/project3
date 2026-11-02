---
name: documentation
description: Writing and updating documentation — READMEs, API docs, docstrings, architecture notes, changelogs, usage examples.
when_to_use: requests to document, explain for others, write README/guide/changelog
---
# Documentation

1. Read the code you document; every claim must match actual behavior, flags and defaults. Run examples when feasible.
2. Audience first: README = what it is, install, quick start, configuration, common tasks, troubleshooting. API docs = parameters, return values, errors, example.
3. Prefer short sections, task-oriented headings, runnable code blocks with language tags, tables for options.
4. Match the existing doc style, tone and language (keep Russian docs in Russian, etc.).
5. Docstrings/comments explain why and non-obvious constraints, not what the next line does.
6. Update related docs when behavior changes (README, CHANGELOG, --help text).
