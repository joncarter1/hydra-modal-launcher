# Examples

Two ways to run the same `my_app.py`, showing both image-customisation paths.

## 1. Basic — YAML-driven image

```bash
uv run example/my_app.py --multirun lr=0.001,0.01,0.1
```

Config: [`conf/config.yaml`](conf/config.yaml). The launcher builds the image from `image.pip_packages` and friends, and auto-pins runtime deps (`hydra-core`, `cloudpickle`) to your host's installed versions.

## 2. Custom image — full Python control

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
├── my_app.py                  # @hydra.main entrypoint, shared by both configs
├── custom_image.py            # build_image() referenced by config_custom.yaml
└── conf/
    ├── config.yaml            # basic — YAML-driven image
    └── config_custom.yaml     # custom — points at custom_image.build_image
```
