# EV-4 focus-gt authoring log

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
50 items: collision 26, offtopic-legit 14, focus-absent 10. Difficulty 15 easy / 26 medium / 9 hard. verify: 50 items, 0 failures.
Collision distractors: >=2 off-labelled papers each, chunk verified to contain the term (regex) -- see distractor_evidence; lookalikes for offtopic-legit verified label on + term in chunk (tools/build.py).
Killed items: 0 items killed after drafting. Candidates abandoned before drafting (killed at selection): 1409.2441:c8 and 2511.14922:c9 (latex-only, no clean excerpt), a second backdoor item, 2008.00357 intro (generic), absent candidates Blundell-Bond (11 hits, a production-function paper may answer), Heckman-Ichimura (65 hits), Gelman-Hill (51), Imbens-Rubin (1439), instrument+telescope (56), Hodrick-Prescott/Stock-Yogo/Lord's paradox (on-topic answers exist). Total abandoned candidates: 12.
Corpus observations: several off-labelled papers use propensity score matching / instruments in the causal sense (2601.01231, 2509.23424, 2604.03338: label noise, not used). "causal attention" appears in more off papers (163) than on (71).

## Absent items
Scans: scans/abs1.tsv, abs2.tsv (candidate screens), abs3-5.out (final spec + broad counts; first-pass SPEC HIT lines list chunk ids). Each item records a specific scan and a broad scan; counts re-run by gt_tools verify. Non-zero specific hits (Hausman-Taylor 2, Blanchard-Quah 3, Bernanke-Mihov 1, sunspot 1, lunar 3) were read: citations in passing or spurious word collisions.
