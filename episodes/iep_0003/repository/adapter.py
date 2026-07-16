class Device:
    def __init__(self): self.lease=False; self.closed=False; self.timeout=100
    def acquire(self, emit, timeout=None, second=False):
        self.lease=True; emit("acquire:second" if second else "acquire")
        if timeout is not None and timeout < 100: emit("timeout:device"); self.abort(emit)
    def abort(self, emit):
        self.lease=False; emit("abort"); emit("lease:released")
    def shutdown(self, emit):
        self.lease=False; emit("shutdown"); emit("lease:released"); self.closed=True; emit("closed")
