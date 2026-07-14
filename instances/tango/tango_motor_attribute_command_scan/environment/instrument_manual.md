# SimuMotor Device Manual

This device is documented with Tango command/attribute/state concepts. Treat it
as an instrument exposed through a raw command protocol.

Discover the concrete simulator resource, then use `COMMAND info` to identify
the device. A typical resource is:

```text
TANGO://motor/axis/1
```

Identity:

```text
COMMAND info -> CLASS SimuMotor DEVICE motor/axis/1
```

Commands:

```text
COMMAND On              enables the motor
COMMAND Move <mm>       starts a move to a target position
COMMAND Stop            stops the motor after the scan
COMMAND State           returns OFF, ON, or MOVING
```

Attributes:

```text
WRITE_ATTR velocity <mm_per_s>
READ_ATTR velocity      returns VELOCITY <value> MM/S
READ_ATTR position      returns POSITION <value> MM
```

Scan positions:

```text
0.0, 1.5, -0.5
```

After each `COMMAND Move`, poll `COMMAND State` until it returns `ON`, then read
`READ_ATTR position`.
