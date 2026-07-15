# Provided value of trigger_value is ignored

Source: https://github.com/bluesky/ophyd/issues/1218

Device.trigger ignores the trigger_value declared on a Component and always writes 1, contradicting the documented component contract.
