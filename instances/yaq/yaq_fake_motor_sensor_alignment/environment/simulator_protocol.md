# Raw Simulator Protocol

The evaluator starts a local TCP simulator gateway before running your code.
Read the endpoint from:

- `INSTRUMENT_SIM_HOST`
- `INSTRUMENT_SIM_PORT`

Use UTF-8 JSON lines. Send one JSON object followed by `\n`; read one JSON
object response line.

Allowed operations:

```json
{"op": "list_resources"}
{"op": "open", "resource": "YAQ::fake-continuous-hardware::axis", "timeout": 5000}
{"op": "open", "resource": "YAQ::fake-sensor::alignment", "timeout": 5000}
{"op": "write", "handle": "h1", "command": "SET_POSITION 1.0"}
{"op": "query", "handle": "h1", "command": "BUSY?"}
{"op": "query", "handle": "h1", "command": "POSITION?"}
{"op": "query", "handle": "h2", "command": "MEASURE? alignment"}
{"op": "close", "handle": "h1"}
```

Successful responses contain `"ok": true`. `open` returns a handle string.
Text queries return:

```json
{"ok": true, "response": "text response"}
```
