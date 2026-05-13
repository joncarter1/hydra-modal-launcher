"""E2E env_passthrough test entrypoint.

Logs the value of ``HML_E2E_TOKEN`` (which Hydra/Modal stream back to the
host via ``modal.enable_output()``) so the driving test can verify that
the host-snapshotted env var actually reached the container.
"""
import logging
import os

import hydra
from omegaconf import DictConfig

log = logging.getLogger(__name__)


@hydra.main(version_base=None, config_path="conf", config_name="env_passthrough")
def main(cfg: DictConfig) -> str:
    token = os.environ.get("HML_E2E_TOKEN", "<unset>")
    log.info("HML_E2E_TOKEN_ON_CONTAINER=%s", token)
    return token


if __name__ == "__main__":
    main()
