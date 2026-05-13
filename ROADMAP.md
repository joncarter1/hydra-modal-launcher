# Roadmap

Open items the maintainer flagged but deferred from v0.1.0. None are blockers; they are improvements with clear scope. Track them as GitHub Issues as they get picked up.

## Features

### Pre-deployed app / `Function.from_name` workflow

Today the launcher always uses `with app.run():` (ephemeral). For users who pre-deploy a heavy image once and want fast subsequent sweeps, a `lookup: {app: ..., function: ...}` config branch that calls `modal.Function.from_name` instead of building locally would skip the per-launch app deploy.