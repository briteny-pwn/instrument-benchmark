import json
from repository.adapter import CameraAdapter, Hardware


def run(name, fault, expected):
    events=[]; h=Hardware(reject=fault == "write_rejected"); a=CameraAdapter(h)
    a.initialize(events.append, callback_value=20 if fault == "callback_during_initialization" else None)
    if fault == "callback_during_initialization": a.property_callback(20, events.append)
    a.set_exposure(30 if fault == "write_rejected" else (20 if fault == "callback_during_initialization" else 10), events.append)
    return {"id": name, "passed": all(x in events for x in expected), "events": events}


def main():
    r=[run("normal_property", "none", ["ready", "write:exposure=10", "callback:exposure=10"]), run("callback_race", "callback_during_initialization", ["callback:ignored-before-ready", "ready", "callback:exposure=20"]), run("hardware_reject", "write_rejected", ["error:write-rejected", "property:exposure=20"])]
    print("IAB_EPISODE_RESULTS="+json.dumps({"scenarios":r}))
if __name__ == "__main__": main()
