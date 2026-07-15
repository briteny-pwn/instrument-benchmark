# Fake Spectrometer Manual

This device follows yaq daemon ideas: it has a central wavelength property,
mapping data for wavelengths, triggered measurement, busy status, and measured
count data. Treat it as an instrument exposed through the raw command protocol
described separately.

Discover the concrete resource and identify it with `*IDN?`. A typical
resource identifiers follow this form:

```text
YAQ::fake-spectrometer::<instance>
```

Identity:

```text
*IDN? -> YAQ,fake-spectrometer,triggered_spectrometer,<serial>
```

Commands:

```text
*IDN?              returns identity
STATE?             returns a one-line state string
SET_CENTER <nm>    sets the central wavelength
CENTER?            returns CENTER <nm>
MEASURE            starts one measurement and returns MEASUREMENT_ID <id>
BUSY?              returns TRUE while acquisition is active, otherwise FALSE
WAVELENGTHS?       returns WAVELENGTHS <comma-separated nm values>
COUNTS?            returns COUNTS <comma-separated count values>
```

Set the central wavelength to `550.0 nm`, trigger one measurement, poll `BUSY?`
until it returns `FALSE`, then read both arrays. The spectrum has 551 points.
