"""`app/dashboard/` -- the Corpus Dashboard: observe AND control `app.ingest` runs over Tailscale.

Three modules, one seam each (`docs/DESIGN-corpus-dashboard.md`):
- `status.py` -- read-only snapshot of a run (`get_status(data_dir) -> dict`).
- `controller.py` -- start/pause/resume/stop/retarget a run via `run_manifest.json` + OS signals.
- `server.py` -- stdlib `http.server` composition root wiring both to `GET /api/status` /
  `POST /api/control` and the static frontend.

Neither `status.py` nor `controller.py` imports the other -- `run_manifest.json` on disk is their
only shared secret, same as the real `app.ingest` launcher and this dashboard never importing one
another (design doc, "The coordination contract").
"""
