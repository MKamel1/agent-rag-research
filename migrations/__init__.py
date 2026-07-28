# migrations — schema migration scripts + migrate.py, imported as `migrations.migrate` by
# rag/document_store.py and this package's own test suite. Needs this file so pytest's default
# "prepend" import mode inserts the repo root (this package's parent) onto sys.path, matching
# rag/contracts/app -- without it, `from migrations.migrate import migrate` only resolves when
# PYTHONPATH is set by hand (T-DOC81 review finding).
