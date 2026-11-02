---
name: release-notes
description: Writing changelog entries and release notes from git history
when_to_use: preparing a release, updating CHANGELOG.md, summarizing merged changes
---
# Release notes

1. `GitLog` since the last tag (`git describe --tags --abbrev=0`).
2. Group by Keep a Changelog sections: Added, Changed, Fixed, Deprecated, Removed, Security.
3. One line per user-visible change, imperative, with PR/issue numbers when present. Skip chores/CI-only commits.
4. Call out breaking changes at the top with migration steps.
