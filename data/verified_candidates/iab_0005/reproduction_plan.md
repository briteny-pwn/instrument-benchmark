# Simulation reproduction

Patch socket.create_connection with a fake socket and use unauthenticated/authenticated driver classes that record constructor and close calls.

Evaluation oracle: Default access constructs legacy drivers without auth, explicit auth reaches capable drivers, incompatible explicit auth raises, and sockets are not leaked.
