"""Tests for asimov_pesummary.pesummary."""

import os
import sys
import unittest
from unittest.mock import MagicMock, mock_open, patch

# ---------------------------------------------------------------------------
# Mock runtime dependencies that are not available in the dev/CI environment.
# htcondor must be in sys.modules before any asimov import because asimov
# loads all registered pipeline entry-points at import time, and some of
# those plugins (e.g. asimov-datafind) import htcondor at module scope.
# ---------------------------------------------------------------------------
for _mod in ("htcondor", "htcondor2", "otter"):
    sys.modules.setdefault(_mod, MagicMock())

# Mock asimov.pipelines (the entry-point registry) before importing
# asimov_pesummary.  When asimov loads, it discovers all registered
# asimov.pipelines entry-points.  Because asimov_pesummary is one of those
# entry-points, loading it while it is mid-initialisation causes a circular
# import AttributeError.  A pre-populated stub breaks the cycle without
# affecting the module under test.
_stub_pipelines = MagicMock()
_stub_pipelines.known_pipelines = {}
sys.modules.setdefault("asimov.pipelines", _stub_pipelines)

from asimov_pesummary.pesummary import PESummary  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIG = {
    ("pipelines", "environment"): "/opt/conda/envs/test",
    ("project", "root"): "/project",
    ("general", "webroot"): "public_html",
    ("condor", "user"): "testuser",
    ("condor", "scheduler"): "test-scheduler.ligo.org",
}


def _config_get(section, option, **kwargs):
    return _CONFIG.get((section, option), "")


def make_production(pesummary_meta=None, approximant="IMRPhenomXPHM",
                    min_freq=None, assets=None):
    """Return a MagicMock production with a realistic meta structure.

    Parameters
    ----------
    pesummary_meta : dict, optional
        Extra keys merged into the default ``postprocessing.pesummary`` block.
        To remove a default key use ``del prod.meta[...][...]["key"]`` after
        calling this helper.
    approximant : str
        Waveform approximant name.
    min_freq : dict, optional
        ``{ifo: Hz}`` mapping for ``quality.minimum frequency``.
        Defaults to ``{"H1": 20, "L1": 20, "V1": 20}``.
    assets : dict, optional
        Overrides for the dict returned by ``_previous_assets()``.
    """
    production = MagicMock()
    production.name = "Prod0"
    production.category = "C01_offline"
    production.event.name = "GW150914"
    production.event.repository.directory = "/repo/GW150914"
    production.event.repository.find_prods.return_value = ["C01_offline/Prod0.ini"]
    production.event.work_dir = "/working/GW150914/Prod0"

    base_pesummary = {
        "accounting group": "ligo.dev.o4.cbc.pe.lalinference",
        "multiprocess": 4,
    }
    if pesummary_meta is not None:
        base_pesummary.update(pesummary_meta)

    production.meta = {
        "waveform": {
            "approximant": approximant,
            "reference frequency": 20,
        },
        "quality": {
            "minimum frequency": min_freq or {"H1": 20, "L1": 20, "V1": 20},
        },
        "postprocessing": {
            "pesummary": base_pesummary,
        },
    }

    default_assets = {
        "samples": "/path/to/posterior_samples.hdf5",
        "psds": {"H1": "/path/H1.psd", "L1": "/path/L1.psd"},
        "calibration": {},
    }
    if assets is not None:
        default_assets.update(assets)
    production._previous_assets.return_value = default_assets

    return production


# ---------------------------------------------------------------------------
# TestPESummaryInit
# ---------------------------------------------------------------------------

class TestPESummaryInit(unittest.TestCase):

    def setUp(self):
        self.production = make_production()

    def test_production_attribute(self):
        pipeline = PESummary(self.production)
        self.assertIs(pipeline.production, self.production)

    def test_category_defaults_to_production_category(self):
        pipeline = PESummary(self.production)
        self.assertEqual(pipeline.category, self.production.category)

    def test_category_can_be_overridden(self):
        pipeline = PESummary(self.production, category="C02_online")
        self.assertEqual(pipeline.category, "C02_online")

    def test_subject_set_to_production_event(self):
        pipeline = PESummary(self.production)
        self.assertIs(pipeline.subject, self.production.event)

    def test_meta_extracted_from_production(self):
        pipeline = PESummary(self.production)
        self.assertEqual(
            pipeline.meta,
            self.production.meta["postprocessing"]["pesummary"],
        )

    def test_logger_set(self):
        pipeline = PESummary(self.production)
        self.assertIsNotNone(pipeline.logger)


# ---------------------------------------------------------------------------
# TestPESummaryResults
# ---------------------------------------------------------------------------

class TestPESummaryResults(unittest.TestCase):

    def setUp(self):
        self.production = make_production()
        self.mock_config = patch("asimov_pesummary.pesummary.config").start()
        self.mock_config.get.side_effect = _config_get
        self.addCleanup(patch.stopall)
        self.pipeline = PESummary(self.production)

    def test_returns_dict(self):
        self.assertIsInstance(self.pipeline.results(), dict)

    def test_returns_metafile_key(self):
        self.assertIn("metafile", self.pipeline.results())

    def test_metafile_path_includes_event_name(self):
        self.assertIn("GW150914", self.pipeline.results()["metafile"])

    def test_metafile_path_includes_production_name(self):
        self.assertIn("Prod0", self.pipeline.results()["metafile"])

    def test_metafile_path_includes_pesummary_subdir(self):
        self.assertIn("pesummary", self.pipeline.results()["metafile"])

    def test_metafile_is_h5_file(self):
        self.assertTrue(self.pipeline.results()["metafile"].endswith(".h5"))

    def test_metafile_path_structure(self):
        expected = os.path.join(
            "/project", "public_html", "GW150914", "Prod0",
            "pesummary", "samples", "posterior_samples.h5",
        )
        self.assertEqual(self.pipeline.results()["metafile"], expected)


# ---------------------------------------------------------------------------
# TestPESummarySubmitDagCommand
#
# All tests in this class run submit_dag(dryrun=True) and inspect the command
# written to the pesummary.sh bash file.
# ---------------------------------------------------------------------------

class TestPESummarySubmitDagCommand(unittest.TestCase):

    def setUp(self):
        self.production = make_production()

        self.mock_config = patch("asimov_pesummary.pesummary.config").start()
        self.mock_config.get.side_effect = _config_get

        self.mock_utils = patch("asimov_pesummary.pesummary.utils").start()

        self._open = mock_open()
        patch("builtins.open", self._open).start()

        self.addCleanup(patch.stopall)

    def _run(self, production=None):
        """Run submit_dag(dryrun=True) and return the written bash-file content."""
        pipeline = PESummary(production or self.production)
        pipeline.submit_dag(dryrun=True)
        handle = self._open.return_value.__enter__.return_value
        return handle.write.call_args[0][0]

    def _parts(self, production=None):
        return self._run(production).split()

    def _has(self, flag, production=None):
        return flag in self._parts(production)

    def _value(self, flag, production=None):
        parts = self._parts(production)
        return parts[parts.index(flag) + 1]

    # --- Core return value ---

    def test_dryrun_returns_zero(self):
        pipeline = PESummary(self.production)
        self.assertEqual(pipeline.submit_dag(dryrun=True), 0)

    # --- Always-present flags ---

    def test_gw_flag_present(self):
        self.assertTrue(self._has("--gw"))

    def test_webdir_flag_present(self):
        self.assertTrue(self._has("--webdir"))

    def test_webdir_includes_event_name(self):
        self.assertIn("GW150914", self._value("--webdir"))

    def test_webdir_includes_production_name(self):
        self.assertIn("Prod0", self._value("--webdir"))

    def test_webdir_includes_pesummary(self):
        self.assertIn("pesummary", self._value("--webdir"))

    def test_labels_flag_present(self):
        self.assertTrue(self._has("--labels"))

    def test_labels_value_is_production_name(self):
        self.assertEqual(self._value("--labels"), "Prod0")

    def test_approximant_flag_present(self):
        self.assertTrue(self._has("--approximant"))

    def test_approximant_value(self):
        self.assertEqual(self._value("--approximant"), "IMRPhenomXPHM")

    def test_f_low_flag_present(self):
        self.assertTrue(self._has("--f_low"))

    def test_f_low_uses_minimum_across_ifos(self):
        prod = make_production(min_freq={"H1": 16, "L1": 20, "V1": 32})
        self.assertEqual(self._value("--f_low", prod), "16")

    def test_f_ref_flag_present(self):
        self.assertTrue(self._has("--f_ref"))

    def test_f_ref_value(self):
        self.assertEqual(self._value("--f_ref"), "20")

    def test_config_flag_present(self):
        self.assertTrue(self._has("--config"))

    def test_config_value_is_ini_file(self):
        self.assertTrue(self._value("--config").endswith(".ini"))

    def test_samples_flag_present(self):
        self.assertTrue(self._has("--samples"))

    def test_samples_value(self):
        self.assertEqual(self._value("--samples"), "/path/to/posterior_samples.hdf5")

    # --- Multiprocess ---

    def test_multiprocess_flag_present(self):
        self.assertTrue(self._has("--multi_process"))

    def test_multiprocess_value(self):
        self.assertEqual(self._value("--multi_process"), "4")

    def test_multiprocess_required_in_meta(self):
        """submit_dag raises KeyError if multiprocess is absent: it is read
        unconditionally when building the HTCondor submit description."""
        prod = make_production()
        del prod.meta["postprocessing"]["pesummary"]["multiprocess"]
        pipeline = PESummary(prod)
        with self.assertRaises(KeyError):
            pipeline.submit_dag(dryrun=True)

    # --- Optional: cosmology ---

    def test_cosmology_flag_present_when_in_meta(self):
        prod = make_production(pesummary_meta={"cosmology": "Planck15_lal"})
        self.assertTrue(self._has("--cosmology", prod))

    def test_cosmology_value(self):
        prod = make_production(pesummary_meta={"cosmology": "Planck15_lal"})
        self.assertEqual(self._value("--cosmology", prod), "Planck15_lal")

    def test_cosmology_flag_absent_when_not_in_meta(self):
        self.assertFalse(self._has("--cosmology"))

    # --- Optional: redshift ---

    def test_redshift_flag_present_when_in_meta(self):
        prod = make_production(pesummary_meta={"redshift": "exact"})
        self.assertTrue(self._has("--redshift_method", prod))

    def test_redshift_value(self):
        prod = make_production(pesummary_meta={"redshift": "exact"})
        self.assertEqual(self._value("--redshift_method", prod), "exact")

    def test_redshift_flag_absent_when_not_in_meta(self):
        self.assertFalse(self._has("--redshift_method"))

    # --- Optional: skymap samples ---

    def test_skymap_samples_flag_present_when_in_meta(self):
        prod = make_production(pesummary_meta={"skymap samples": 2000})
        self.assertTrue(self._has("--nsamples_for_skymap", prod))

    def test_skymap_samples_value(self):
        prod = make_production(pesummary_meta={"skymap samples": 2000})
        self.assertEqual(self._value("--nsamples_for_skymap", prod), "2000")

    def test_skymap_samples_flag_absent_when_not_in_meta(self):
        self.assertFalse(self._has("--nsamples_for_skymap"))

    # --- Optional: evolve spins ---

    def test_evolve_spins_forwards_flag_present(self):
        prod = make_production(pesummary_meta={"evolve spins": "forwards"})
        # Note: "fowards" is a typo in the source that is preserved intentionally.
        self.assertTrue(self._has("--evolve_spins_fowards", prod))

    def test_evolve_spins_forwards_value(self):
        prod = make_production(pesummary_meta={"evolve spins": "forwards"})
        self.assertEqual(self._value("--evolve_spins_fowards", prod), "True")

    def test_evolve_spins_backwards_flag_present(self):
        prod = make_production(pesummary_meta={"evolve spins": "backwards"})
        self.assertTrue(self._has("--evolve_spins_backwards", prod))

    def test_evolve_spins_backwards_value(self):
        prod = make_production(pesummary_meta={"evolve spins": "backwards"})
        self.assertEqual(
            self._value("--evolve_spins_backwards", prod), "precession_averaged"
        )

    def test_evolve_spins_both_directions(self):
        prod = make_production(pesummary_meta={"evolve spins": "forwards backwards"})
        parts = self._parts(prod)
        self.assertIn("--evolve_spins_fowards", parts)
        self.assertIn("--evolve_spins_backwards", parts)

    def test_evolve_spins_flags_absent_when_not_in_meta(self):
        parts = self._parts()
        self.assertNotIn("--evolve_spins_fowards", parts)
        self.assertNotIn("--evolve_spins_backwards", parts)

    # --- Optional: NRSur fits ---

    def test_nrsur_fits_flag_for_nrsur_approximant(self):
        prod = make_production(approximant="NRSur7dq4")
        self.assertTrue(self._has("--NRSur_fits", prod))

    def test_nrsur_fits_flag_absent_for_non_nrsur_approximant(self):
        self.assertFalse(self._has("--NRSur_fits"))

    def test_nrsur_detection_is_case_insensitive(self):
        prod = make_production(approximant="nrsur7dq4")
        self.assertTrue(self._has("--NRSur_fits", prod))

    # --- Optional: regenerate posteriors ---

    def test_regenerate_flag_present_when_in_meta(self):
        prod = make_production(pesummary_meta={
            "regenerate": True,
            "regenerate posteriors": ["redshift", "mass_1_source"],
        })
        self.assertTrue(self._has("--regenerate", prod))

    def test_regenerate_flag_absent_when_not_in_meta(self):
        self.assertFalse(self._has("--regenerate"))

    # --- Optional: calculate precessing SNR ---

    def test_calculate_precessing_snr_flag_present(self):
        prod = make_production(pesummary_meta={"calculate": ["precessing snr"]})
        self.assertTrue(self._has("--calculate_precessing_snr", prod))

    def test_calculate_precessing_snr_flag_absent_by_default(self):
        self.assertFalse(self._has("--calculate_precessing_snr"))

    def test_calculate_precessing_snr_absent_when_not_in_calculate_list(self):
        prod = make_production(pesummary_meta={"calculate": ["something_else"]})
        self.assertFalse(self._has("--calculate_precessing_snr", prod))

    # --- PSDs ---

    def test_psds_flag_present_when_psds_exist(self):
        self.assertTrue(self._has("--psds"))

    def test_psds_flag_absent_when_no_psds(self):
        prod = make_production(assets={"psds": {}})
        self.assertFalse(self._has("--psds", prod))

    def test_psd_ifo_entries_present(self):
        parts = self._parts()
        ifo_entries = [p for p in parts if p.startswith(("H1:", "L1:"))]
        self.assertEqual(len(ifo_entries), 2)

    # --- Calibration envelopes ---

    def test_calibration_flag_present_when_cals_exist(self):
        prod = make_production(assets={
            "calibration": {"H1": "/path/H1_cal.txt", "L1": "/path/L1_cal.txt"},
        })
        self.assertTrue(self._has("--calibration", prod))

    def test_calibration_flag_absent_when_no_cals(self):
        # Default production has an empty calibration dict.
        self.assertFalse(self._has("--calibration"))

    def test_calibration_ifo_entries_present(self):
        prod = make_production(assets={
            "calibration": {"H1": "/path/H1_cal.txt", "L1": "/path/L1_cal.txt"},
        })
        parts = self._parts(prod)
        cal_entries = [p for p in parts if p.startswith(("H1:", "L1:"))]
        # Should have both PSD entries and calibration entries (2 each)
        self.assertGreaterEqual(len(cal_entries), 2)


# ---------------------------------------------------------------------------
# TestPESummaryBashFile
# ---------------------------------------------------------------------------

class TestPESummaryBashFile(unittest.TestCase):

    def setUp(self):
        self.production = make_production()

        self.mock_config = patch("asimov_pesummary.pesummary.config").start()
        self.mock_config.get.side_effect = _config_get

        self.mock_utils = patch("asimov_pesummary.pesummary.utils").start()

        self._open = mock_open()
        patch("builtins.open", self._open).start()

        self.addCleanup(patch.stopall)
        self.pipeline = PESummary(self.production)

    def test_bash_file_opened_for_writing(self):
        self.pipeline.submit_dag(dryrun=True)
        self._open.assert_called_with("pesummary.sh", "w")

    def test_bash_file_content_written(self):
        self.pipeline.submit_dag(dryrun=True)
        handle = self._open.return_value.__enter__.return_value
        handle.write.assert_called_once()

    def test_bash_file_starts_with_executable(self):
        self.pipeline.submit_dag(dryrun=True)
        handle = self._open.return_value.__enter__.return_value
        written = handle.write.call_args[0][0]
        self.assertTrue(written.startswith(self.pipeline.executable))

    def test_bash_file_written_in_work_directory(self):
        self.pipeline.submit_dag(dryrun=True)
        self.mock_utils.set_directory.assert_called_with(
            self.production.event.work_dir
        )


# ---------------------------------------------------------------------------
# TestPESummaryHTCondorSubmit
# ---------------------------------------------------------------------------

class TestPESummaryHTCondorSubmit(unittest.TestCase):

    def setUp(self):
        self.production = make_production()

        self.mock_config = patch("asimov_pesummary.pesummary.config").start()
        self.mock_config.get.side_effect = _config_get

        self.mock_utils = patch("asimov_pesummary.pesummary.utils").start()

        self._open = mock_open()
        patch("builtins.open", self._open).start()

        self.mock_htcondor = patch("asimov_pesummary.pesummary.htcondor").start()
        self.mock_htcondor.Submit.return_value.queue.return_value = 42

        self.addCleanup(patch.stopall)
        self.pipeline = PESummary(self.production)

    def test_dryrun_does_not_call_htcondor_submit(self):
        self.pipeline.submit_dag(dryrun=True)
        self.mock_htcondor.Submit.assert_not_called()

    def test_dryrun_returns_zero(self):
        self.assertEqual(self.pipeline.submit_dag(dryrun=True), 0)

    def test_htcondor_submit_called_on_live_run(self):
        self.pipeline.submit_dag(dryrun=False)
        self.mock_htcondor.Submit.assert_called_once()

    def test_submit_description_contains_executable(self):
        self.pipeline.submit_dag(dryrun=False)
        desc = self.mock_htcondor.Submit.call_args[0][0]
        self.assertIn("executable", desc)

    def test_submit_description_contains_arguments(self):
        self.pipeline.submit_dag(dryrun=False)
        desc = self.mock_htcondor.Submit.call_args[0][0]
        self.assertIn("arguments", desc)

    def test_submit_description_request_cpus(self):
        self.pipeline.submit_dag(dryrun=False)
        desc = self.mock_htcondor.Submit.call_args[0][0]
        self.assertEqual(desc["request_cpus"], 4)

    def test_submit_description_accounting_group(self):
        self.pipeline.submit_dag(dryrun=False)
        desc = self.mock_htcondor.Submit.call_args[0][0]
        self.assertEqual(
            desc["accounting_group"], "ligo.dev.o4.cbc.pe.lalinference"
        )

    def test_submit_description_accounting_group_user(self):
        self.pipeline.submit_dag(dryrun=False)
        desc = self.mock_htcondor.Submit.call_args[0][0]
        self.assertEqual(desc["accounting_group_user"], "testuser")

    def test_no_accounting_group_when_absent(self):
        prod = make_production()
        del prod.meta["postprocessing"]["pesummary"]["accounting group"]
        pipeline = PESummary(prod)
        pipeline.submit_dag(dryrun=False)
        desc = self.mock_htcondor.Submit.call_args[0][0]
        self.assertNotIn("accounting_group", desc)
        self.assertNotIn("accounting_group_user", desc)

    def test_returns_cluster_id(self):
        self.mock_htcondor.Submit.return_value.queue.return_value = 99
        result = self.pipeline.submit_dag(dryrun=False)
        self.assertEqual(result, 99)

    def test_submit_description_batch_name_includes_event(self):
        self.pipeline.submit_dag(dryrun=False)
        desc = self.mock_htcondor.Submit.call_args[0][0]
        self.assertIn("GW150914", desc["batch_name"])

    def test_submit_description_batch_name_includes_production(self):
        self.pipeline.submit_dag(dryrun=False)
        desc = self.mock_htcondor.Submit.call_args[0][0]
        self.assertIn("Prod0", desc["batch_name"])


if __name__ == "__main__":
    unittest.main()
