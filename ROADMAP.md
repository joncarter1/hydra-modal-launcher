# Roadmap

Open items the maintainer flagged but deferred from v0.1.0. None are blockers; they're improvements with clear scope.

Convert to GitHub Issues once the repo is up.

## Correctness / robustness

### Slim the cloudpickled payload

**Problem.** `launch()` currently does `cloudpickle.dumps(self)` and ships the whole `ModalLauncher` instance to every worker. The worker only ever reads `self.task_function` and `self.hydra_context.callbacks`. The rest — `self.config`, `self.hydra_context.config_loader` with its local filesystem paths, `self.params` — is dead weight, and any future code path that touches `config_loader` on the remote will hit a "Primary config directory not found" class of bug (already debugged once for the worker; could regress in callbacks).

**Fix.** Replace the launcher pickle with `(task_function_pickled, callbacks_pickled, sweep_config)` per payload. Pickle `task_function` and `callbacks` once outside the loop, reuse across payloads.

**Files:** `modal_launcher.py:launch`, `_worker.py:modal_entry`.

### Sync real Modal `function_call_id` into local `.hydra/` stubs post-run

**Problem.** Parent-side `_write_local_job_stubs` writes `hydra.job.id: stub_<num>` because Modal hasn't run yet. The worker overwrites with `modal.current_function_call_id()` on the remote, but that value never propagates back to the local stub. Someone browsing `multirun/.../<n>/.hydra/hydra.yaml` post-sweep sees `stub_0` rather than the call id needed to look up the Modal run.

**Fix.** After `starmap` returns, each `JobReturn.cfg` has the real `hydra.job.id`. Re-emit the per-job `hydra.yaml` (or just the `hydra.job.*` block) using the returned configs.

**Files:** `modal_launcher.py:launch`.

## Tests / verification

### End-to-end failure-path test

**Problem.** The success path is covered live on Modal; the exception path — job raises → Modal returns the exception via `return_exceptions=True` → `_to_job_return` maps it to `JobReturn(FAILED)` → Hydra's sweeper handles it — is unit-tested in isolation but never executed against real Modal.

**Fix.** Add an `examples/` or `tests/` script that deliberately raises in the task function and assert `JobReturn(status=FAILED)` comes back with the original exception. Gate behind `MODAL_TOKEN_ID` env var so CI doesn't run it unless wired up.

## Documentation / examples

### `image_builder` escape hatch example

**Problem.** The `image.image_builder` `_target_` field is wired through the schema and code, but no example shows what the contract is (signature, return type, when it's called). A first-time user discovering it in the config reference has to read source to use it.

**Fix.** Add `example/custom_image.py` with a `build_image(image_cfg: ModalImageConf) -> modal.Image` and a one-line config snippet showing how to point at it. Reference from README.

## Features

### `requirements.txt` mode

Single source of truth for user training deps. Today, users duplicate their pins in `image.pip_packages`. A first-class `image.requirements_txt: "requirements.txt"` field that becomes a `pip install -r` step in the built image would remove the duplication.

### Pre-deployed app / `Function.from_name` workflow

Today the launcher always uses `with app.run():` (ephemeral). For users who pre-deploy a heavy image once and want fast subsequent sweeps, a `lookup: {app: ..., function: ...}` config branch that calls `modal.Function.from_name` instead of building locally would skip the per-launch app deploy.

### Auto-detect importable sibling packages

The `__main__` auto-mount currently mounts the whole project root for Layout B. Smarter alternative: detect every top-level dir under project root that has `__init__.py` and add via `add_local_python_source(*names)`. Cleaner mount, fewer bytes shipped.
