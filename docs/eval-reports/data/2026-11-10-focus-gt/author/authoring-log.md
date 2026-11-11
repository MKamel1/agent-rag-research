# EV-4 focus-gt authoring log (CHECKPOINT, incomplete)

## Collision-term table (chunk counts per label; papers per label) -- scans/scans-terms.tsv (tools/termscan.py)
term: on_papers / off_papers (off-topic papers using the word)
instrument 992/481; treatment 4982/927; intervention 4222/663; effect 4017/2037; exposure 1702/570; matching 2225/1746;
interference 1050/442; discontinuity 489/226; mediation 1300/344; shock 583/205; attribution 380/306; selection 4029/2107;
control 5016/2602; collider 849/75; backdoor 775/63; dose 692/77; causal attention 71/163 (more off than on);
causal structure 2134/170; causal ordering 460/49; counterfactual 3238/275; propensity 2584/110 (off hits mostly causal-in-disguise or "ignition propensity").
Weak collisions (off count tiny): potential outcome 3278/35, spillover 567/25, uplift 137/28, weak instrument 160/1,
synthetic control 419/15, regression discontinuity 360/8 -- no usable collision.
Strongest: matching, instrument, interference, exposure, treatment, intervention (large non-causal use); collider/backdoor are clean (particle colliders / security backdoors).

## Items
40 answerable items drafted (26 collision, 14 offtopic-legit); verify: 0 failures. Distractors verified (label off + regex in chunk) by tools/build.py.
Killed: none yet in items; abandoned candidates: 2006.11386-style math-only chunks (latex heavy), 1409.2441:c8 (math), 2511.14922:c9 (latex), backdoor second item.
Noted: some off-labelled papers use propensity/instrument in the causal sense (mislabels, e.g. 2601.01231, 2509.23424, 2604.03338) -- not used as distractors.

## Absent (focus-absent) -- NOT YET AUTHORED. See RESUME.md.
Scan outputs: scans/abs1.tsv, scans/abs2.tsv (exact-count candidates).
Specific patterns with 0 chunk hits: Hausman.Taylor, Blundell.Bond (but fuzzy `Blundell.{1,8}Bond` has 1 hit in 2506.23297:c2), Blanchard.Quah, Heckman.Ichimura (fuzzy has 2 hits), Koch.s postulates, Gelman.Hill (fuzzy: many hits -> drop), Coase, Neyman.s paradox, Imbens.Rubin (fuzzy: many hits -> drop), `instrumental variable.*(telescope|detector|spectrograph)`.
