"""Build a Modal App + Image + Function from ``ModalLauncherConf``.

This module imports ``modal`` lazily so unit tests that exercise the pure
config-to-spec mapping don't require ``modal`` to be installed.
"""
from __future__ import annotations

from typing import Any, Callable

import sys

from .config import ModalFunctionConf, ModalImageConf, ModalLauncherConf


def _host_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _resolved_python_version(image_cfg: ModalImageConf) -> str:
    return image_cfg.python_version or _host_python_version()


def build_image_spec(image_cfg: ModalImageConf) -> dict[str, Any]:
    """Pure helper: resolve ``ModalImageConf`` into a normalised spec dict.

    Useful for testing and for ``dry_run`` logging. Does not import modal.
    """
    if image_cfg.image_builder:
        return {"image_builder": image_cfg.image_builder}
    return {
        "python_version": _resolved_python_version(image_cfg),
        "base": image_cfg.base,
        "base_image": image_cfg.base_image,
        "pip_packages": _merge_pip_packages(
            image_cfg.pip_packages, _required_runtime_specs()
        ),
        "apt_packages": sorted(image_cfg.apt_packages),
        "run_commands": list(image_cfg.run_commands),
        "env": dict(image_cfg.env),
        "local_python_modules": list(image_cfg.local_python_modules),
        "local_dirs": [
            {"local_path": m.local_path, "remote_path": m.remote_path}
            for m in image_cfg.local_dirs
        ],
    }


def build_function_kwargs(
    fcfg: ModalFunctionConf, parallelism: int
) -> dict[str, Any]:
    """Pure helper: resolve ``ModalFunctionConf`` -> kwargs for ``app.function``.

    ``secrets`` and ``volumes`` are returned as raw names; the caller resolves
    them via ``modal.Secret.from_name`` / ``modal.Volume.from_name`` once
    modal is imported.
    """
    kwargs: dict[str, Any] = {"timeout": fcfg.timeout}
    if fcfg.gpu:
        kwargs["gpu"] = fcfg.gpu
    if fcfg.cpu is not None:
        kwargs["cpu"] = fcfg.cpu
    if fcfg.memory is not None:
        kwargs["memory"] = fcfg.memory
    if fcfg.retries:
        kwargs["retries"] = fcfg.retries
    if fcfg.region:
        kwargs["region"] = fcfg.region
    if parallelism > 0:
        # Recent Modal SDKs renamed ``concurrency_limit`` -> ``max_containers``.
        # We target modal>=1.4 (see pyproject.toml).
        kwargs["max_containers"] = parallelism
    return kwargs


def _resolve_image_builder(dotted: str) -> Callable[[ModalImageConf], Any]:
    from hydra.utils import get_method

    return get_method(dotted)


# Runtime deps the worker module imports on the remote container.
# These are unconditionally added to every built image so users don't have to
# remember them. ``image_builder`` users own the full image and are expected
# to include these themselves.
_REQUIRED_PIP_PACKAGES = ("hydra-core", "cloudpickle")


def _pin_to_host(pkg_name: str) -> str:
    """Return ``pkg==<host_version>`` when the package is installed locally.

    Pinning the runtime deps shipped to the container to the host's installed
    version closes a real foot-gun: cloudpickle / hydra-core changing pickle
    format across minor versions can silently break deserialization on the
    container. User-supplied pins (e.g. ``hydra-core>=1.3``) still win via
    ``_merge_pip_packages``' name-based dedup.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return f"{pkg_name}=={version(pkg_name)}"
    except PackageNotFoundError:
        return pkg_name


def _required_runtime_specs() -> tuple[str, ...]:
    return tuple(_pin_to_host(p) for p in _REQUIRED_PIP_PACKAGES)


def _pip_pkg_name(spec: str) -> str:
    """Extract the bare package name from a pip requirement string.

    ``hydra-core>=1.3`` -> ``hydra-core``; ``foo[bar]==1.0`` -> ``foo``.
    """
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", " "):
        idx = spec.find(sep)
        if idx != -1:
            spec = spec[:idx]
    return spec.strip().lower()


def _merge_pip_packages(
    user_packages: list[str] | tuple[str, ...],
    required: tuple[str, ...],
) -> list[str]:
    """Merge user-supplied pip specs with required ones, deduping by name.

    User specs win on name conflict (their version constraint is preserved).
    """
    seen: set[str] = set()
    merged: list[str] = []
    for spec in list(user_packages) + list(required):
        name = _pip_pkg_name(spec)
        if name in seen:
            continue
        seen.add(name)
        merged.append(spec)
    return sorted(merged)


def _build_image(image_cfg: ModalImageConf):
    import modal

    if image_cfg.image_builder:
        builder = _resolve_image_builder(image_cfg.image_builder)
        return builder(image_cfg)

    python_version = _resolved_python_version(image_cfg)
    if image_cfg.base == "debian_slim":
        img = modal.Image.debian_slim(python_version=python_version)
    elif image_cfg.base == "from_registry":
        if not image_cfg.base_image:
            raise ValueError(
                "image.base='from_registry' requires image.base_image to be set"
            )
        img = modal.Image.from_registry(
            image_cfg.base_image, python_version=python_version
        )
    else:
        raise ValueError(
            f"Unknown image.base={image_cfg.base!r}; expected 'debian_slim' "
            f"or 'from_registry' (or set image.image_builder for full control)."
        )

    if image_cfg.apt_packages:
        img = img.apt_install(*sorted(image_cfg.apt_packages))
    pip_packages = _merge_pip_packages(image_cfg.pip_packages, _required_runtime_specs())
    if pip_packages:
        img = img.pip_install(*pip_packages)
    for cmd in image_cfg.run_commands:
        img = img.run_commands(cmd)
    if image_cfg.env:
        img = img.env(dict(image_cfg.env))
    if image_cfg.local_python_modules:
        img = img.add_local_python_source(*image_cfg.local_python_modules)
    for mount in image_cfg.local_dirs:
        img = img.add_local_dir(
            mount.local_path,
            remote_path=mount.remote_path,
            ignore=list(mount.ignore),
        )
    return img


def _resolve_function_kwargs(fcfg: ModalFunctionConf, parallelism: int) -> dict[str, Any]:
    import modal

    kwargs = build_function_kwargs(fcfg, parallelism)
    if fcfg.secrets:
        kwargs["secrets"] = [modal.Secret.from_name(s) for s in fcfg.secrets]
    if fcfg.volumes:
        kwargs["volumes"] = {
            mp: modal.Volume.from_name(name)
            for mp, name in fcfg.volumes.items()
        }
    return kwargs


def build_modal_app(cfg: ModalLauncherConf):
    """Build a ``(modal.App, modal.Function)`` pair from launcher config.

    The function is the ephemeral entrypoint that runs one Hydra job.
    Called once per ``ModalLauncher.launch`` invocation.
    """
    import modal

    from . import _worker

    app = modal.App(cfg.app_name)
    image = _build_image(cfg.image)
    fn_kwargs = _resolve_function_kwargs(cfg.function, cfg.parallelism)
    fn = app.function(image=image, **fn_kwargs)(_worker.modal_entry)
    return app, fn
