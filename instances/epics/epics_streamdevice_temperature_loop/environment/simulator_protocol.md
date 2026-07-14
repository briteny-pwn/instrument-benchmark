# Raw Simulator Protocol

A TCP instrument service is available while your program runs.
Read the endpoint from:

- `INSTRUMENT_SIM_HOST`
- `INSTRUMENT_SIM_PORT`

Use UTF-8 JSON lines. Send one JSON object followed by `\n`; read one JSON
object response line.

Allowed operations:

```json
{"op": "list_resources"}
{"op": "open", "resource": "TCPIP0::...", "timeout": 5000, "read_termination": "\r\n", "write_termination": "\r\n"}
{"op": "write", "handle": "h1", "command": "SETP 1,37.0"}
{"op": "query", "handle": "h1", "command": "*IDN?"}
{"op": "close", "handle": "h1"}
```

Successful responses contain `"ok": true`. `open` returns a handle string.
Text queries return:

```json
{"ok": true, "response": "text response"}
```
