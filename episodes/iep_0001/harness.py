import json
from repository.adapter import StageAdapter


class Transport:
    def __init__(self, fault): self.fault, self.n = fault, 0
    def connect(self): pass
    def start_move(self, target): self.target = target
    def poll(self):
        self.n += 1
        if self.fault == "poll_delay" and self.n == 1: return "delayed"
        if self.fault == "disconnect_after_start" and self.n == 1: return "disconnect"
        return self.target


def scenario(name, fault, expected):
    events = []
    a = StageAdapter(Transport(fault)); a.initialize(events.append); a.move(42, events.append)
    a.poll(events.append)
    if fault == "poll_delay": a.poll(events.append)
    if fault == "disconnect_after_start": a.recover(events.append)
    return {"id": name, "passed": all(item in events for item in expected) and events.index(expected[0]) >= 0, "events": events}


def main():
    results = [
        scenario("nominal_move", "none", ["ready", "move_start", "busy:true", "position:42", "busy:false"]),
        scenario("delayed_poll", "poll_delay", ["move_start", "busy:true", "poll:delayed", "position:42", "busy:false"]),
        scenario("disconnect_recovery", "disconnect_after_start", ["move_start", "busy:true", "error:disconnect", "recover", "ready", "busy:false"]),
    ]
    print("IAB_EPISODE_RESULTS=" + json.dumps({"scenarios": results}))


if __name__ == "__main__": main()
