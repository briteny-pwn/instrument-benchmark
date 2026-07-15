# Difficulty analysis

1. **Instrument access:** A previous per-Component timeout change removed the effective class-wide EpicsSignal default. Users need both class defaults and per-device overrides, with a regression test for the standard set_defaults path.
2. **Why this is not a generic software bug:** Timeout configuration crosses Component construction, Device traversal, and EPICS signal connection lifecycle. The repair must preserve override precedence and raise on genuinely disconnected children.
3. **Instrument/framework:** scientific_control through ophyd.
4. **Gold behavior:** Restores signal default timeout handling, adds Device-level connection timeout defaults/overrides, and tests the precedence and timeout paths.
5. **Difficulty source:** timeout, framework_semantic_mismatch, device_initialization; Timeout configuration crosses Component construction, Device traversal, and EPICS signal connection lifecycle. The repair must preserve override precedence and raise on genuinely disconnected children.
6. **Phase-1 simulation:** Use mocked connected/disconnected child signals and a deterministic clock. Exercise class default, instance override, immediate connection, and timeout paths.
7. **Evaluation oracle:** Upstream tests plus observed timeout propagation, exception timing, and child connection-call trace.
