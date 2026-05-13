"""E2E failure-path test entrypoint.

Always raises in ``main()``. Driven by ``tests/test_e2e_failure.py`` to
verify that exceptions on the container come back through
``return_exceptions=True`` -> ``_to_job_return`` -> ``JobReturn(FAILED)``
-> Hydra's sweeper, on a real Modal sandbox.
"""
import hydra
from omegaconf import DictConfig


@hydra.main(version_base=None, config_path="conf", config_name="config")
def main(cfg: DictConfig) -> float:
    raise RuntimeError(f"Forced failure for lr={cfg.lr}")


if __name__ == "__main__":
    main()
