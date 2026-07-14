# SimulatorDS XATTR Average Processor Manual

This task models a SimulatorDS processor that computes attributes from other
Tango devices, similar to formulas that use `XATTR(...)`.

Resources:

```text
TANGO://sim/sensor/a
TANGO://sim/sensor/b
TANGO://sim/processor/avg
```

Sensor attributes:

```text
READ_ATTR temperature -> TEMP <value> C
COMMAND State         -> ON
```

Processor attributes:

```text
READ_ATTR average_temperature -> AVG <value> C
READ_ATTR deviation           -> DEV <value> C
COMMAND State                 -> ON or ALARM
```

The processor average is the arithmetic mean of the two sensor temperatures.
The processor deviation is half of the absolute difference between the sensor
temperatures.

The processor state may be `ALARM` when its published attributes do not match
those formulas. Determine validity from the values rather than from state alone.
