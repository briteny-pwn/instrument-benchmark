# Difficulty analysis

1. **Instrument access:** Instrument.open_tcpip always forwards auth=None into concrete instrument constructors. Most drivers accept only filelike, so Ethernet-to-serial access fails with an unexpected keyword error.
2. **Why this is not a generic software bug:** Connection factory semantics span socket setup, communicator wrapping, heterogeneous driver constructors, optional authentication, and cleanup after construction failure.
3. **Instrument/framework:** instrument_drivers through instrumentkit.
4. **Gold behavior:** Forwards auth only when explicitly supplied, normalizes the Yokogawa constructor, and adds mocked TCP/IP regression tests.
5. **Difficulty source:** device_initialization, framework_semantic_mismatch, resource_conflict; Connection factory semantics span socket setup, communicator wrapping, heterogeneous driver constructors, optional authentication, and cleanup after construction failure.
6. **Phase-1 simulation:** Patch socket.create_connection with a fake socket and use unauthenticated/authenticated driver classes that record constructor and close calls.
7. **Evaluation oracle:** Default access constructs legacy drivers without auth, explicit auth reaches capable drivers, incompatible explicit auth raises, and sockets are not leaked.
