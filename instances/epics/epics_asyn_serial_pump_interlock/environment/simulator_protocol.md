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
{"op": "open", "resource": "ASYN::...", "timeout": 5000, "read_termination": "\n", "write_termination": "\n"}
{"op": "query", "handle": "h1", "command": "@P1 ILK?"}
{"op": "query", "handle": "h1", "command": "@P1 START"}
{"op": "close", "handle": "h1"}
```

Successful responses contain `"ok": true`. `open` returns a handle string.
Text queries return:

```json
{"ok": true, "response": "text response"}
```
