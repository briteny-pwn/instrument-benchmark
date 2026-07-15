# Simulation reproduction

A stateful fake detector accepts only its configured trigger token and records idle-to-acquiring-to-complete transitions.

Evaluation oracle: The trace contains the configured token, exactly one trigger transition, completion is awaited, and default trigger behavior still works.
