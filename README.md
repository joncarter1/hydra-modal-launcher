# hydra-modal-launcher

[![PyPI](https://img.shields.io/pypi/v/hydra-modal-launcher.svg)](https://pypi.org/project/hydra-modal-launcher/)
[![Python](https://img.shields.io/pypi/pyversions/hydra-modal-launcher.svg)](https://pypi.org/project/hydra-modal-launcher/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A [Hydra](https://hydra.cc/) launcher plugin that executes jobs as [Modal](https://modal.com/) functions.

## Quick start

```bash
pip install hydra-modal-launcher
```

```python
# my_app.py
import hydra
from omegaconf import DictConfig

@hydra.main(version_base=None)
def main(cfg: DictConfig) -> float:
    return float(cfg.lr) * float(cfg.epochs)

if __name__ == "__main__":
    main()
```

```bash
uv run my_app.py --multirun hydra/launcher=modal +lr=0.001,0.01,0.1 +epochs=10
# → 3 jobs run as 3 Modal functions, in parallel
```

Image, function spec (GPU, CPU, memory, secrets, volumes, timeout) and parallelism are all configurable under `hydra.launcher` — see [Common recipes](#common-recipes).

## Contents

- [Quick start](#quick-start)
- [Common recipes](#common-recipes)
- [Configuration reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)

<details>
<summary>More</summary>

- [Per-job outputs](#per-job-outputs)
- [How the user's code reaches the container](#how-the-users-code-reaches-the-container)
- [How it works](#how-it-works)
- [Project structure](#project-structure)
- [Gotchas](#gotchas)
- [Limitations](#limitations)
- [Testing](#testing)
- [Credits](#credits)

</details>

## Common recipes

These go under `hydra.launcher` in your config (or as `--multirun` overrides).

### GPU job

```yaml
hydra:
  launcher:
    parallelism: 4
    function:
      gpu: "H100"
      memory: 16384
      timeout: 3600
    image:
      pip_packages: [torch]
```

### Use a Modal Secret

```yaml
hydra:
  launcher:
    function:
      secrets:
        - my-wandb-key        # resolved via modal.Secret.from_name("my-wandb-key")
```

### Mount a Modal Volume at the sweep dir

```yaml
hydra:
  launcher:
    function:
      volumes:
        ${hydra.sweep.dir}: my-sweeps    # mount-path → volume-name
```

### Custom image builder (full Python control)

```python
# custom_image.py at the project root (or anywhere on your sys.path)
import modal

def build_image(image_cfg) -> modal.Image:
    return (
        modal.Image.from_registry("ghcr.io/myorg/base:latest")
        .pip_install("torch==2.5.0", "lightning")
        .run_commands("git clone https://github.com/myorg/data.git /data")
    )
```

```yaml
hydra:
  launcher:
    image:
      image_builder: custom_image.build_image    # every other image.* field is ignored
```

### Install deps from a requirements file or pyproject

For projects with more than a handful of pins, point the launcher at your existing dep manifest instead of duplicating entries in `pip_packages`. Both fields are composable — and additive with `pip_packages` (which still wins on name collision with the auto-pinned runtime deps).

```yaml
hydra:
  launcher:
    image:
      pip_requirements: requirements.txt          # passed to Image.pip_install_from_requirements
```

```yaml
hydra:
  launcher:
    image:
      pip_pyproject: pyproject.toml               # passed to Image.pip_install_from_pyproject
      pip_pyproject_extras: [training]            # → optional_dependencies=[...]
      pip_packages: [extra-debug-tool]            # still merged on top
```

Install layers are emitted heavy-first (`pip_pyproject` → `pip_requirements` → `pip_packages`), so editing `pip_packages` between runs doesn't invalidate the large transitive-dep layer.

#### Path resolution

`pip_pyproject` and `pip_requirements` accept both absolute and relative paths. Relative paths follow this order:

1. **Absolute paths** are used as-is.
2. **Relative paths that exist relative to CWD** are passed through unchanged — Modal's default behaviour.
3. **Otherwise**, the launcher walks up from CWD looking for the nearest `pyproject.toml` / `setup.py` / `setup.cfg` / `.git`, and if the file exists there, uses that absolute path. The resolution is logged.
4. **No match anywhere** — the path is handed to Modal unchanged so the resulting `FileNotFoundError` surfaces at build time.

This means you can invoke `uv run scripts/train.py` from any subdir and `pip_pyproject: pyproject.toml` will still find the project's root pyproject — same DWIM the launcher already does for source mounting.

### Pin extra deps without losing the auto-pinned runtime deps

The plugin auto-adds `hydra-core==<host_version>` and `cloudpickle==<host_version>` to every built image. Your `pip_packages` entries are merged with these; on a name collision, your pin wins.

```yaml
hydra:
  launcher:
    image:
      pip_packages:
        - "torch==2.5.0"
        - "transformers>=4.50"
        - "hydra-core>=1.3.0,<2"   # overrides the auto-pin
```

## Configuration reference

### `hydra.launcher.image` (`ModalImageConf`)

| Field | Default | Notes |
| --- | --- | --- |
| `python_version` | `null` | If unset, matches the host's `major.minor` at launch time. Cross-version cloudpickle of `__main__` functions can SIGSEGV the container; keep these aligned. |
| `base` | `"debian_slim"` | or `"from_registry"` |
| `base_image` | `null` | required when `base="from_registry"` |
| `pip_packages` | `[]` | sorted before install for cache stability; merged with auto-pinned `hydra-core` + `cloudpickle` |
| `pip_requirements` | `null` | path to a requirements file; passed to `Image.pip_install_from_requirements`. Relative paths are resolved against the nearest project root (see [Path resolution](#path-resolution)). |
| `pip_pyproject` | `null` | path to a `pyproject.toml`; passed to `Image.pip_install_from_pyproject`. Same resolution rules as `pip_requirements`. |
| `pip_pyproject_extras` | `[]` | extras keys for `pip_pyproject`, forwarded as `optional_dependencies=[...]` |
| `apt_packages` | `[]` | |
| `run_commands` | `[]` | extra `RUN` lines |
| `env` | `{}` | env vars baked into the image |
| `local_python_modules` | `[]` | importable module names; passed to `Image.add_local_python_source` |
| `local_dirs` | `[]` | list of `{local_path, remote_path, ignore}` for `Image.add_local_dir` |
| `image_builder` | `null` | dotted path to `(image_cfg) -> modal.Image`. Overrides every other field in `image`. |

### `hydra.launcher.function` (`ModalFunctionConf`)

| Field | Default | Notes |
| --- | --- | --- |
| `gpu` | `null` | e.g. `"L40S"`, `"A100:2"` |
| `cpu` | `null` | float, fractional cores |
| `memory` | `null` | MB |
| `timeout` | `3600` | seconds |
| `secrets` | `[]` | names resolved via `modal.Secret.from_name` |
| `volumes` | `{}` | `mount_path -> volume_name`, resolved via `modal.Volume.from_name` |
| `retries` | `0` | |
| `region` | `null` | |

### `hydra.launcher` (top-level)

| Field | Default | Notes |
| --- | --- | --- |
| `app_name` | `"hydra-modal-launcher"` | passed to `modal.App(...)` |
| `parallelism` | `-1` | `1` = serial, `N` caps concurrent containers via `max_containers=N`, `-1` = unbounded |
| `dry_run` | `false` | log resolved spec and skip `app.run()` |
| `env_passthrough` | `[]` | Host env vars to snapshot at launch time and inject into every worker container. Shipped as an ephemeral `modal.Secret.from_dict`, so values are present before user code starts. Use for per-launch runtime values (e.g. a tracking run ID set by a parent-side callback) that can't live in a static named secret. Missing keys log a warning and are skipped. |

## Per-job outputs

Jobs run remotely on ephemeral Modal containers; Hydra's per-job working directory written by `run_job` lives on that container, not on your laptop. The launcher:

1. **Always** writes minimal local `.hydra/{config,hydra,overrides}.yaml` stubs into `${hydra.sweep.dir}/<job_num>/` from the parent process so downstream tooling and humans see the expected layout.
2. **Optionally** mounts a [Modal Volume](https://modal.com/docs/guide/volumes) on the remote container via `hydra.launcher.function.volumes`. If you want real artifact persistence, point a volume at the sweep dir and pull it down after the run.

Each job's Python return value is captured in `JobReturn._return_value`. Failures are mapped to `JobReturn(status=FAILED, _return_value=<exception>)`.

## How the user's code reaches the container

Modal does **not** auto-mount your CWD. The launcher inspects your `task_function`'s module and:

- **Importable package** (`__module__ == "myproject.scripts.train"`): adds the top-level package via `Image.add_local_python_source("myproject")`.
- **`__main__`** (e.g. `python scripts/train.py`): walks up from the script's directory looking for `pyproject.toml` / `setup.py` / `setup.cfg` / `.git`. If found, mounts the whole project root via `Image.add_local_dir(<root>, "/root")` with default ignores (`.venv/`, `.git/`, `__pycache__/`, `node_modules/`, `multirun/`, `outputs/`, etc.). This handles the common research-repo layout where `scripts/` is a sibling of the package:
  ```
  myproject/
  ├── pyproject.toml        ← project root marker
  ├── myproject/            ← package
  │   └── lib.py
  ├── scripts/
  │   └── train.py          ← @hydra.main entrypoint
  └── conf/
      └── config.yaml
  ```
- **`__main__` with no project markers anywhere up-tree**: mounts only the script's directory and warns that sibling packages will be unreachable.

Override either path by setting `image.local_python_modules`, `image.local_dirs` (with custom `ignore` globs per mount), or by taking full control with `image.image_builder`.

## How it works

```
parent process                              modal cloud
──────────────                              ───────────
@hydra.main(main)
   │
   ▼
ModalLauncher.launch(overrides, idx0)
   │
   │  1. configure_log + Singleton.get_state()
   │  2. _resolve_sweep_configs(overrides)        ┐  done on parent —
   │  3. _write_local_job_stubs(sweep_configs)    │  the user's conf/ dir
   │  4. cloudpickle.dumps(launcher)              │  is local-only and
   │  5. build_modal_app(launcher_cfg)            ┘  doesn't exist remotely
   │
   ▼
with modal.enable_output(), app.run():
    fn.starmap(payloads, return_exceptions=True) ────►  spawns N containers
                                                              │
                                                              ▼
                                            _worker.modal_entry(sweep_config, num, state, launcher_pickled)
                                                              │
                                                              │  cloudpickle.loads(launcher_pickled)
                                                              │  Singleton.set_state + setup_globals
                                                              │  HydraConfig.instance().set_config(sweep_config)
                                                              │  open_dict: hydra.job.id = modal call id
                                                              │  run_job(task_function, sweep_config, ...)
                                                              │
                                                              ▼
                                                         returns JobReturn
   │
   ▼
[JobReturn, JobReturn, ...] ────► back to Hydra's sweeper
```

Sweep configs are pre-resolved on the parent so the worker never needs to read the local `conf/` dir from inside a Modal container. The cloudpickled launcher carries `task_function` and `hydra_context.callbacks`; the singleton snapshot is shipped separately and restored on the worker so `HydraConfig.instance()` resolves correctly.

## Project structure

```
hydra-modal-launcher/
├── hydra_plugins/hydra_modal_launcher/   # the plugin (PEP 420 namespace — no __init__ on hydra_plugins/)
│   ├── config.py                          # dataclasses + ConfigStore registration
│   ├── modal_launcher.py                  # ModalLauncher(Launcher)
│   ├── _modal_app.py                      # pure + impure builders for modal.App / Image / Function
│   └── _worker.py                         # ships to the Modal container
├── example/                               # Layout-A demo (entry: `uv run example/my_app.py`)
├── tests/                                 # pure unit tests, no Modal account required
├── AGENTS.md                              # ← read this if you're an AI agent
└── CHANGELOG.md
```

For deeper conventions and invariants — what's pure vs impure, where Modal can be imported, how to add a config field — see [`AGENTS.md`](AGENTS.md).

## Gotchas

- **Host/container Python version must match.** Cloudpickle ships `__main__`-scoped functions by value (bytecode + cells); deserializing across Python minor versions can segfault the container. The default `python_version=null` auto-detects the host's `major.minor` and uses that, so you generally don't need to set it.
- **`hydra-core` and `cloudpickle` are added to every built image** automatically, pinned to your host's installed versions. User-supplied version pins for the same package win on name collision.
- **Modal logs stream to your terminal** during a sweep via `modal.enable_output()`. Local Hydra logs and remote container stdout are interleaved.

## Limitations

- No `checkpoint` / preemption support — Modal has no equivalent of SLURM's signal protocol.
- No automatic sync of remote working dirs back to your laptop. Use volumes if you need it.
- Ephemeral apps only (`with app.run():`). Pre-deployed apps via `Function.from_name` are out of scope.
- Image is rebuilt once per `launch()` call. Modal caches build layers so subsequent runs are fast.

## Troubleshooting

### `Runner segmentation fault (SIGSEGV)` on container startup

Host and container Python versions don't match. Cloudpickle ships `__main__` functions by value (bytecode); deserializing across minor versions crashes the container. Verify `hydra.launcher.image.python_version` is `null` (the default — it auto-matches your host) or set explicitly to your host's `major.minor`.

### `ModuleNotFoundError: No module named 'mypkg'` on the remote

The auto-mount didn't pick up your package. If you ran the script directly (`python scripts/train.py`), the launcher looks for `pyproject.toml` / `setup.py` / `setup.cfg` / `.git` to mount the whole project root. If none exist, only the script's directory is mounted. Fix by either:
- adding the missing markers (an empty `pyproject.toml` is fine), or
- explicitly setting `image.local_python_modules: ["mypkg"]` or `image.local_dirs:` in your config.

### `Primary config directory not found` on the remote

You're on a stale build of the plugin. v0.1.0+ pre-resolves sweep configs on the parent — the worker should never call `load_sweep_config`. Upgrade.

### `Input aborted - exceeded limit of 8 retries`

Container is crashing during input deserialization. Usual causes:

1. Python-version mismatch (SIGSEGV — see above).
2. Out-of-memory at import time. Bump `function.memory`. `hydra-core` + `omegaconf` import at ~150 MB; 256 MB is too tight.
3. Cloudpickle version drift. Should be auto-pinned to your host — verify with `hydra.launcher.dry_run=true` and check `cloudpickle==X.Y.Z` is in `pip_packages`.

### Modal container logs aren't showing up

You're probably running an old build. v0.1.0+ wraps the sweep in `with modal.enable_output()`. Upgrade.

### Dry-run for everything

Add `hydra.launcher.dry_run=true` to any sweep. The launcher logs the resolved image spec + function kwargs and returns without calling Modal. Useful for validating config and image deps before paying for a build.

## Testing

```bash
uv sync --extra dev
uv run pytest tests/
```

`uv.lock` is committed, so the sync is reproducible. Unit tests don't require a Modal account; the orchestration is pure functions where possible.

Live tests against real Modal are marked `@pytest.mark.live` and skipped by default. To run them (requires Modal credentials configured locally):

```bash
uv run pytest tests/ --live
```

## Credits

Inspired by the official Hydra launcher plugins:

- [`hydra-submitit-launcher`](https://github.com/facebookresearch/hydra/tree/main/plugins/hydra_submitit_launcher) — SLURM via [submitit](https://github.com/facebookincubator/submitit)
- [`hydra-ray-launcher`](https://github.com/facebookresearch/hydra/tree/main/plugins/hydra_ray_launcher) — AWS via [Ray](https://www.ray.io/)

