# Difficulty analysis

Adapter: PVCAM

Failure modes: state_machine, property_state_desync

The `PrepareForAcq` callback must be called unconditionally to properly notify core whenever new acquisition is about to start.
