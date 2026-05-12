"""Unit tests that don't require a Modal account.

The tests cover:
- ConfigStore registration
- Pure config -> image-spec / function-kwargs mapping
- ``_to_job_return`` exception mapping
- End-to-end ``launch`` flow with a fake modal app
"""
from __future__ import annotations

import sys
import types
from dataclasses import asdict
from unittest.mock import MagicMock

import pytest
from hydra.core.config_store import ConfigStore
from hydra.core.utils import JobReturn, JobStatus

from hydra_plugins.hydra_modal_launcher._modal_app import (
    build_function_kwargs,
    build_image_spec,
)
from hydra_plugins.hydra_modal_launcher.config import (
    LocalDirMount,
    ModalFunctionConf,
    ModalImageConf,
    ModalLauncherConf,
)
from hydra_plugins.hydra_modal_launcher.modal_launcher import (
    ModalLauncher,
    _detect_project_root,
)
from hydra_plugins.hydra_modal_launcher._paths import (
    _resolve_against_project_root,
)


def test_config_store_registration():
    cs = ConfigStore.instance()
    node = cs.load("hydra/launcher/modal.yaml")
    assert node is not None
    assert node.node["_target_"].endswith("ModalLauncher")


def test_build_image_spec_pins_required_deps_to_host_versions():
    from importlib.metadata import version

    image_cfg = ModalImageConf(
        pip_packages=["zlib", "numpy"],
        apt_packages=["zsh", "git"],
        env={"FOO": "bar"},
        local_python_modules=["mypkg"],
    )
    spec = build_image_spec(image_cfg)
    # cloudpickle + hydra-core are auto-merged in, pinned to host versions
    assert f"hydra-core=={version('hydra-core')}" in spec["pip_packages"]
    assert f"cloudpickle=={version('cloudpickle')}" in spec["pip_packages"]
    assert "numpy" in spec["pip_packages"]
    assert "zlib" in spec["pip_packages"]
    # Sorted for cache stability
    assert spec["pip_packages"] == sorted(spec["pip_packages"])
    assert spec["apt_packages"] == ["git", "zsh"]
    assert spec["env"] == {"FOO": "bar"}
    assert spec["local_python_modules"] == ["mypkg"]


def test_build_image_spec_preserves_user_version_pin_for_required_deps():
    image_cfg = ModalImageConf(pip_packages=["hydra-core>=1.3"])
    spec = build_image_spec(image_cfg)
    # User's pin wins on the name collision; we don't also inject the
    # host-pinned version.
    assert "hydra-core>=1.3" in spec["pip_packages"]
    assert not any(
        s.startswith("hydra-core==") for s in spec["pip_packages"]
    )
    # cloudpickle still auto-added and host-pinned
    assert any(s.startswith("cloudpickle==") for s in spec["pip_packages"])


def test_build_image_spec_with_image_builder_ignores_other_fields():
    image_cfg = ModalImageConf(
        pip_packages=["torch"],
        pip_requirements="requirements.txt",
        pip_pyproject="pyproject.toml",
        pip_pyproject_extras=["training"],
        image_builder="my.module.build_image",
    )
    spec = build_image_spec(image_cfg)
    assert spec == {"image_builder": "my.module.build_image"}


def test_build_image_spec_passes_through_pip_requirements():
    spec = build_image_spec(ModalImageConf(pip_requirements="requirements.txt"))
    assert spec["pip_requirements"] == "requirements.txt"
    # Defaults for the other dep sources stay empty / None.
    assert spec["pip_pyproject"] is None
    assert spec["pip_pyproject_extras"] == []


def test_build_image_spec_passes_through_pip_pyproject_and_extras():
    spec = build_image_spec(
        ModalImageConf(
            pip_pyproject="pyproject.toml",
            pip_pyproject_extras=["training", "viz"],
        )
    )
    assert spec["pip_pyproject"] == "pyproject.toml"
    assert spec["pip_pyproject_extras"] == ["training", "viz"]
    assert spec["pip_requirements"] is None


def test_build_image_spec_dep_sources_default_to_none():
    spec = build_image_spec(ModalImageConf())
    assert spec["pip_requirements"] is None
    assert spec["pip_pyproject"] is None
    assert spec["pip_pyproject_extras"] == []


def test_build_function_kwargs_serial():
    fcfg = ModalFunctionConf(gpu="L40S", cpu=2, memory=4096, timeout=600)
    kwargs = build_function_kwargs(fcfg, parallelism=1)
    assert kwargs == {
        "timeout": 600,
        "gpu": "L40S",
        "cpu": 2,
        "memory": 4096,
        "max_containers": 1,
    }


def test_build_function_kwargs_unlimited_parallelism_omits_max_containers():
    fcfg = ModalFunctionConf()
    kwargs = build_function_kwargs(fcfg, parallelism=-1)
    assert "max_containers" not in kwargs


def test_build_function_kwargs_skips_unset_fields():
    fcfg = ModalFunctionConf()
    kwargs = build_function_kwargs(fcfg, parallelism=-1)
    assert kwargs == {"timeout": 3600}


def test_to_job_return_passes_through_jobreturn():
    jr = JobReturn(overrides=["a=1"], status=JobStatus.COMPLETED, _return_value=42)
    out = ModalLauncher._to_job_return(jr, ["a=1"])
    assert out is jr


def test_to_job_return_wraps_exception_as_failed():
    exc = RuntimeError("boom")
    out = ModalLauncher._to_job_return(exc, ["a=1"])
    assert out.status == JobStatus.FAILED
    assert out._return_value is exc
    assert out.overrides == ["a=1"]


def test_to_job_return_wraps_unexpected_value_as_completed():
    out = ModalLauncher._to_job_return({"loss": 0.1}, ["a=1"])
    assert out.status == JobStatus.COMPLETED
    assert out._return_value == {"loss": 0.1}


def test_local_dir_mount_defaults():
    m = LocalDirMount()
    assert m.local_path == "."
    assert m.remote_path == "/root"
    assert m.ignore == []


def test_detect_project_root_finds_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "mypkg").mkdir()
    (tmp_path / "mypkg" / "__init__.py").write_text("")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "train.py").write_text("")

    # Walking up from scripts/ should land at tmp_path (where pyproject lives)
    assert _detect_project_root(tmp_path / "scripts") == tmp_path.resolve()
    # And from within the package too
    assert _detect_project_root(tmp_path / "mypkg") == tmp_path.resolve()


def test_detect_project_root_prefers_nearest_marker(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    inner = tmp_path / "subproj"
    inner.mkdir()
    (inner / "setup.py").write_text("")
    (inner / "src").mkdir()

    # The inner setup.py wins over the outer pyproject.toml
    assert _detect_project_root(inner / "src") == inner.resolve()


def test_detect_project_root_walks_past_unmarked_subdir(tmp_path):
    # Marker at the top; intermediate dirs are unmarked. Walk-up should
    # pass through them rather than stopping early.
    (tmp_path / "pyproject.toml").write_text("")
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert _detect_project_root(deep) == tmp_path.resolve()


def test_resolve_against_project_root_passes_through_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    abs_path = str(tmp_path / "nope.txt")
    # Absolute paths never trigger the walk-up, even when the file is absent.
    assert _resolve_against_project_root(abs_path) == abs_path


def test_resolve_against_project_root_passes_through_existing_cwd_relative(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "requirements.txt").write_text("")
    monkeypatch.chdir(sub)
    # File exists CWD-relative, so the resolver yields to Modal's default
    # semantics rather than rewriting to the project-root absolute path.
    assert _resolve_against_project_root("requirements.txt") == "requirements.txt"


def test_resolve_against_project_root_walks_up_to_find_file(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "requirements.txt").write_text("")
    nested = tmp_path / "scripts"
    nested.mkdir()
    monkeypatch.chdir(nested)
    # No requirements.txt at CWD; walk-up finds project root and the file is
    # there, so the resolver returns the absolute path.
    assert _resolve_against_project_root("requirements.txt") == str(
        (tmp_path / "requirements.txt").resolve()
    )


def test_resolve_against_project_root_returns_original_on_miss(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("")
    nested = tmp_path / "scripts"
    nested.mkdir()
    monkeypatch.chdir(nested)
    # File doesn't exist anywhere; we hand back the original string so Modal
    # raises a clear FileNotFoundError at build time.
    assert _resolve_against_project_root("does-not-exist.txt") == "does-not-exist.txt"


def test_detect_project_root_finds_git_dir(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "scripts").mkdir()
    assert _detect_project_root(tmp_path / "scripts") == tmp_path.resolve()


def test_modal_launcher_conf_defaults():
    cfg = ModalLauncherConf()
    assert cfg.parallelism == -1
    assert cfg.dry_run is False
    assert cfg.app_name == "hydra-modal-launcher"
    # None -> resolved to host python at build time
    assert cfg.image.python_version is None
    assert cfg.function.timeout == 3600


def test_build_image_spec_uses_host_python_when_unset():
    import sys

    spec = build_image_spec(ModalImageConf())
    assert spec["python_version"] == f"{sys.version_info.major}.{sys.version_info.minor}"


def test_build_image_spec_respects_explicit_python_version():
    spec = build_image_spec(ModalImageConf(python_version="3.10"))
    assert spec["python_version"] == "3.10"
