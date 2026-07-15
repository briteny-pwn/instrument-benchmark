import pyepics


def run_experiment(output_path: str) -> dict:
    return {"bad": bool(pyepics)}
