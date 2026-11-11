"""EV-2 stub: seeded stratified sample (100 per Haiku label, random.seed(20261110)) from topic_labels.tsv,
joined read-only to papers (title, abstract[:600], categories_json); writes audit_sample.tsv WITHOUT the Haiku label.

PRE-REGISTERED CRITERION (EV-2, written before any labelling):
  Cohen's kappa (three-way, my labels vs Haiku) >= 0.70 AND binary off-vs-not-off agreement >= 0.92
  => labels ACCEPTED as-is. Otherwise report which band fails and recommend relabelling that band.
"""
