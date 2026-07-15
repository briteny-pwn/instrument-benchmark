# Raw Simulator Protocol

A TCP instrument service is available while your program runs.
Read the connection endpoint from these environment variables:

- `INSTRUMENT_SIM_HOST`
- `INSTRUMENT_SIM_PORT`

Communicate with the gateway using UTF-8 JSON lines. Send exactly one JSON
object followed by `\n`; read exactly one JSON object response line.

Allowed operations:

```json
{"op": "list_resources"}
{"op": "open", "resource": "USB0::...", "timeout": 5000, "read_termination": "\n", "write_termination": "\n"}
{"op": "write", "handle": "h1", "command": "*RST"}
{"op": "query", "handle": "h1", "command": "*IDN?"}
{"op": "query_raw", "handle": "h1", "command": "CURVE?"}
{"op": "close", "handle": "h1"}
```

Successful responses contain `"ok": true`. `open` returns a handle string.
Text queries return:

```json
{"ok": true, "response": "text response"}
```

Binary block queries return base64 encoded bytes:

```json
{"ok": true, "encoding": "base64", "data": "base64 bytes"}
```
