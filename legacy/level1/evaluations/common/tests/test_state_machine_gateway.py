from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluations.common.state_machine_gateway import Gateway


class StateMachineGatewayTests(unittest.TestCase):
    def _gateway(self) -> Gateway:
        self.tempdir = tempfile.TemporaryDirectory()
        path = Path(self.tempdir.name) / "scenario.json"
        path.write_text(
            json.dumps(
                {
                    "initial_state": {"pump": {"armed": False, "attempts": 0}},
                    "resources": [
                        {
                            "name": "BUS",
                            "commands": [
                                {
                                    "kind": "write",
                                    "command": "ARM",
                                    "state_updates": {"pump.armed": True},
                                },
                                {
                                    "kind": "query",
                                    "command": "START",
                                    "requires_state": {"pump.armed": True},
                                    "steps": [
                                        {"response": "BUSY", "state_increments": {"pump.attempts": 1}},
                                        {
                                            "response": "ACK",
                                            "state_increments": {"pump.attempts": 1},
                                            "state_updates": {"pump.running": True},
                                        },
                                    ],
                                },
                                {
                                    "kind": "write",
                                    "command_regex": "^SET ([-+0-9.]+)$",
                                    "state_from_groups": {
                                        "source.setpoint": {"group": 1, "type": "float"},
                                        "source.readback": {
                                            "group": 1,
                                            "type": "float",
                                            "scale": 2.0,
                                            "offset": 0.1,
                                            "round": 3,
                                        },
                                    },
                                },
                                {
                                    "kind": "query",
                                    "command": "READ?",
                                    "response_template": "READ {source.readback}",
                                },
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return Gateway(path)

    def tearDown(self) -> None:
        if hasattr(self, "tempdir"):
            self.tempdir.cleanup()

    def test_state_preconditions_and_step_updates(self) -> None:
        gateway = self._gateway()
        handle = gateway.dispatch({"op": "open", "resource": "BUS"})["handle"]
        with self.assertRaises(RuntimeError):
            gateway.dispatch({"op": "query", "handle": handle, "command": "START"})
        gateway.dispatch({"op": "write", "handle": handle, "command": "ARM"})
        first = gateway.dispatch({"op": "query", "handle": handle, "command": "START"})
        second = gateway.dispatch({"op": "query", "handle": handle, "command": "START"})
        self.assertEqual(first["response"], "BUSY")
        self.assertEqual(second["response"], "ACK")
        self.assertEqual(gateway.state["pump"], {"armed": True, "attempts": 2, "running": True})

    def test_response_sequence_does_not_reset_when_handle_reopens(self) -> None:
        gateway = self._gateway()
        first_handle = gateway.dispatch({"op": "open", "resource": "BUS"})["handle"]
        gateway.dispatch({"op": "write", "handle": first_handle, "command": "ARM"})
        first = gateway.dispatch({"op": "query", "handle": first_handle, "command": "START"})
        gateway.dispatch({"op": "close", "handle": first_handle})
        second_handle = gateway.dispatch({"op": "open", "resource": "BUS"})["handle"]
        second = gateway.dispatch({"op": "query", "handle": second_handle, "command": "START"})
        self.assertEqual(first["response"], "BUSY")
        self.assertEqual(second["response"], "ACK")

    def test_regex_command_captures_drive_state_and_response(self) -> None:
        gateway = self._gateway()
        handle = gateway.dispatch({"op": "open", "resource": "BUS"})["handle"]
        gateway.dispatch({"op": "write", "handle": handle, "command": "set 1.25"})
        response = gateway.dispatch({"op": "query", "handle": handle, "command": "READ?"})
        self.assertEqual(response["response"], "READ 2.6")
        self.assertEqual(gateway.state["source"], {"setpoint": 1.25, "readback": 2.6})


if __name__ == "__main__":
    unittest.main()
