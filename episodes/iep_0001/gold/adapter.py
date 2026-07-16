class StageAdapter:
    def __init__(self, transport):
        self.transport = transport
        self.state = "disconnected"
        self.busy = False
        self.position = None

    def initialize(self, emit):
        self.transport.connect()
        self.state = "ready"
        emit("ready")

    def move(self, target, emit):
        self.transport.start_move(target)
        self.busy = True
        emit("move_start")
        emit("busy:true")

    def poll(self, emit):
        event = self.transport.poll()
        if event == "delayed":
            emit("poll:delayed")
            return
        if event == "disconnect":
            self.state = "error"
            self.busy = False
            emit("error:disconnect")
            return
        self.position = event
        self.busy = False
        self.state = "ready"
        emit(f"position:{event}")
        emit("busy:false")

    def recover(self, emit):
        self.transport.connect()
        self.state = "ready"
        self.busy = False
        emit("busy:false")
        emit("recover")
        emit("ready")
