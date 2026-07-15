# Difficulty analysis

Adapter: DemoCamera

Failure modes: state_machine, async_timing, property_state_desync

The DemoCamera XY stage reports user-space positions while a move is active. The polling thread must wake on move start, serialize access to the timeout state, and notify Busy/position callbacks without stale coordinates.
