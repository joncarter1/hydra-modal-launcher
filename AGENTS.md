# AGENTS.md

Map of this repo for AI coding agents. Read this before making non-trivial changes.

## What this package does

A Hydra `Launcher` plugin (registered as `hydra/launcher=modal`) that runs each multirun job as one invocation of a Modal function. Config-driven image, function-spec, and parallelism. Inspired by `hydra-submitit-launcher` and `hydra-ray-launcher`.

## File map

```
hydra_plugins/hydra_modal_launcher/
├── __init__.py            # __version__ only; nothing else loads at import time
├── config.py              # OmegaConf dataclasses + ConfigStore.store("hydra/launcher", "modal", ...)
├── modal_launcher.py      # ModalLauncher(Launcher) — the only public entry
├── _modal_app.py          # Pure builders: ModalLauncherConf -> modal.App + modal.Image + modal.Function
├── _paths.py              # _detect_project_root + _resolve_against_project_root (shared between launcher & builder)
├── _worker.py             # Top-level fn shipped to Modal containers; mirrors hydra_ray_launcher._launcher_util
└── py.typed
example/                   # Layout-A demo (entrypoint = `uv run example/my_app.py`)
  ├── conf/
  │   ├── config.yaml               # YAML pip_packages
  │   ├── config_requirements.yaml  # pip_requirements: example/requirements.txt
  │   ├── config_pyproject.yaml     # pip_pyproject: example/pyproject.toml
  │   └── config_custom.yaml        # image_builder escape hatch
  ├── pyproject.toml                # demo deps for config_pyproject.yaml — minimal [project] table
  ├── requirements.txt              # demo deps for config_requirements.yaml
  ├── custom_image.py
  └── my_app.py
tests/                     # Pure unit tests; no Modal account required
```

## Key invariants

1. **Plugin discovery is namespace-package-based.** `hydra_plugins/` is a PEP 420 namespace package — never add an `__init__.py` to it. Hydra's plugin scanner walks the namespace at startup and registers `Launcher` subclasses + already-loaded `ConfigStore` entries.

2. **The worker (`_worker.py`) must stay importable without `modal`.** `modal` is only imported lazily inside `_modal_job_id`. This lets unit tests exercise the orchestration without a Modal install.

3. **`_modal_app.py` exposes two pure helpers (`build_image_spec`, `build_function_kwargs`) that take only config and return dicts.** They MUST NOT import `modal`. The `_build_image` and `_resolve_function_kwargs` functions (with `modal` imports) are the impure variants. Tests target the pure helpers.

4. **Required runtime deps are auto-pinned to host versions** — but only on the YAML build path. `_modal_app._required_runtime_specs()` reads `cloudpickle` + `hydra-core` from `importlib.metadata` and pins them in the built image. Without this, cross-version cloudpickle deserialization can SIGSEGV the container. User-supplied pins win on name collision via `_merge_pip_packages`. **`image.image_builder` short-circuits `_build_image` before the merge step** — when a user supplies a code-mode builder, they own runtime deps too. Documented in `example/custom_image.py` and `example/README.md`.

5. **Python version on the container defaults to the host's `major.minor`** (`_resolved_python_version`). Same reason as #4. Never hardcode a Python version string.

6. **The worker does NOT call `load_sweep_config`.** Sweep configs are pre-resolved on the parent in `_resolve_sweep_configs` and shipped as the first payload arg. The worker would crash trying to read the user's local `conf/` dir from inside the Modal container.

7. **`return_exceptions=True` is hard-coded in the `Function.starmap` call.** Hydra's sweeper expects a `JobReturn` for every input; raw exceptions break the sweep. `_to_job_return` maps exceptions to `JobReturn(status=FAILED, _return_value=<exc>)`.

8. **`max_containers=N` is the Modal SDK ≥1.4 spelling.** Older spellings (`concurrency_limit`) won't work. If bumping the minimum Modal version, update the comment in `_modal_app._resolve_function_kwargs` and `pyproject.toml` together.

9. **Install layers in `_build_image` are heavy-to-light by design.** Order: `pip_install_from_pyproject` → `pip_install_from_requirements` → `pip_install(merged user + auto-pinned)`. Edits to `pip_packages` between runs shouldn't invalidate the larger pyproject/requirements layers. Don't reorder without thinking about cache impact. The auto-pinned `hydra-core` + `cloudpickle` ride in the final `pip_install` so they always win on name collision regardless of which dep source the user picked.

10. **The launcher's own `hydra_plugins` package reaches the container via Modal's automatic function-source detection, not via `local_dirs`.** Modal introspects `_worker.modal_entry`'s module hierarchy when the `@app.function` is registered and produces a `PythonPackage:hydra_plugins` mount (visible in build logs). This is why `example/` can ship its own `pyproject.toml` without breaking the demo — narrowing `_detect_project_root`'s mount to `example/` doesn't drop the launcher. If Modal ever changes this auto-detection, the example would need an explicit `image.local_python_modules: [hydra_plugins]` to compensate.

11. **`pip_pyproject` / `pip_requirements` paths are resolved against the project root, not just CWD.** `_resolve_against_project_root` (in `_paths.py`) is called in `_build_image` only — `build_image_spec` stays hermetic so unit tests don't touch the filesystem. The resolver: absolute paths and CWD-relative-that-exist pass through unchanged; otherwise it walks up from CWD using the same markers as `_detect_project_root` and prepends if the file is found. On any miss the original string is returned so Modal raises a clear `FileNotFoundError` at build time. Changes to resolution semantics MUST keep `build_image_spec` filesystem-free.

## Common tasks

### Add a new config field

Update three places, in this order:
1. `config.py` — add to the relevant dataclass (`ModalImageConf` / `ModalFunctionConf` / `ModalLauncherConf`), keeping the old-style `Optional[...]` typing (avoid `from __future__ import annotations` here — it breaks Hydra's dataclass scanner on Python 3.12).
2. `_modal_app.py` — propagate into `build_image_spec` / `build_function_kwargs` (pure side) and the corresponding `_build_image` / `_resolve_function_kwargs` (impure side).
3. `tests/test_modal_launcher.py` — assert the field round-trips through the pure helpers.
4. `README.md` — config reference table.
5. `CHANGELOG.md` — `[Unreleased]` section.

### Change worker-side behaviour

Touch `_worker.py:modal_entry`. Keep imports lazy (inside the function body), match the singleton/setup_globals/HydraConfig restore order, return what `run_job` returns. Don't refactor away the `cloudpickle.loads(launcher_pickled)` without coordinating with `modal_launcher.py:launch` — they're a pair.

### Bump a dependency

`pyproject.toml` + matching version comment in `_modal_app.py` (for `modal` specifically). Then `uv lock` to update `uv.lock`, and `uv build && uv run twine check dist/*` to confirm metadata still validates. CI uses `uv sync --extra dev` against the lock, so an out-of-sync lock fails the run.

### Cut a release

See "Releasing" in `README.md`. SemVer tag `vX.Y.Z` → `publish.yml` builds + publishes via trusted publishing.

## What's verified vs unverified

| Path | Verified how |
|---|---|
| Plugin discovery, ConfigStore registration | Unit test |
| Image spec / function kwargs / pip merging | Unit tests |
| `pip_requirements` / `pip_pyproject` / `pip_pyproject_extras` round-trip through pure helper | Unit tests |
| `_to_job_return` exception mapping | Unit test |
| `_detect_project_root` for Layout B | Unit tests |
| End-to-end on Modal — Layout A (`uv run example/my_app.py`) | Live run |
| End-to-end on Modal — Layout B (project-root mount of `/tmp/research-repo`) | Live run |
| Wheel installs from fresh `uv venv` and plugin discovery still works | Live |
| `pip_install_from_requirements` SDK call (via `config_requirements.yaml`) | Live run; container confirmed to import `tabulate` from the installed requirements |
| `pip_install_from_pyproject` SDK call (via `config_pyproject.yaml`) | Live run; container confirmed to import `tabulate` from `example/pyproject.toml`'s `[project].dependencies` |
| `_resolve_against_project_root` resolution branches | Unit tests (4 cases — absolute, CWD-relative-exists, walk-up-hit, miss) |
| Narrowed auto-mount when `example/pyproject.toml` is present + `PythonPackage:hydra_plugins` auto-discovery | Live run — basic and pyproject configs both work with `Created mount /Users/.../example` instead of the whole repo |
| **End-to-end failure path** | NOT verified live — see `ROADMAP.md` |

## Cost notes for live E2E testing

A 2-job sweep on `cpu=0.5, memory=1024, timeout=120` after the image is cached costs ~$0.0002. The first-time image build is the expensive bit (~$0.005-0.02 depending on pip_install size). Keep test workloads tiny — never `gpu=...` on speculative runs.

## Things that previously broke (don't reintroduce)

- `from __future__ import annotations` in `config.py` — breaks Hydra's dataclass plugin scanner on Python 3.12 (`cls.__module__` lookup fails).
- Importing `modal` at module top-level in `_worker.py` — slows cold starts and breaks unit tests without `modal` installed.
- Calling `load_sweep_config` on the remote — the user's `conf/` directory doesn't exist on the container's filesystem.
- Hardcoded `python_version="3.11"` — causes SIGSEGV when host is on a different minor.
- Bare `pip_install("hydra-core", "cloudpickle")` — without host-version pinning, cross-version cloudpickle deserialization can crash.

See `ROADMAP.md` for known gaps with stated fixes.
