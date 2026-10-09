# Isolated development and public backups

Work in an independent checkout and Python environment. Preserve sibling
checkouts, their environments and original datasets. Run heavy benchmarks and
test suites serially; avoid concurrent MSYS-heavy shells on this workstation.

The October 9 public source backup uses the existing safe public main history
and a new snapshot commit. Its application modules match the latest tested
local development state. It does not reproduce private branches or client
records. HANDOFF.md and docs/BACKUP_STATUS.md describe current scope.

A public backup must pass the repository privacy guard. Never bypass that guard
or force-publish a branch containing private history. Retain private job notes
and release payloads separately and audit source/document archives before
publishing a binary package.
