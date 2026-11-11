Title: OP-7: Track the four container definitions in ops/docker-compose.yml
Labels: wave:1-no-gpu, area:ops, needs-services, size:S

## OP-7 -- Track the four container definitions in ops/docker-compose.yml

**Review cross-reference:** S-12. **Wave:** W1 do now, no GPU.

**Why.** The four containers (embedder, reranker, vector store, reference-resolution service) cannot be recreated from tracked files: the vector-store image tag is the moving `latest`, arguments, ports and volumes exist only in `docker inspect`, and a re-pull could jump the storage version over a 31 GB store (RV-6 F-A2; review S-12). Not re-run by the review beyond the lane's own inspect.

**Scope.**
- In:
  - A compose file with the four services exactly as inspected today (image, command, binds, ports, GPU reservation), the vector store pinned to v1.18.2 by digest, and no restart policy (a restart on a contended GPU is how the foreign-holder situation arises).
  - Read-only inspection only: `docker inspect`, `docker image inspect`, `docker compose config`.
- Out (explicitly):
  - Starting, stopping or recreating any container (this ticket never applies the file). Moving the vector store's data. Adding a restart policy.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `ops/docker-compose.yml`

**Commits** (① is a stub, committed before any real work):
① stub: compose file with the four service names and a header comment stating 'mirrors inspected state of <date>; never applied by this ticket'
② services transcribed from `docker inspect` output, one commit per service pair
③ digest pin and `docker compose config` output compared line by line with the inspected values

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `docker compose -f ops/docker-compose.yml config` succeeds and matches image, command, binds and GPU reservation of each running container (differences listed in the PR)

**Acceptance / falsification criterion.** `docker compose config` reproduces image digest, command, binds, ports and GPU reservation of all four running containers; the vector-store image is pinned by digest to v1.18.2; the PR lists any field that could not be reproduced. Falsified if a running container's inspected setting is absent from the file.

**Gates / depends on.** Depends on: none. Gates: EP-7, EP-3.

**Needs.** GPU: n · services up: docker daemon read-only inspection (no container is started or restarted) · operator sign-off: n (not a protected path). The version pin is a decision for the operator in PR review. · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** The file drifts from reality or is applied by a later agent with different GPU settings. Mitigation: header states it is a mirror; EP-7 documents 'verify with config diff before any recreate'. Rollback: delete the file.

**Docs to update in the same PR.** RUNBOOK containers section via EP-7; PROJECT-STATUS doc-map/entry via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
