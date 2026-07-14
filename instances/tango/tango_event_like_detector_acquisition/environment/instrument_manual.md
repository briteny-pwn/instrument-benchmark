# SimDetector Acquisition Manual

This device is documented with Tango command/attribute/event concepts. The raw
simulator provides event-like records as query responses.

Discover the concrete simulator resource, then use `COMMAND info` to identify
the device. A typical resource is:

```text
TANGO://detector/sim/1
```

Identity:

```text
COMMAND info -> CLASS SimDetector DEVICE detector/sim/1
```

Commands:

```text
WRITE_ATTR exposure <seconds>
COMMAND StartAcquisition <frames>
COMMAND State
READ_EVENT frame
READ_ATTR frame_count
READ_ATTR mean_intensity
```

State behavior:

```text
COMMAND State -> RUNNING while acquisition is active
COMMAND State -> ON after all requested frames have been produced
```

Frame event format:

```text
FRAME <index> INTENSITY <value>
```

Collect four frame events after starting acquisition.
