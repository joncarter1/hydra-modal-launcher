# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-12

### Added
- Initial release.
- `ModalLauncher` Hydra plugin registered as `hydra/launcher=modal` via PEP 420 `hydra_plugins` namespace discovery.
- Config-driven image: `python_version` (auto-matches host when unset), `pip_packages`, `apt_packages`, `run_commands`, `env`, `local_python_modules`, `local_dirs` (with per-mount `ignore` globs), plus an `image_builder` `_target_` escape hatch for fully custom `modal.Image` construction in user code.
- Config-driven function spec: `gpu`, `cpu`, `memory`, `timeout`, `secrets`, `volumes`, `retries`, `region`.
- `parallelism` knob: `1` = serial, `N` = capped via `max_containers=N`, `-1` = unbounded.
- `dry_run` mode logs the resolved image and function spec without invoking Modal.
- Per-job `.hydra/{config,hydra,overrides}.yaml` stubs written locally from the parent process; full remote artifact persistence via opt-in Modal Volumes.
- Auto-detection of host Python version, sidestepping cross-version cloudpickle SIGSEGV crashes on remote containers.
- Auto-detection of project root (`pyproject.toml` / `setup.py` / `setup.cfg` / `.git`) for `__main__` entrypoints; mounts the whole tree with sensible default ignores (`.venv/`, `.git/`, `__pycache__/`, `node_modules/`, Hydra's `multirun/` and `outputs/`, etc.).
- Auto-pinning of required runtime deps (`hydra-core`, `cloudpickle`) to the host's installed versions when adding them to the image; user-supplied version pins win on name collision.
- Remote container stdout streamed to the local terminal via `modal.enable_output()`.

[Unreleased]: https://github.com/joncarter1/hydra-modal-launcher/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/joncarter1/hydra-modal-launcher/releases/tag/v0.1.0
