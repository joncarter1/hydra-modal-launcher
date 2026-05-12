"""Top-level worker module shipped to Modal.

Kept import-light so it can be unit-tested without a ``modal`` install.
``modal`` itself is only imported lazily inside ``_modal_job_id``.
"""
from __future__ import annotations

from typing import Any, Sequence


def _modal_job_id(job_num: int) -> str:
    try:
        import modal

        cid = modal.current_function_call_id()
        if cid:
            return str(cid)
    except Exception:
        pass
    return f"modal_{job_num}"


def modal_entry(
    sweep_config: Any,
    job_num: int,
    singleton_state: dict,
    launcher_pickled: bytes,
) -> Any:
    """Worker entrypoint invoked inside a Modal container.

    ``sweep_config`` is fully resolved on the parent and shipped in; the worker
    does not re-run ``load_sweep_config`` because the user's config search
    paths (e.g. ``conf/``) don't exist on the remote container's filesystem.
    """
    import cloudpickle
    from hydra.core.hydra_config import HydraConfig
    from hydra.core.singleton import Singleton
    from hydra.core.utils import run_job, setup_globals
    from omegaconf import open_dict

    launcher = cloudpickle.loads(launcher_pickled)

    Singleton.set_state(singleton_state)
    setup_globals()

    # Refresh the job id with Modal's call id when available; the parent set a
    # placeholder so local stubs / log lines have something useful.
    with open_dict(sweep_config):
        sweep_config.hydra.job.id = _modal_job_id(job_num)
        sweep_config.hydra.job.num = job_num

    HydraConfig.instance().set_config(sweep_config)

    return run_job(
        hydra_context=launcher.hydra_context,
        task_function=launcher.task_function,
        config=sweep_config,
        job_dir_key="hydra.sweep.dir",
        job_subdir_key="hydra.sweep.subdir",
    )
