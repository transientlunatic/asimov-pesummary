"""
A minimal fake upstream PE pipeline, for testing asimov-pesummary end-to-end.

``FakeCBCPipeline`` stands in for a real sampler (bilby, RIFT, ...). It does
not run any inference: it synthesises a small but genuinely parseable
posterior samples file and tiny PSD files, then marks itself complete
immediately. A downstream ``pesummary`` production that ``needs:`` this one
can then run the real ``summarypages`` executable against these fixtures,
exercising the full asimov-pesummary integration without the cost of a real
parameter estimation run.

Note that the ``pesummary`` production's own ``--config`` ini is *not*
sourced from here: ``PESummary.submit_dag`` resolves it from its own
production's name/category via ``repository.find_prods(...)``, independent
of ``_previous_assets()``. That ini must be seeded separately as its own
test fixture (see the e2e test blueprints).

This module is only useful for testing and is not registered for use in
production ledgers.
"""

import os

import numpy as np

from asimov.pipeline import Pipeline


class FakeCBCPipeline(Pipeline):
    """
    A minimal testing pipeline which stands in for a real CBC PE pipeline.

    Rather than running any sampler, this pipeline synthesises a small,
    genuinely-parseable set of posterior samples and PSDs (using the same
    recipe PESummary's own test suite uses to exercise ``summarypages``),
    for a downstream ``PESummary`` production to consume via
    ``_previous_assets()``. It completes as soon as these fixtures are
    written, so it never needs its own HTCondor job.

    Parameters
    ----------
    production : :class:`asimov.analysis.Analysis`
        The production this pipeline will run for.
    category : str, optional
        The category of the job.
    """

    name = "FakeCBCPipeline"
    STATUS = {"wait", "stuck", "stopped", "running", "finished"}

    #: GW parameters synthesised into the fake samples file. Kept
    #: non-precessing (zero in-plane/aligned spin) so that the default
    #: non-precessing approximants used in tests don't trip waveform
    #: generation errors in PESummary's plotting stage.
    PARAMETERS = [
        "mass_1", "mass_2", "a_1", "a_2", "tilt_1", "tilt_2",
        "phi_jl", "phi_12", "psi", "theta_jn", "ra", "dec",
        "luminosity_distance", "geocent_time", "redshift",
        "mass_1_source", "mass_2_source", "log_likelihood",
    ]

    def __init__(self, production, category=None):
        super().__init__(production, category)
        self.logger.info("Using the FakeCBCPipeline for testing")

    def _ensure_rundir(self):
        if not self.production.rundir:
            return False
        os.makedirs(self.production.rundir, exist_ok=True)
        return True

    def _samples_path(self):
        return os.path.join(self.production.rundir, "posterior_samples.dat")

    def _make_samples(self, n_samples=50, seed=1234):
        """Write a small, genuinely-parseable posterior samples file."""
        rng = np.random.default_rng(seed)
        parameters = self.PARAMETERS
        data = np.array([rng.random(len(parameters)) for _ in range(n_samples)])

        mass_1 = rng.random(n_samples) * 60 + 10
        q = rng.uniform(0.5, 1.0, n_samples)
        distance = rng.uniform(100, 600, n_samples)
        redshift = np.full(n_samples, 0.1)
        for num in range(n_samples):
            data[num][0] = mass_1[num]
            data[num][1] = mass_1[num] * q[num]
            data[num][2] = 0.0  # a_1
            data[num][3] = 0.0  # a_2
            data[num][12] = distance[num]
            data[num][13] = 1126259462.4  # geocent_time
            data[num][14] = redshift[num]
            data[num][15] = mass_1[num] / (1 + redshift[num])
            data[num][16] = (mass_1[num] * q[num]) / (1 + redshift[num])

        samples_path = self._samples_path()
        np.savetxt(
            samples_path, data, delimiter=" ", header=" ".join(parameters),
            comments="",
        )
        return samples_path

    # Note: this pipeline does not need to write a ``.ini`` for itself.
    # ``PESummary.submit_dag`` resolves ``--config`` from *its own*
    # production's name/category via ``repository.find_prods(...)``, not
    # from ``_previous_assets()`` — so that ini is a separate fixture,
    # seeded directly under the downstream ``pesummary`` production's name.

    def _psd_paths(self):
        ifos = self.production.meta.get("interferometers", ["H1", "L1"])
        return {
            ifo: os.path.join(self.production.rundir, f"{ifo}_psd.dat")
            for ifo in ifos
        }

    def _make_psds(self):
        """Write a tiny flat-ish PSD file for each configured interferometer."""
        rng = np.random.default_rng(4321)
        frequencies = np.linspace(1, 1024, 200)
        psds = self._psd_paths()
        for path in psds.values():
            strains = rng.uniform(1e-24, 1e-23, len(frequencies))
            np.savetxt(path, np.vstack([frequencies, strains]).T, delimiter="\t")
        return psds

    def build_dag(self, user=None, dryrun=False):
        """Materialise the fake samples and PSD files."""
        if dryrun:
            self.logger.info("Dry run: would build fake PE fixtures")
            return
        if not self._ensure_rundir():
            self.logger.warning("No run directory specified, cannot build fixtures")
            return
        self._make_samples()
        self._make_psds()
        self.logger.info(f"Built fake PE fixtures in {self.production.rundir}")

    def submit_dag(self, dryrun=False):
        """Build the fixtures and mark this production complete."""
        self.build_dag(dryrun=dryrun)
        if dryrun:
            self.logger.info("Dry run: would submit fake PE job")
            return 12345
        self.production.status = "complete"
        return 12345

    def detect_completion(self):
        if not self.production.rundir:
            return False
        return os.path.exists(self._samples_path())

    def after_completion(self):
        super().after_completion()
        self.production.status = "complete"

    def samples(self, absolute=False):
        if not self.production.rundir:
            return []
        path = self._samples_path()
        return [os.path.abspath(path) if absolute else path]

    def collect_assets(self):
        """
        Advertise the fake samples and PSDs to downstream productions.

        This is the key piece of wiring: a downstream analysis's
        ``_previous_assets()`` merges whatever ``collect_assets()`` returns
        here, so the ``"samples"``/``"psds"`` keys are what a ``PESummary``
        production (via ``needs:``) will pick up.
        """
        samples = self.samples()
        assets = {"samples": samples[0] if samples else None}
        if self.production.rundir:
            assets["psds"] = self._psd_paths()
        return assets
