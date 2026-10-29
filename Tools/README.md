# ID Cadastral — canonical host tools

This directory in `state-id-harvester` is the canonical source for the ID Cadastral
UI and host analysis tools. The duplicate tools in the older SDK release checkout
have been removed. These tools run locally, outside native phone builds.

Start with [the Cadastral launcher](Cadastral/README.md). The UI source is
[PixelViewer](PixelViewer/README.md). Host tool dependencies use OpenCV 5.0.0
(`opencv-contrib-python-headless==5.0.0.93`). UI behavior and analysis algorithms
are unchanged by this move.

The current local server runs at http://127.0.0.1:8768/ using the environment and
Washington dataset under ignored `output/cadastral-local-20261026/`. Its
`start.sh` now invokes this directory's `Cadastral/launch.py`.

Source provenance: the baseline tools were restored from `kenshiki-identity-sdk`
commit `da7f9de18bb6f3eb9af345263d3f9a8fa962741b`, then updated only for the
OpenCV 5 dependency pin. The SDK import originally identified capture-stack
commit `5e4e1090254e7527bbb8365f6a0921ea6dd1e78d`. Imported third-party notices,
source, and tests remain with the tools. Historical result descriptions in the
individual READMEs are not new validation results.

Keep captures, generated reports, environments, and downloaded model weights in
ignored `output/` or an explicit external data directory, outside this source tree.
