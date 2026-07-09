# Environment

This directory contains the task environment materials.

The model-visible material is:

- `instrument_manual.md`: simplified manual for the target instrument.

The instrument simulator is provided by the external runtime during execution
and is not part of the visible task material. Candidate code should interact
with the instrument through the PyVISA API described in the prompt and manual.
