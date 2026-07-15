from functools import lru_cache
from pathlib import Path
from evaluator.cpp_contract import Contract, load_spec, save_trace
INSTANCE = Path(__file__).resolve().parents[1]
SPEC = load_spec(INSTANCE)
@lru_cache(maxsize=1)
def contract(): return Contract(INSTANCE, SPEC)
def group(name): return SPEC["groups"][name]
def assert_flag(name): assert contract().value(name), f"semantic contract not satisfied: {name}"
def write_trace():
    events = [{"action": "contract_checkpoint", "name": name, "value": True} for name in group("state_trace") if contract().value(name)]
    save_trace(events)
