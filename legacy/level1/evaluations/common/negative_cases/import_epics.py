import epics


def run_experiment(output_path: str) -> dict:
    return {"bad": bool(epics)}
