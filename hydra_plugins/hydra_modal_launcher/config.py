from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from hydra.core.config_store import ConfigStore


@dataclass
class LocalDirMount:
    local_path: str = "."
    remote_path: str = "/root"
    # gitignore-style globs forwarded to ``Image.add_local_dir(ignore=...)``.
    ignore: List[str] = field(default_factory=list)


@dataclass
class ModalImageConf:
    # Default ``null`` -> match the host's Python (major.minor). Mismatched
    # host/container Python versions can SIGSEGV cloudpickle deserialization
    # when functions are pickled by value (e.g. from ``__main__``).
    python_version: Optional[str] = None
    base: str = "debian_slim"
    base_image: Optional[str] = None
    pip_packages: List[str] = field(default_factory=list)
    # Path to a pip requirements file; forwarded to
    # ``Image.pip_install_from_requirements``. Composable with ``pip_packages``
    # and the pyproject fields.
    pip_requirements: Optional[str] = None
    # Path to a ``pyproject.toml`` whose ``[project].dependencies`` are
    # installed via ``Image.pip_install_from_pyproject``.
    pip_pyproject: Optional[str] = None
    # Optional extras keys for ``pip_pyproject``; forwarded as
    # ``optional_dependencies=[...]``.
    pip_pyproject_extras: List[str] = field(default_factory=list)
    apt_packages: List[str] = field(default_factory=list)
    run_commands: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    # Importable module names passed to Image.add_local_python_source(*modules)
    local_python_modules: List[str] = field(default_factory=list)
    # Filesystem mounts passed to Image.add_local_dir(local_path, remote_path)
    local_dirs: List[LocalDirMount] = field(default_factory=list)
    # Optional code escape hatch: dotted path to a callable
    # (image_cfg: ModalImageConf) -> modal.Image. When set, every other
    # field on ModalImageConf is ignored.
    image_builder: Optional[str] = None


@dataclass
class ModalFunctionConf:
    gpu: Optional[str] = None
    cpu: Optional[float] = None
    memory: Optional[int] = None
    timeout: int = 3600
    secrets: List[str] = field(default_factory=list)
    volumes: Dict[str, str] = field(default_factory=dict)
    retries: int = 0
    region: Optional[str] = None


@dataclass
class ModalLauncherConf:
    _target_: str = (
        "hydra_plugins.hydra_modal_launcher.modal_launcher.ModalLauncher"
    )
    app_name: str = "hydra-modal-launcher"
    parallelism: int = -1
    dry_run: bool = False
    image: ModalImageConf = field(default_factory=ModalImageConf)
    function: ModalFunctionConf = field(default_factory=ModalFunctionConf)
    # Env vars to snapshot from the launching host and inject into each worker
    # container. Implemented as an ephemeral ``modal.Secret.from_dict`` so the
    # values are set before the worker process starts (matching the timing of
    # named secrets). Missing keys are skipped silently.
    env_passthrough: List[str] = field(default_factory=list)


def _register() -> None:
    cs = ConfigStore.instance()
    cs.store(group="hydra/launcher", name="modal", node=ModalLauncherConf)


_register()


__all__ = [
    "LocalDirMount",
    "ModalImageConf",
    "ModalFunctionConf",
    "ModalLauncherConf",
]
