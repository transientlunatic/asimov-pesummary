# Setting up a real end-to-end test for an asimov pipeline plugin

This describes the pattern used in this repo (`asimov-pesummary`) to test a
pipeline plugin against its *real* downstream executable, without needing a
real gravitational-wave analysis to run first. It's written to be copied into
other asimov pipeline plugin repos (`asimov-bilby`, `asimov-rift`, ...) and
adapted.

## The core idea

Your plugin almost certainly consumes the output of an upstream analysis
(samples, PSDs, calibration envelopes, ...) via `production._previous_assets()`,
and hands it to a real external executable (`summarypages`, `bilby_pipe`,
whatever). A purely mocked unit test suite (mock `htcondor`, mock the
production, assert on the constructed CLI command) never actually proves that
executable can parse what you hand it — and that's usually where the real
bugs live.

Instead of running a real upstream analysis (slow, heavy dependencies), write
a **fake upstream pipeline**: a tiny `Pipeline` subclass that synthesises a
small but *genuinely parseable* fixture of the right shape, completes
instantly, and advertises that fixture through the same
`collect_assets()` → `_previous_assets()` machinery a real pipeline would use.
Your plugin then runs against real fixture data, through its real code path,
with the real downstream executable — just fast and dependency-light.

## Step 0: reverse-engineer the input contract, and spike it by hand first

Before touching asimov at all:

1. Read your plugin's `submit_dag()` to find every file it hands to the
   downstream executable and in what format.
2. Check whether the downstream tool's own test suite ships fixture
   generators for exactly this purpose — it's worth grepping the installed
   package before hand-rolling a format (we found pesummary ships
   `pesummary.tests.base.make_result_file`, `make_psd`, `make_calibration`,
   and a 3-line `example_config.ini`, which told us its `--samples` flag
   happily accepts a plain whitespace-delimited `.dat` file with a header
   row — no bilby dependency needed).
3. Write a **throwaway script** that generates the fixture and invokes the
   real downstream executable directly (no asimov involved). Iterate here —
   it's much faster than debugging through asimov + CI. Only move on once
   this actually produces valid output.

Don't skip this. Every asimov-specific bug we hit later was a *wiring* bug;
the fixture format itself was solved once, up front, this way.

## Step 1: write the fake upstream pipeline

A minimal example (trimmed from `asimov_pesummary/testing.py`):

```python
from asimov.pipeline import Pipeline

class FakeCBCPipeline(Pipeline):
    name = "FakeCBCPipeline"

    def build_dag(self, user=None, dryrun=False):
        # Write your fixture files here. No real HTCondor job needed —
        # just materialise files and return; this keeps CI fast and means
        # only the *real* pipeline under test goes through HTCondor.
        ...

    def submit_dag(self, dryrun=False):
        self.build_dag(dryrun=dryrun)
        self.production.status = "complete"
        return 12345  # dummy cluster id

    def detect_completion(self):
        return os.path.exists(self._samples_path())

    def collect_assets(self):
        # This is THE key piece of wiring. asimov's `_previous_assets()`
        # merges whatever this returns — there is no automatic discovery.
        # The dict keys here must match exactly what the downstream
        # pipeline's `_previous_assets().get("...")` calls expect.
        return {"samples": self._samples_path(), "psds": self._psd_paths()}
```

Register it as a real entry point so it's usable from a ledger, just like a
production pipeline:

```toml
[project.entry-points."asimov.pipelines"]
fakecbcpipeline = "yourpackage.testing:FakeCBCPipeline"
```

## Step 2: the gotchas that only show up through the real asimov CLI

We validated `FakeCBCPipeline`/`PESummary` by calling `.submit_dag()` directly
in a Python script first, and it looked fine — but that **bypasses several
generic hooks asimov's CLI wraps around every pipeline**. These only surface
once you actually run `asimov manage build submit`, so budget time for this
step and don't skip straight to CI:

- **Every pipeline needs `build_dag()`, even as a no-op.** asimov's generic
  `manage build submit` unconditionally calls `pipe.build_dag(dryrun=...)`
  before `pipe.submit_dag(...)`, wrapped in a `try/except` that only catches
  `PipelineException`/`ValueError` — a missing method is an uncaught
  `AttributeError` that crashes the whole command. If all your work already
  happens in `submit_dag`, just add:
  ```python
  def build_dag(self, user=None, dryrun=False):
      pass
  ```

- **`manage build` auto-generates a production's `.ini` if one doesn't
  already exist**, via `production.make_config()`, which looks for a
  Liquid/Jinja2 template. It checks, in order: `config.get("templating",
  "directory")`, then `pipeline.config_template` (a property/attribute you
  can define), then falls back to a template bundled *inside asimov's own
  package* (`asimov/configs/<pipeline-name>.ini`) — which won't exist for
  your plugin. Either:
  - give your fake pipeline a `config_template` property pointing at a
    trivial template you ship as package data, or
  - pre-seed a real `.ini` file directly in the test event's git repository
    before running `manage build`, so `find_prods(...)` finds it and skips
    generation entirely.

  Note this ini is resolved **per-production**, by that production's own
  `name`/`category` — not inherited from an upstream production via
  `_previous_assets()`. If your real (downstream) pipeline also reads a
  config file via `repository.find_prods(self.production.name, ...)`,
  it needs its *own* ini seeded under its own production name, separate
  from the fake upstream one.

- **`collect_assets()` isn't automatic.** Having a `samples()` method on
  your pipeline does nothing on its own — only what `collect_assets()`
  explicitly returns is visible to `_previous_assets()`. (We found asimov's
  own bundled `SimpleTestPipeline` has this exact gap, for reference — it's
  an easy thing to forget.)

- **Class-level attributes computed from `config.get(...)` can be stale.**
  If your executable path is set as a class attribute (`executable =
  os.path.join(config.get(...), ...)`), it gets evaluated once at import
  time. Depending on import ordering this may run before the current
  project's `.asimov/asimov.conf` is loaded, silently capturing an empty or
  default value. Prefer computing it at call time, or verify explicitly with
  a real CLI dry run rather than assuming it's fine because a quick Python
  script showed the right value (imports happen in different orders there).

- **Use the asimov ≥0.7 scheduler interface, not hand-rolled htcondor2.**
  `self.scheduler` (from the base `Pipeline` class, lazily configured from
  `condor`/`slurm` config) plus `asimov.scheduler_utils.create_job_from_dict`
  replace manual `htcondor.Submit`/`Schedd`/`.transaction()` calls — which
  are liable to break across htcondor2 API versions (we hit
  `AttributeError: 'Schedd' object has no attribute 'transaction'` from
  exactly this). It also gets you Slurm support for free:
  ```python
  from asimov.scheduler_utils import create_job_from_dict
  job = create_job_from_dict(submit_description)  # same dict shape as before
  cluster_id = self.scheduler.submit(job)
  ```
  If your `Pipeline` subclass overrides `__init__` without calling
  `super().__init__()`, make sure to set `self._scheduler = None` yourself —
  that's what the `scheduler` property checks.

- **Ledger config doesn't always merge where you'd expect.** We assumed a
  project-level `configuration` block's `waveform: {minimum frequency: ...}`
  would merge down into every production's `meta`; it didn't — only
  `postprocessing.*` merged as expected. Don't assume; print
  `production.meta` after applying your blueprints and check what actually
  landed before debugging further downstream.

## Step 3: ledger blueprints

You'll want, in `tests/test_blueprints/`:
- a `configuration` blueprint with your test-only settings (short sampler
  runs are irrelevant here since there's no real sampler, but keep
  `postprocessing.<your-pipeline>` settings realistic),
- a minimal `event` blueprint (no real strain data needed if your fake
  pipeline never touches it),
- an `analysis` blueprint for the fake upstream pipeline,
- an `analysis` blueprint for the real pipeline under test, with
  `needs: [<fake-upstream-name>]`.

## Step 4: validate locally before touching CI

In order, cheapest-to-most-realistic:
1. Run your Step-0 spike script against the real downstream executable.
2. Build a scratch asimov project by hand (`asimov init`, apply your
   blueprints), and drive it via the **real CLI** — `asimov apply`,
   `asimov manage build submit`, `asimov monitor` — not direct Python calls,
   for exactly the reasons in Step 2.
3. If you don't have a local HTCondor collector running (and especially if
   your machine already has a *real* HTCondor configuration — host certs,
   security tokens — rather than being a disposable sandbox), don't start
   `condor_master` just to test locally. Validate everything up to the
   scheduler `.submit()` call, and let CI's disposable `htcondor/mini`
   container exercise the real submission.

## Step 5: the CI workflow

The `htcondor/mini:latest` container pattern (see `.github/workflows/e2e.yml`
and the vendored composite actions under `.github/actions/` in this repo) is
reusable as-is:
- `setup-htcondor` / `create-submit-user` / `run-asimov-command` /
  `wait-for-files` are generic — copy them verbatim.
- `setup-pesummary-env` is the one you rename/adapt per-plugin (it's just
  "provision a conda env and `pip install -e .[test]`").
- **Use `$CONDA_PREFIX`, not `dirname dirname $(which python)`**, to find
  the environment prefix for `pipelines/environment`. The `htcondor/mini`
  image is minimal and may not even have `which` installed — a failed
  command substitution there silently produces an empty string rather than
  an error, which asimov then happily accepts, and the resulting relative
  executable path only surfaces later as a bewildering *HTCondor held job*
  ("Transfer input files failure... No such file or directory") rather than
  an obvious config error. Guard it explicitly:
  ```bash
  if [ -z "$CONDA_PREFIX" ] || [ ! -x "$CONDA_PREFIX/bin/your-executable" ]; then
    echo "::error::CONDA_PREFIX ('$CONDA_PREFIX') does not contain bin/your-executable"
    exit 1
  fi
  ```

## Step 6 (optional): publish the output for visual regression checks

If your downstream tool produces an HTML report (like `summarypages` does),
it's worth publishing it to GitHub Pages so you can eyeball regressions
across branches/tags rather than just getting a pass/fail signal. See the
`publish-pages` job in `.github/workflows/e2e.yml` for the pattern:
- the test job uploads the generated site as a build artifact;
- a separate job (its own `permissions: contents: write`) downloads it and
  pushes it to the `gh-pages` branch with
  `peaceiris/actions-gh-pages@v4` and `keep_files: true` — that flag is
  what makes it non-destructive, only touching its own `destination_dir`
  subfolder;
- destination is computed per event: `branch/<name>/` (overwritten each
  push), `tag/<name>/` (new directory per tag, so these persist forever),
  `pr/<number>/`;
- skip (don't fail) the publish job for PRs from forks — `GITHUB_TOKEN` is
  read-only there regardless of the `permissions:` block, so attempting the
  push would otherwise show a confusing red X on an external contributor's
  PR even though the actual test passed.

## Summary checklist

- [ ] Spiked the fixture format against the real downstream executable,
      standalone, before touching asimov
- [ ] Fake pipeline: `build_dag` + `submit_dag` both defined, completes
      without a real HTCondor job
- [ ] `collect_assets()` returns exactly the keys the real pipeline reads
      from `_previous_assets()`
- [ ] `config_template` (or pre-seeded ini) so `manage build` doesn't crash
- [ ] Real pipeline's own ini (if it needs one) seeded under its own
      production name
- [ ] Validated via the real `asimov` CLI locally, not just direct Python
      calls
- [ ] Uses `self.scheduler` / `create_job_from_dict`, not hand-rolled
      htcondor2 calls
- [ ] CI env setup uses `$CONDA_PREFIX`, not `which`-based path parsing
- [ ] (optional) Output published somewhere browsable for regression checks
