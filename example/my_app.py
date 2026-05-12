"""Example app showing how to drive the Modal launcher.

See ``example/README.md`` for the two variants (basic, custom_image) and
the dry-run flag. Quick refresher:

    uv run example/my_app.py --multirun lr=0.001,0.01,0.1
    uv run example/my_app.py --config-name=config_custom --multirun lr=0.001,0.01,0.1
"""
from __future__ import annotations

import logging

import hydra
from omegaconf import DictConfig

log = logging.getLogger(__name__)


@hydra.main(version_base=None, config_path="conf", config_name="config")
def main(cfg: DictConfig) -> float:
    log.info("Running job with lr=%s, epochs=%s", cfg.lr, cfg.epochs)
    loss = 1.0
    for _ in range(int(cfg.epochs)):
        loss *= 1.0 - float(cfg.lr)
    log.info("Final loss: %.4f", loss)
    return float(loss)


if __name__ == "__main__":
    main()
