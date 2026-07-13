# TempLoop336 Controller Manual

This device is documented in the style of an EPICS StreamDevice byte-stream
protocol. Commands and replies are ASCII text terminated by CR LF.

Resource:

```text
TCPIP0::10.10.0.11::4001::SOCKET
```

Identification:

```text
*IDN? -> EPICSIM,TempLoop336,TC336001,1.0
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
