# Difficulty analysis

1. **Instrument access:** EpicsSignal.set fails when writing a short array to an EPICS PV whose readback returns the full native array; shape mismatch reaches numpy comparison and produces FailedStatus.
2. **Why this is not a generic software bug:** The oracle depends on EPICS Channel Access readback semantics, asynchronous set completion, array shape, and stale trailing buffer values.
3. **Instrument/framework:** scientific_control through ophyd.
4. **Gold behavior:** Compares the meaningful written prefix for array PV readback while preserving scalar and equal-shape comparisons, with regression tests.
5. **Difficulty source:** stale_data, framework_semantic_mismatch; The oracle depends on EPICS Channel Access readback semantics, asynchronous set completion, array shape, and stale trailing buffer values.
6. **Phase-1 simulation:** A fake array PV keeps a fixed-capacity buffer, updates only the written prefix, and returns full readback with controllable stale tail data.
7. **Evaluation oracle:** Set completes when the written prefix matches, fails on a changed prefix, ignores only the irrelevant tail, and preserves scalar/equal-array behavior.
