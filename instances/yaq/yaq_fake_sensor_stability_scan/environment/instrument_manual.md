# Fake Sensor Daemon Manual

This device follows yaq daemon ideas: an instrument component exposes identity,
state, channel metadata, and measurements. Treat it as an instrument exposed
through the raw command protocol described separately.

The simulator assigns the resource identifier at runtime. Discover resources,
open candidates, and use `*IDN?` to identify the `fake-sensor` device. Resource
identifiers follow this form:

```text
YAQ::fake-sensor::<instance>
```

Identity:

```text
*IDN? -> YAQ,fake-sensor,<daemon_name>,<serial>
```

Commands:

```text
*IDN?                 returns identity
STATE?                returns a one-line state string
CHANNELS?             returns comma-separated channel names
MEASURE? signal       returns MEASURED signal <value> ID <measurement_id>
BUSY?                 returns TRUE or FALSE
```

The `signal` channel is scalar and dimensionless. Collect five readings. The
signal is stable when the sample standard deviation is below `0.01`.
