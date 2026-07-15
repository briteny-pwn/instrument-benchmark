# Difficulty analysis

Adapter: ASITiger

Failure modes: device_initialization, property_state_desync

CRISP Dither and Sum properties are updated when Initialize() is called.

The SNR property uses the "EX" shortcut for the "EXTRA" command if firmware is >= 3.53.

Add firmware version check in `ASIDacXYStage` for single axis pattern 3.

Convert all of the "Always read" CRISP properties to `MM::ActionLambda`.

Add overload to ASIHub to create less temporary std::string objects.

For example, `QueryCommandVerify` now has an overload where the second parameter is `const char *`:
`hub_->QueryCommandVerify(command.str(), ":A X="))`
