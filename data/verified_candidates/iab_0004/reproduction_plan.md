# Simulation reproduction

A fake array PV keeps a fixed-capacity buffer, updates only the written prefix, and returns full readback with controllable stale tail data.

Evaluation oracle: Set completes when the written prefix matches, fails on a changed prefix, ignores only the irrelevant tail, and preserves scalar/equal-array behavior.
