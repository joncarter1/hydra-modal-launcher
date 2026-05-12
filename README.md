# hydra-modal-launcher

A [Hydra](https://hydra.cc/) launcher plugin that ships multirun jobs to [Modal](https://modal.com/). Inspired by `hydra-submitit-launcher` and `hydra-ray-launcher`.

Each Hydra job runs as one invocation of a Modal function. The image and function spec (GPU, CPU, memory, secrets, volumes, timeout, parallelism) are configured from YAML. An `image_builder` escape hatch lets you produce a fully custom `modal.Image` in Python when YAML isn't enough.

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [Common recipes](#common-recipes)
- [Configuration reference](#configuration-reference)
- [Per-job outputs](#per-job-outputs)
- [How the user's code reaches the container](#how-the-users-code-reaches-the-container)
- [How it works](#how-it-works)
- [Project structure](#project-structure)
- [Gotchas](#gotchas)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Testing](#testing)

## Install

```bash
pip install hydra-modal-launcher
# or, from a checkout:
pip install -e ".[dev]"
```

Requires `python>=3.10`, `hydra-core>=1.3`, and `modal>=1.4`. You also need [`modal token new`](https://modal.com/docs/guide#getting-started) to be configured on the host that runs the sweep.

## Quick start

```python
# my_app.py
import hydra
from omegaconf import DictConfig

@hydra.main(version_base=None, config_path="conf", config_name="config")
def main(cfg: DictConfig) -> float:
    return float(cfg.lr) * float(cfg.epochs)

if __name__ == "__main__":
    main()
```

```yaml
# conf/config.yaml
defaults:
  - _self_
  - override hydra/launcher: modal

lr: 0.01
epochs: 10

hydra:
  launcher:
    parallelism: 3        # 1 = serial, N = cap, -1 = unlimited
    image:
      pip_packages: [hydra-core, omegaconf]
    function:
      cpu: 1
      memory: 1024
      timeout: 300
```

Launch a sweep:

```bash
# Dry-run: log resolved spec without calling Modal
uv run my_app.py --multirun hydra.launcher.dry_run=true lr=0.001,0.01,0.1

# Real run (Modal credentials in env)
uv run my_app.py --multirun lr=0.001,0.01,0.1
```

## Common recipes

These go under `hydra.launcher` in your config (or as `--multirun` overrides).

### GPU job

```yaml
hydra:
  launcher:
    parallelism: 4
    function:
      gpu: "L40S"             # or "A100", "H100", "L40S:2" for 2x
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

