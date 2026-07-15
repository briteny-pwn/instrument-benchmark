"""Negative fixture: importing a forbidden framework must fail."""

import qcodes  # noqa: F401


def run_experiment(output_path: str) -> dict:
    return {}
