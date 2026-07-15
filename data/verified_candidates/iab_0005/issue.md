# inst.open_tcpip() errors for various instruments

Source: https://github.com/instrumentkit/InstrumentKit/issues/439

Instrument.open_tcpip always forwards auth=None into concrete instrument constructors. Most drivers accept only filelike, so Ethernet-to-serial access fails with an unexpected keyword error.
