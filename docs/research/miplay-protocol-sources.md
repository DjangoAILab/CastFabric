# MiPlay protocol research and implementation boundary

CastFabric's MiPlay receiver was implemented from observed wire behavior,
small deterministic protocol fixtures and public interoperability projects.
The implementation lives under `miair/miplay/` and is covered by offline
source/receiver tests.

## Public references

- [openMiPlay/MiPlayForWindows](https://github.com/openMiPlay/MiPlayForWindows)
  demonstrates community interest in interoperating with MiPlay endpoints.
- Existing MiAir, AirPlay and DLNA components provide only CastFabric's
  downstream speaker path; they are not treated as MiPlay protocol sources.
- mDNS/DNS-SD, RTSP, RTP and MPEG-TS are implemented using their standard wire
  structures plus endpoint observations captured in the repository's tests.

## Clean implementation boundary

At the time of research, the referenced MiPlay community repository did not
provide a license that authorized copying its source into this project. No
source file from it is vendored, imported or mechanically translated here.
Public behavior was used only to identify interoperability questions; the
codecs, state machines, simulator and tests were written independently.

Before adding another implementation as a dependency or copying any protocol
table, contributors must verify its license and record the decision here.
Real-device captures committed for diagnostics must exclude account tokens,
cookies, stable personal identifiers and unrelated LAN traffic.
