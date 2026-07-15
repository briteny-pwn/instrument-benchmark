# SimulatorDS Temperature Device Manual

This device is documented with Tango/SimulatorDS concepts. Treat it as an
instrument exposed through a raw command protocol.

Discover the concrete simulator resource, then use `COMMAND info` to identify
the device. Resource names follow this form:

```text
TANGO://<authority>/temperature/<name>
```

Tango identity:

```text
COMMAND info -> CLASS SimulatorDS DEVICE sys/tg_test/temp/1
```

Attributes:

```text
READ_ATTR temperature       returns temperature as TEMP <value> C
WRITE_ATTR alarm_limit <v>  updates the configured alarm threshold in C
READ_ATTR alarm_limit       returns LIMIT <value> C
```

Commands:

```text
COMMAND State   returns ON or ALARM
COMMAND Status  returns a status string
```

The dynamic temperature attribute follows the configured sequence. The state is
`ALARM` only while the latest temperature is strictly above the configured
limit; a temperature equal to the limit remains `ON`.
