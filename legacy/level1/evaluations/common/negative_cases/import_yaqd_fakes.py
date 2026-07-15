import yaqd_fakes


def run_experiment(output_path: str) -> dict:
    return {"bad": bool(yaqd_fakes)}
