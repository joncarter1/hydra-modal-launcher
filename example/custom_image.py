"""Demonstrates the ``image_builder`` escape hatch.

``hydra.launcher.image.image_builder`` accepts a dotted path to a callable
with the signature ``(ModalImageConf) -> modal.Image``. When set, every
other field under ``image:`` in the config is ignored — you own the full
image build in Python.

The callable receives the resolved ``ModalImageConf`` so you can still
read fields from it (e.g. ``image_cfg.python_version``) if you want to
mix config-driven and code-driven choices.

Pin ``hydra-core`` and ``cloudpickle`` here too: the launcher only
auto-injects those when it's the one building the image. With
``image_builder`` set, that injection is skipped and the responsibility
falls to you.
"""
import modal

from hydra_plugins.hydra_modal_launcher.config import ModalImageConf


def build_image(image_cfg: ModalImageConf) -> modal.Image:
    python_version = image_cfg.python_version or "3.12"
    return (
        modal.Image.debian_slim(python_version=python_version)
        .apt_install("git")
        .pip_install(
            "hydra-core>=1.3",   # required by the worker
            "cloudpickle>=3.0",  # required by the worker
            # ... add real training deps here, e.g. "torch==2.5.0"
        )
        .run_commands(
            "echo 'image built via example.custom_image' > /etc/built-by"
        )
        .env({"BUILT_BY": "example.custom_image"})
    )
