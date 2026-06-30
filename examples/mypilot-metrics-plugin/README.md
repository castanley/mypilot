# Example extension: `mypilot-metrics-plugin`

A minimal, working example of how to extend the MyPilot API without modifying it.

The API exposes exactly one extension point. At startup, after mounting its own routes, it does the
equivalent of:

```python
from importlib.metadata import entry_points

for ep in entry_points(group="mypilot.app"):
    ep.load()(app)   # call setup(app) with the FastAPI application
```

So an extension is just an installable Python package that registers a `setup(app)` callable under
the `mypilot.app` entry-point group (see this package's [`pyproject.toml`](pyproject.toml)) and does
whatever it likes with the FastAPI `app` — mount routers, add middleware, register startup hooks.

With no extension installed, the loop does nothing and the app runs unchanged.

## Try it

```bash
pip install -e examples/mypilot-metrics-plugin
# restart the API, then:
curl http://localhost:8000/api/metrics
# mypilot_process_uptime_seconds 12.345
```

Uninstall the package and `/api/metrics` is gone — the core app is untouched either way.

## Write your own

1. Make a package with a `setup(app: FastAPI) -> None` function.
2. Declare it under `[project.entry-points."mypilot.app"]` in your `pyproject.toml`.
3. `pip install` it next to the API.
