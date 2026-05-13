"""Hydra launcher that submits each multirun job to a Modal function."""
from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any, Sequence

from hydra.core.singleton import Singleton
from hydra.core.utils import (
    JobReturn,
    JobStatus,
    configure_log,
    filter_overrides,
)
from hydra.plugins.launcher import Launcher
from hydra.types import HydraContext, TaskFunction
from omegaconf import DictConfig, OmegaConf, open_dict

from .config import ModalLauncherConf
from ._paths import _PROJECT_ROOT_MARKERS, _detect_project_root  # noqa: F401  (re-exported for tests)

log = logging.getLogger(__name__)


_DEFAULT_PROJECT_IGNORES = (
    "**/.venv/**",
    "**/venv/**",
    "**/.git/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/.ruff_cache/**",
    "**/.tox/**",
    "**/node_modules/**",
    "**/*.egg-info/**",
    "**/dist/**",
    "**/build/**",
    "**/multirun/**",
    "**/outputs/**",
    "**/.DS_Store",
)


class ModalLauncher(Launcher):
    def __init__(self, **params: Any) -> None:
        self.config: DictConfig | None = None
        self.task_function: TaskFunction | None = None
        self.hydra_context: HydraContext | None = None
        self.params: dict[str, Any] = params

    def setup(
        self,
        *,
        hydra_context: HydraContext,
        task_function: TaskFunction,
        config: DictConfig,
    ) -> None:
        self.config = config
        self.task_function = task_function
        self.hydra_context = hydra_context

    def launch(
        self,
        job_overrides: Sequence[Sequence[str]],
        initial_job_idx: int,
    ) -> Sequence[JobReturn]:
        assert self.config is not None
        assert self.hydra_context is not None
        assert self.task_function is not None

        configure_log(self.config.hydra.hydra_logging, self.config.hydra.verbose)
        sweep_dir = Path(str(self.config.hydra.sweep.dir))
        sweep_dir.mkdir(parents=True, exist_ok=True)

        launcher_cfg: ModalLauncherConf = self.config.hydra.launcher  # type: ignore[assignment]

        self._maybe_auto_mount_user_source(launcher_cfg)

        log.info(
            "ModalLauncher: launching %d jobs (parallelism=%d, dry_run=%s)",
            len(job_overrides),
            launcher_cfg.parallelism,
            launcher_cfg.dry_run,
        )
        for idx, overrides in enumerate(job_overrides):
            log.info(
                "    #%d : %s", initial_job_idx + idx, " ".join(filter_overrides(overrides))
            )

        sweep_configs = self._resolve_sweep_configs(job_overrides, initial_job_idx)
        self._write_local_job_stubs(sweep_configs)

        singleton_state = Singleton.get_state()
        import cloudpickle  # local import; not needed for dry_run-only paths

        launcher_pickled = cloudpickle.dumps(self)
        payloads = [
            (sweep_cfg, initial_job_idx + i, singleton_state, launcher_pickled)
            for i, sweep_cfg in enumerate(sweep_configs)
        ]

        if launcher_cfg.dry_run:
            from ._modal_app import build_function_kwargs, build_image_spec

            log.info(
                "dry_run=True; image_spec=%s function_kwargs=%s",
                build_image_spec(launcher_cfg.image),
                build_function_kwargs(launcher_cfg.function, launcher_cfg.parallelism),
            )
            return [
                JobReturn(
                    overrides=list(o),
                    status=JobStatus.COMPLETED,
                    _return_value=None,
                )
                for o in job_overrides
            ]

        from ._modal_app import build_modal_app

        import modal

        app, fn = build_modal_app(launcher_cfg)
        with modal.enable_output(), app.run():
            # Logged through Hydra's handlers so the dashboard link persists
            # to multirun.log; modal.enable_output() only writes to stderr.
            log.info("ModalLauncher: dashboard https://modal.com/apps/%s", app.app_id)
            raw_results = list(fn.starmap(payloads, return_exceptions=True))

        return [
            self._to_job_return(raw, list(o))
            for raw, o in zip(raw_results, job_overrides)
        ]

    @staticmethod
    def _to_job_return(raw: Any, overrides: list[str]) -> JobReturn:
        if isinstance(raw, JobReturn):
            return raw
        if isinstance(raw, BaseException):
            return JobReturn(
                overrides=overrides,
                status=JobStatus.FAILED,
                _return_value=raw,
            )
        # Should not happen — Modal returned a non-JobReturn, non-exception.
        # Wrap it as a completed result with the raw payload.
        return JobReturn(
            overrides=overrides,
            status=JobStatus.COMPLETED,
            _return_value=raw,
        )

    def _maybe_auto_mount_user_source(self, launcher_cfg: ModalLauncherConf) -> None:
        """Add the user's task module to the image's mounts.

        Modal containers start from a clean image: the user's source must be
        present for ``cloudpickle.loads`` to resolve ``task_function`` by
        qualname. We try ``add_local_python_source(<top-level package>)`` first
        and fall back to ``add_local_dir`` on the script's directory if the
        user ran ``python my_app.py`` (where ``__module__ == '__main__'``).
        Either form is skipped if the user opted into ``image_builder``.
        """
        if launcher_cfg.image.image_builder:
            return

        fn = self.task_function
        module = inspect.getmodule(fn) if fn is not None else None
        module_name = getattr(module, "__name__", None)
        module_file = getattr(module, "__file__", None)

        if module_name and module_name != "__main__":
            top = module_name.split(".")[0]
            if top not in launcher_cfg.image.local_python_modules:
                launcher_cfg.image.local_python_modules.append(top)
                log.info("Auto-mounting Python module %r into Modal image", top)
            return

        if module_file:
            from .config import LocalDirMount

            script_dir = Path(module_file).resolve().parent
            project_root = _detect_project_root(script_dir)
            mount_dir = project_root or script_dir

            already = {Path(m.local_path).resolve() for m in launcher_cfg.image.local_dirs}
            if mount_dir.resolve() in already:
                return

            launcher_cfg.image.local_dirs.append(
                LocalDirMount(
                    local_path=str(mount_dir),
                    remote_path="/root",
                    ignore=list(_DEFAULT_PROJECT_IGNORES),
                )
            )
            if project_root is not None:
                log.warning(
                    "task_function's module is '__main__'. Detected project "
                    "root at %s; auto-mounting it -> /root (with default "
                    "ignores for .venv/.git/__pycache__/etc). For more "
                    "predictable behaviour, invoke entrypoints as modules "
                    "(`python -m your_package.your_module`).",
                    mount_dir,
                )
            else:
                log.warning(
                    "task_function's module is '__main__' and no project "
                    "marker (pyproject.toml/setup.py/setup.cfg/.git) was "
                    "found at or above %s. Auto-mounting just that directory "
                    "-> /root; sibling packages will be unreachable. Add them "
                    "via image.local_python_modules or image.local_dirs.",
                    mount_dir,
                )
            return

        log.error(
            "Could not detect a source path for task_function. The remote "
            "Modal container will fail to unpickle the launcher unless your "
            "code is available via image.local_python_modules or "
            "image.local_dirs."
        )

    def _resolve_sweep_configs(
        self,
        job_overrides: Sequence[Sequence[str]],
        initial_job_idx: int,
    ) -> list[DictConfig]:
        """Resolve one ``sweep_config`` per job on the parent process.

        Done parent-side because the user's config search paths (``conf/``)
        don't exist on the remote container's filesystem. ``hydra.job.id`` is
        set to a stub here; the worker overwrites it with Modal's real
        function-call id once the job lands on a container.
        """
        assert self.hydra_context is not None
        assert self.config is not None

        configs: list[DictConfig] = []
        for i, overrides in enumerate(job_overrides):
            job_num = initial_job_idx + i
            sweep_config = self.hydra_context.config_loader.load_sweep_config(
                self.config, list(overrides)
            )
            with open_dict(sweep_config):
                sweep_config.hydra.job.id = f"stub_{job_num}"
                sweep_config.hydra.job.num = job_num
            configs.append(sweep_config)
        return configs

    @staticmethod
    def _write_local_job_stubs(sweep_configs: Sequence[DictConfig]) -> None:
        """Materialise ``<sweep>/<idx>/.hydra/{config,hydra,overrides}.yaml``.

        ``run_job`` runs remotely and writes these files inside the Modal
        container's ephemeral FS; they don't sync back. We replicate the
        resolved per-job config locally so downstream tooling (and humans
        browsing the sweep dir) see the expected layout.
        """
        for sweep_config in sweep_configs:
            try:
                subdir = str(sweep_config.hydra.sweep.subdir)
                out_dir = Path(str(sweep_config.hydra.sweep.dir)) / subdir
                hydra_dir = out_dir / ".hydra"
                hydra_dir.mkdir(parents=True, exist_ok=True)

                cfg_for_user = OmegaConf.masked_copy(
                    sweep_config,
                    [k for k in sweep_config.keys() if k != "hydra"],  # type: ignore[union-attr]
                )
                (hydra_dir / "config.yaml").write_text(
                    OmegaConf.to_yaml(cfg_for_user)
                )
                (hydra_dir / "hydra.yaml").write_text(
                    OmegaConf.to_yaml(sweep_config.hydra)
                )
                overrides = list(sweep_config.hydra.overrides.task)
                (hydra_dir / "overrides.yaml").write_text(
                    OmegaConf.to_yaml(overrides)
                )
            except Exception as exc:  # pragma: no cover - best-effort
                log.warning(
                    "Failed to write local .hydra/ stub for job %s: %s",
                    sweep_config.hydra.job.num,
                    exc,
                )
