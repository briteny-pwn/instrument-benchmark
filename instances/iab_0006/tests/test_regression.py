from support import assert_flag, group
def _make(name):
    def check(): assert_flag(name)
    check.__name__ = f"test_{name}"
    return check
for _name in group("regression"): globals()[f"test_{_name}"] = _make(_name)
