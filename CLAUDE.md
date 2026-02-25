# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install for development (includes test and doc dependencies)
pip install -e ".[docs,test]"

# Run tests
pytest

# Run a single test file
pytest tests/test_pesummary.py

# Run a single test
pytest tests/test_pesummary.py::TestClassName::test_method_name
```

Tests use `pytest-cov` and automatically report coverage for `asimov_pesummary`. Coverage config is in `pyproject.toml` under `[tool.pytest.ini_options]`.

Versioning is handled by `setuptools_scm` — there is no hardcoded version string.

## Architecture

This is an **Asimov pipeline plugin** that integrates [PESummary](https://lscsoft.docs.ligo.org/pesummary/) as a post-processing step for gravitational wave parameter estimation.

### Plugin registration

The package registers itself as an Asimov pipeline via the entry point in `pyproject.toml`:
```
[project.entry-points."asimov.pipelines"]
pesummary = "asimov_pesummary:PESummary"
```
Asimov discovers and loads this class automatically when the package is installed.

### Core class: `PESummary` (`asimov_pesummary/pesummary.py`)

Inherits from `asimov.pipeline.Pipeline`. The two key methods are:

- **`submit_dag(dryrun=False)`** — Builds the `summarypages` CLI command and submits it as an HTCondor job. It reads PE configuration from `production.meta["postprocessing"]["pesummary"]` and retrieves upstream results (samples, PSDs, calibration envelopes) via `self.production._previous_assets()`.

- **`results()`** — Returns a dict of output file paths, primarily the `posterior_samples.h5` metafile under `<webroot>/<event>/<production>/pesummary/samples/`.

### Configuration keys (`production.meta["postprocessing"]["pesummary"]`)

The plugin reads these optional keys from the Asimov ledger:
- `cosmology`, `redshift`, `skymap samples`, `evolve spins`, `multiprocess`, `regenerate`, `calculate`
- `accounting group` — if set, adds HTCondor accounting group to the job

The `summarypages` executable path is resolved from `config.get("pipelines", "environment")`.

### HTCondor compatibility

The code tries to import `htcondor2` first, falling back to `htcondor`, to support both the legacy and new HTCondor Python bindings.
