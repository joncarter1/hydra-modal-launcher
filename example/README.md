# Examples

Four ways to run the same `my_app.py`, showing the available image-customisation paths.

## 1. Basic — YAML-driven image

```bash
uv run example/my_app.py --multirun lr=0.001,0.01,0.1
```

Config: [`conf/config.yaml`](conf/config.yaml). The launcher builds the image from `image.pip_packages` and friends, and auto-pins runtime deps (`hydra-core`, `cloudpickle`) to your host's installed versions.

## 2. Install deps from a requirements file

```bash
uv run example/my_app.py --config-name=config_requirements --multirun lr=0.001,0.01,0.1
```

Config: [`conf/config_requirements.yaml`](conf/config_requirements.yaml), pointing at [`requirements.txt`](requirements.txt). The launcher forwards the file to `Image.pip_install_from_requirements`, and the auto-pinned `hydra-core` + `cloudpickle` are merged on top via a separate `pip_install` layer.

The config path is `example/requirements.txt`, which works whether you invoke from the repo root (CWD-relative) or from inside `example/` (where the project-root-aware resolver walks up). See [Path resolution](../README.md#path-resolution) for the full rules.

## 3. Install deps from a `pyproject.toml`

```bash
uv run example/my_app.py --config-name=config_pyproject --multirun lr=0.001,0.01,0.1
```

Config: [`conf/config_pyproject.yaml`](conf/config_pyproject.yaml), pointing at [`pyproject.toml`](pyproject.toml). The launcher forwards the file to `Image.pip_install_from_pyproject`, which reads `[project].dependencies` (plus any keys named in `pip_pyproject_extras`) and `pip install`s them into the image.

Note that the config uses `pip_pyproject: example/pyproject.toml` rather than a bare `pyproject.toml`. From the documented invocation (CWD = repo root), bare `pyproject.toml` would resolve CWD-relative to the **launcher's** pyproject — see the comment in the config and the [Path resolution](../README.md#path-resolution) docs.

All of `pip_pyproject`, `pip_requirements`, and `pip_packages` are composable in one config and emit separate layers in heavy-to-light order.

## 4. Custom image — full Python control

```bash
uv run example/my_app.py --config-name=config_custom --multirun lr=0.001,0.01,0.1
```

Config: [`conf/config_custom.yaml`](conf/config_custom.yaml), pointing at the builder in [`custom_image.py`](custom_image.py).

When `image.image_builder` is set, every other field under `image:` is ignored — the callable owns the entire `modal.Image` construction. Useful for pinning a base image from a registry, running arbitrary shell during build, or programmatically deciding deps from the resolved config. Note that the launcher's auto-injection of `hydra-core` and `cloudpickle` is also skipped, so the builder must include them itself.

## Dry-run any of them

Add `hydra.launcher.dry_run=true` to log the resolved image + function spec without spending a cent on Modal:

```bash
uv run example/my_app.py --config-name=config_custom \
    --multirun hydra.launcher.dry_run=true lr=0.001,0.01
```

## Folder layout

```
example/
├── __init__.py
├── README.md                  # ← you are here
├── my_app.py                  # @hydra.main entrypoint, shared by all configs
├── custom_image.py            # build_image() referenced by config_custom.yaml
├── pyproject.toml             # demo deps for config_pyproject.yaml
├── requirements.txt           # demo deps for config_requirements.yaml
└── conf/
    ├── config.yaml            # basic — YAML-driven image
    ├── config_requirements.yaml  # deps from a requirements file
    ├── config_pyproject.yaml     # deps from a pyproject
    └── config_custom.yaml     # custom — points at custom_image.build_image
```

Because `example/pyproject.toml` now exists, the launcher's `_detect_project_root` lands here rather than walking up to the repo root, and `local_dirs` mounts only `example/` on the container. The launcher's own `hydra_plugins` package reaches the container independently via Modal's automatic function-source detection (visible in build logs as `Created mount PythonPackage:hydra_plugins`).
