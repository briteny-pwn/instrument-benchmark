class CameraAdapter:
    def __init__(self, hardware):
        self.hardware, self.ready, self.exposure = hardware, False, None

    def initialize(self, emit, callback_value=None):
        if callback_value is not None: self.property_callback(callback_value, emit)
        self.ready = True
        self.exposure = self.hardware.read_exposure()
        emit("ready")

    def set_exposure(self, value, emit):
        emit(f"write:exposure={value}")
        if not self.hardware.write_exposure(value):
            emit("error:write-rejected")
            emit(f"property:exposure={self.exposure}")
            return
        self.exposure = value
        self.property_callback(value, emit)

    def property_callback(self, value, emit):
        if not self.ready:
            emit("callback:ignored-before-ready")
            return
        self.exposure = value
        emit(f"callback:exposure={value}")


class Hardware:
    def __init__(self, reject=False): self.value, self.reject = 20, reject
    def read_exposure(self): return self.value
    def write_exposure(self, value):
        if self.reject: return False
        self.value = value; return True
