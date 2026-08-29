# Repository Instructions

## Project Shape
- Product name is CastFabric. The Python package remains `miair` plus top-level compatibility launcher `miair.py`; primary installed CLI entrypoints are `castfabric` and `castfabric-miplay`, with legacy aliases retained.
- `miair.app.CastFabric` wires the app (`MiAir` is an alias): Web UI/API starts first, then enabled generic DLNA targets start virtual DLNA, AirPlay and MiPlay without requiring Xiaomi credentials.
- Major protocol code lives under `miair/dlna/` and `miair/airplay/`; Web API routes and settings masking live in `miair/web/api.py`.
- Playback output contracts and adapters live under `miair/outputs/`; standard DLNA is core and Xiaomi MiNA is an optional legacy-target fallback.

## Commands
- Runtime requires Python `>=3.10` per `pyproject.toml`; README says Python 3.12+ for Windows usage.
- Install editable package/deps with `python3 -m pip install -e .` before importing modules or running tests; `miair.py` auto-installs runtime deps only when launched directly.
- Start locally with `castfabric --conf-path conf` (legacy `python3 miair.py` remains supported).
- Run the existing test script with `python3 tests/test_audio_seek.py`; this is not a pytest-configured repo and `pytest` is not declared as a dependency.
- Focused pytest-style execution may still work if pytest is installed: `python3 -m pytest tests/test_audio_seek.py -k detect_audio_format`.

## Runtime And Config
- Config is loaded from `<conf-path>/config.json`; relative `--conf-path` is normalized to an absolute path in `Config.load`.
- `CASTFABRIC_HOSTNAME` explicitly overrides saved `hostname`; `MIAIR_HOSTNAME` remains a fallback. `MI_USER`, `MI_PASS`, and `MI_DID` are optional Xiaomi-extension compatibility variables.
- Default ports are DLNA HTTP `8200` and Web UI/API `8300`; Docker exposes both and runs with host networking.
- Secrets/cookies must stay masked in API responses; preserve `_mask_cookie`, `_unmask_cookie`, and `_mask_devices` behavior when touching settings endpoints.

## Docker And Deploy
- CI tests feature branches and publishes multi-architecture GHCR images on `main`, version tags, or manual dispatch.
- The checked-in `Dockerfile` copies `config-example.json` and `.env.example` into the image, seeds `/app/conf/config.json` and `/app/conf/.env` if absent, then runs `python miair.py --conf-path /app/conf`.
- `deploy.sh` is a non-destructive Docker Compose wrapper (`local` builds, `pull` uses GHCR); it never rewrites the Dockerfile or deletes configuration.
- `manage.sh update` pulls the published image and recreates the Compose service while preserving the configured host directory mounted at `/app/conf`.

## Testing Quirks
- `tests/test_audio_seek.py` imports production modules and needs runtime dependencies such as `miservice-fork`, `aiohttp`, `zeroconf`, `pycryptodome`, and `av` installed.
- ffmpeg-dependent portions of the test script are best-effort: they skip or warn when ffmpeg is unavailable; pure-Python seek tests should still run once Python deps are installed.
- The current macOS system Python in this workspace is 3.9.6, below the project requirement, so use a Python 3.10+ interpreter for meaningful verification.
