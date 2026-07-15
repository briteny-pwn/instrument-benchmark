# Fake Motor + Sensor Alignment Manual

This setup follows yaq daemon ideas: each instrument component is a separate
daemon with its own resource. Treat both devices as instruments exposed through
the raw command protocol described separately.

Discover the concrete resources and classify them using `*IDN?`. Typical
resource identifiers follow these forms:

```text
YAQ::fake-continuous-hardware::<instance>
YAQ::fake-sensor::<instance>
```

Identity:

```text
*IDN? -> YAQ,<kind>,<name>,<serial>
```

Motor commands:

```text
*IDN?                 returns identity
STATE?                returns a one-line state string
LIMITS?               returns LIMITS <low>,<high>
UNITS?                returns UNITS mm
SET_POSITION <mm>     starts motion toward the destination
BUSY?                 returns TRUE while motion is active, otherwise FALSE
POSITION?             returns POSITION <mm>
DESTINATION?          returns DESTINATION <mm>
```

Sensor commands:

```text
*IDN?                 returns identity
CHANNELS?             returns comma-separated channel names
MEASURE? alignment    returns MEASURED alignment <value> ID <measurement_id>
BUSY?                 returns TRUE or FALSE
```

Scan positions:

```text
-1.0, 0.0, 1.0
```

For each motor position, send `SET_POSITION`, poll `BUSY?` until it returns
`FALSE`, read `POSITION?`, then read `MEASURE? alignment`.
