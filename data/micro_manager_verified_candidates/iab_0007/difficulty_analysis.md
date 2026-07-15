# Difficulty analysis

Adapter: MMCore

Failure modes: property_state_desync, framework_semantic_mismatch

Closes #887.

@tlambert03 Is this (together with the `onPropertyChanged("Core", "Autoshutter", f)` from #881) enough for #887?

I left out updating the system state cache because that requires mapping to a particular shutter's `State` property. Probably doable but better if we have the guarantee that the shutter in fact has a canonical `State` property.
