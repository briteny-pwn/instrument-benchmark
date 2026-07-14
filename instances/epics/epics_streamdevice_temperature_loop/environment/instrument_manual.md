# TempLoop336 Controller Manual

This device is documented in the style of an EPICS StreamDevice byte-stream
protocol. Commands and replies are ASCII text terminated by CR LF.

The simulator assigns the concrete resource identifier. Discover the available
resource and identify the controller with `*IDN?`. Resource names follow this
form:

```text
TCPIP0::<address>::<port>::SOCKET
```

Identification:

```text
*IDN? -> <vendor>,TempLoop336,<serial>,<firmware>
```

Loop 1 commands:

```text
SETP 1,<celsius>     set loop 1 setpoint
SETP? 1              returns SETP 1,<celsius>
RANGE 1,<OFF|LOW|MED|HIGH>
RANGE? 1             returns RANGE 1,<range>
KRDG? A              returns TEMP <celsius> C
HTR? 1               returns HTR 1,<percent> %
STB?                 returns LOOP <RAMPING|STABLE>
```

The loop is stable when `STB?` reports `LOOP STABLE` and the latest temperature
is within 0.05 C of the setpoint. Poll `KRDG? A`, `HTR? 1`, and `STB?` while
waiting for stability.
