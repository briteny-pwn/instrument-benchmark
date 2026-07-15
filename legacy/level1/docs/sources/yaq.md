# Yaq Source Notes

The `yaq` source uses yaq and yaqd-fakes as source material for from-scratch
instrument-interface tasks.

Yaq models instrument components as small daemon processes. The native yaq
protocol uses TCP plus Avro RPC, with daemon traits, configuration, state, and
message schemas. `yaqd-fakes` provides native fake daemons such as sensors,
continuous positioners, and spectrometers.

Candidates do not use yaq directly. Current hidden evaluations launch native
`yaqd-fakes` daemons and communicate with them through an evaluation-only yaq
client, then expose a raw JSON-line socket gateway to candidate solutions.

Current instance themes:

- Fake sensor stability scan.
- Fake continuous motor plus sensor alignment scan.
- Fake spectrometer triggered acquisition.

Primary source material:

- yaq introduction: daemon architecture, TCP transport, Avro RPC, config/state,
  timing, and traits.
- yaq daemon catalogue: fake camera, fake continuous hardware, fake sensor,
  fake spectrometer, fake triggered sensor, and related daemons.
- YEP-107: yaq usage of Apache Avro RPC.
- yaq-python repository: core packages `yaqc`, `yaqd-core`, and `yaqd-fakes`.
