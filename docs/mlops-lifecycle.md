# Phase 1 lifecycle

1. Validate YAML and estimator parameters before training side effects.
2. Generate synthetic transactions from a fixed seed and versioned generator.
3. Stratify into 60% train, 20% validation and 20% test by default. Transaction IDs
   are disjoint and excluded from features. Targets are excluded from preprocessing.
4. Hash each CSV and the canonical manifest. Save under its full content fingerprint.
   Existing content is verified and reused; corruption is an error, never overwritten.
5. Create the platform model, dataset version and RUNNING training record.
6. Fit imputation, scaling and one-hot encoding only on training rows. Train logistic
   regression and random forest with configured seeds and parameters.
7. Compute real validation and test precision, recall, F1, ROC AUC, average precision,
   false-positive rate, label/prediction rates and confusion counts.
8. Log parameters, metrics, input lineage, full config, manifest, runtime packages,
   signature, input example and serialized preprocessing + estimator to MLflow.
9. Register a candidate version, store platform lineage and finish the run.
10. Compare versions on validation metrics from the same dataset fingerprint. Test
    metrics remain reporting-only; there is no automatic threshold tuning or model selection.
11. A reviewer promotes a chosen candidate with a reason. The old champion is archived.
    Rejected and archived versions cannot be promoted. An active champion cannot be
    rejected/archived directly; replace it with an eligible candidate.
12. Synchronize registry aliases and retain audit history. Retry failed synchronization
    explicitly. There is no automatic production action in Phase 1.

The MLflow pyfunc flavor returns two-class probabilities. Apply the logged
`decision_threshold` to the positive-class column when deriving labels. The sklearn
flavor retains `predict_proba`; its default `predict` does not apply a custom threshold.
Models use skops serialization with explicit `numpy.dtype` and, for locally trained
random forests, `sklearn.tree._tree.Tree` allowances. Future serving
must load only governed artifacts from this registry and respect the saved input schema.

The generator is implemented in `aegis/data/fraud.py`. Source: project-generated synthetic
data, no external download or real customer information. Labels are probabilistic and
depend on transaction amount, time, distance, activity, age, merchant and card presence.
Do not interpret its metrics as a financial benchmark. Shift/corruption scenarios that
produce monitored incidents belong to Phases 2–4.
