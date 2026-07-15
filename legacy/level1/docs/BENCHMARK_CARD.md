# Instrument Access Benchmark Card

## Release identity

Formal runs use manifest schema v2. Each manifest binds the benchmark release
and Git state to the selected spec, every referenced hidden scenario, generator
code, dependency lock or requirements file, authoring/evaluation/model seeds,
container image digests, runtime, model identity, and decoding metadata. An
untagged checkout is identified as `unreleased+<commit>`, and a dirty checkout
is explicitly marked; neither should be represented as a published release.

## Intended claim and use

The benchmark measures whether a candidate can implement a raw instrument
client from a manual, interact with a hidden simulator, derive an experimental
result from observations, and clean up safely. It is intended for controlled,
repeated comparison of systems on the same released item/scenario set.

It does not by itself establish performance on real laboratory hardware,
native EPICS/Tango deployments, novel instrument families, or unsupervised
operation in safety-critical settings. It must not be used as a hardware safety
certification or as the sole basis for deployment.

## Task population

The current release candidate contains 19 items sourced from PyVISA, QCoDeS,
EPICS, Tango, and yaq patterns. Candidates see only a prompt, instrument manual,
and raw simulator protocol. Hidden evaluations use multiple scenarios,
independent trace/state evidence, required access and safety gates, and
isolated execution.

Most EPICS and Tango items use behavioral state-machine substitutes rather
than native framework runtimes. Native yaq and partial pyvisa-sim coverage do
not imply representative real-hardware coverage.

## Primary reporting

Reports must lead with:

- MIPR: macro mean of per-item pass rates;
- MHSPR: macro mean of per-item hidden-scenario pass rates;
- results grouped by capability and backend;
- paired item-level comparisons with bootstrap confidence intervals when
  systems share items;
- item difficulty, discrimination, and repeated-trial agreement;
- threshold and rubric-weight sensitivity.

Weighted scores are diagnostic. Required gates and minimum scenario pass rates
remain part of the official pass definition. Sensitivity output that omits
those gates is labeled diagnostic rescoring.

## Reproducibility and data policy

Use `python -m benchmark_harness.validity` and the protocol in
`docs/validity/README.md`. Preserve normalized records, analysis parameters,
release manifests, and output hashes. Pair systems on the same item population
and, where supported, the same explicit generation seed. Do not infer a model
seed when an adapter does not expose one.

Raw credentials, participant identity, proprietary prompts, and hardware
secrets must not enter published records. Human records use pseudonymous IDs
and require the study's consent/ethics process.

## Evidence status

Repository reference and negative suites are implementation checks, not model
or human baselines. No external model, human-subject, expert-review, native
EPICS/Tango, or real-hardware result is bundled as empirical evidence. Those
claims remain blocked until independently collected data is imported under the
published protocols. Empty templates are provided; they are not observations.

## Known threats to validity

- small and partly hand-authored item/scenario populations;
- possible item-family and backend imbalance;
- simulator-to-hardware and state-machine-to-native-runtime gaps;
- model contamination or release leakage;
- dependence on rubric weights, gates, thresholds, decoding, and run variance;
- unstable discrimination estimates with few systems;
- non-independent repeated trials if seeds or cached state are reused;
- selection bias in expert and human panels.

Any publication should identify the exact release, disclose missing evidence,
report uncertainty, and avoid generalizing beyond the tested population.
