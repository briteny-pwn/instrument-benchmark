# Validity Study Protocols

These protocols separate executable study infrastructure from empirical
claims. Files under `templates/` contain no observations. A study remains
`blocked_no_data` until independently collected records are supplied.

## Baseline record protocol

One JSONL row represents one system/item/trial result. Required fields are
`system_id`, `item_id`, `trial_id`, and `passed`. Recommended fields are
`benchmark_release`, `provider`, `agent`, `seed`, `pair_id`, `backend`,
`capabilities`, `score`, `hidden_scenario_pass_rate`, `scenario_outcomes`,
`dimension_scores`, `rubric`, and `pass_threshold`.

`pair_id` must identify trials deliberately matched across systems. Do not
manufacture a seed or pairing identifier when a runtime does not expose one.
The analyzer always pairs comparisons at the shared-item level; explicit
pairing metadata is retained for stricter downstream studies.

Normalize run directories, report JSON, JSONL, JSON, or CSV:

```bash
python -m benchmark_harness.validity import runs/ external.csv \
  --output validity-data/baselines.jsonl
```

Compute MIPR, MHSPR, backend/capability groups, item difficulty and
discrimination, test-retest agreement, and paired item bootstrap comparisons:

```bash
python -m benchmark_harness.validity analyze \
  --input validity-data/baselines.jsonl \
  --output validity-data/analysis.json \
  --bootstrap-samples 10000 --seed 1729
```

Run diagnostic rubric and threshold sensitivity:

```bash
python -m benchmark_harness.validity sensitivity \
  --input validity-data/baselines.jsonl \
  --output validity-data/sensitivity.json \
  --thresholds 0.70,0.75,0.80,0.85,0.90 \
  --perturbations=-0.20,0.20
```

MIPR is the macro mean of item pass rates, so items with more retries do not
receive more weight. MHSPR is the macro mean of available item-level hidden
scenario pass rates. Bootstrap intervals resample shared items. With very few
items or systems, intervals and discrimination are descriptive only.

## Native/runtime and hardware calibration

Pre-register the selected release, item subset, simulator/native/hardware
mapping, expected equivalence tolerances, repetitions, environmental controls,
instrument inventory, firmware/software versions, calibration status, and
safety supervision. Run the same candidate artifact against both conditions
when technically possible.

Record every attempt using `templates/hardware_calibration.csv`. A comparison
must include matched `pair_id` values, observed scores/pass states, deviations,
operator interventions, and incident status. Report exclusions and failures;
do not silently remove hardware faults. Credentials, serial numbers that are
sensitive, and operator identities must be pseudonymized.

Use `protocol_version=1`, `record_type=hardware_calibration`, and
`data_status=observed` only after the attempt occurs. `condition` is one of
`simulator`, `native_runtime`, or `hardware`. `candidate_sha256` binds the same
candidate across paired conditions, and `evidence_uri` points to an access-
controlled evidence bundle rather than embedding secrets.

Native-framework equivalence should compare protocol-visible behavior, state
transitions, timing/error semantics, and final safety state. Real-hardware
calibration additionally requires current calibration evidence, a written
hazard assessment, emergency-stop procedure, and qualified supervision.

## Expert review

Freeze the release before review. Recruit reviewers independently of item
authors when possible, record relevant domain expertise and conflicts using
pseudonymous IDs in `templates/expert_review.csv`, and randomize item order. Each reviewer assesses manual
clarity, realism, capability alignment, oracle correctness, rubric relevance,
safety completeness, ambiguity, and leakage risk using an anchored 1--5 scale.

Keep ratings separate from adjudication. After independent review, log each
accepted/rejected change and rationale. Report reviewer count, missing ratings,
agreement, conflicts, and item exclusions. A filled template without reviewer
provenance and independent collection is not expert-validation evidence.

Use `protocol_version=1`, `record_type=expert_review`, and
`data_status=observed`. For positive-quality fields, 1 means unacceptable and
5 means exemplary. For `ambiguity_risk` and `leakage_risk`, 1 means negligible
and 5 means critical. `recommendation` is `accept`, `revise`, or `reject`;
adjudication must not overwrite the independent rating.

## Minimum release evidence

A publication-ready release should archive:

1. manifests and normalized baseline records for all reported systems;
2. repeated trials sufficient to estimate run variance;
3. analysis and sensitivity outputs with commands and seeds;
4. completed expert reviews and adjudication log;
5. native/hardware calibration records for any transfer claim;
6. contamination/leakage review and all declared exclusions.
