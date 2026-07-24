# Distributed Contract Version 1

The orchestrator validates the instance and evaluator manifests, hashes every
candidate-visible instance file, records all three repository commit IDs, and
then invokes:

```text
python -m instrument_benchmark_evaluator.cli run
  --request <absolute JSON path>
  --report <absolute JSON path>
```

The request identifies the run, instance, candidate, protocol version, limits,
and repeated-world seed range. Exit status `0` means an evaluator report was
produced; candidate failures remain normal report outcomes. Exit status `2`
means an incompatible or invalid request. Any other status is evaluator
infrastructure failure.

The evaluator owns raw evidence, worlds, oracle, scoring, and safety gates. The
orchestrator validates but never changes the evaluator score. It adds:

- `run_id`;
- instrument, instance, and evaluator Git provenance;
- orchestration protocol and evaluator exit status.

