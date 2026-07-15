# Difficulty analysis

Adapter: AlliedVisionCamera

Failure modes: async_timing, property_state_desync, stale_data

AlliedVision callbacks can race property allowed-value updates during SDK invalidation callbacks. The merged repair serializes callback mutations and ignores callbacks before property initialization.
