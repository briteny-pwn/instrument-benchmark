# Difficulty analysis

1. **Instrument access:** Device.trigger ignores the trigger_value declared on a Component and always writes 1, contradicting the documented component contract.
2. **Why this is not a generic software bug:** This is control-framework state semantics, not generic arithmetic: the configured command value can encode a device-specific trigger transition.
3. **Instrument/framework:** scientific_control through ophyd.
4. **Gold behavior:** Carries the Component trigger_value into the trigger signal set call and adds a non-default-value regression test.
5. **Difficulty source:** state_machine, framework_semantic_mismatch; This is control-framework state semantics, not generic arithmetic: the configured command value can encode a device-specific trigger transition.
6. **Phase-1 simulation:** A stateful fake detector accepts only its configured trigger token and records idle-to-acquiring-to-complete transitions.
7. **Evaluation oracle:** The trace contains the configured token, exactly one trigger transition, completion is awaited, and default trigger behavior still works.
