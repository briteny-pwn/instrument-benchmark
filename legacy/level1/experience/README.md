# Legacy Development Workspaces

This directory is no longer a formal benchmark execution boundary. Existing
solutions and transcripts were created with access to the repository and must
be treated as development-only, potentially contaminated results.

New blind runs are created under the ignored `runs/` directory by
`python -m benchmark_harness`. Only the three model-facing task files are
mounted into the authoring container, and hidden evaluation runs separately.
