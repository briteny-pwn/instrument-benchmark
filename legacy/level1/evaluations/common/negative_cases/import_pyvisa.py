"""Negative fixture: importing a forbidden framework must fail."""

import pyvisa  # noqa: F401


def run_experiment(output_path: str) -> dict:
    return {}
