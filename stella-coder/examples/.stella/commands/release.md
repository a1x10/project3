---
description: Prepare a release (version bump, changelog, checks)
argument-hint: <patch|minor|major>
---
Prepare a $ARGUMENTS release: run the full test suite and linter, bump the version in the manifest, update CHANGELOG.md from commits since the last tag (load the release-notes skill), and show me the diff. Do not tag, commit or push.
