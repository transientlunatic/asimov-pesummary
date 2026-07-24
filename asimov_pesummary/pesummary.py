"""Defines the interface with generic analysis pipelines."""

import os

from asimov import utils  # NoQA
from asimov import config, logger, logging, LOGGER_LEVEL  # NoQA
from asimov.scheduler_utils import create_job_from_dict  # NoQA

import otter  # NoQA
from asimov.storage import Store  # NoQA
from asimov.pipeline import Pipeline, PipelineException, PipelineLogger  # NoQA


class PESummary(Pipeline):
    """
    A postprocessing pipeline add-in using PESummary.

    A production using this pipeline may be either a regular analysis
    (post-processing a single upstream production's samples) or an asimov
    ``SubjectAnalysis`` (combining several productions' samples into one set
    of summary pages). ``SubjectAnalysis`` productions marked ``refreshable:
    true`` are automatically resubmitted by asimov's monitor loop whenever
    their resolved source analyses change; when that happens here, only the
    newly-added analyses are passed to ``summarypages``, using its own
    ``--add_to_existing``/``--existing_webdir`` flags to append them to the
    already-published pages rather than recombining everything from
    scratch. If an analysis is ever removed from the combined set,
    ``summarypages`` cannot retract a label from an existing page in place,
    so a full rebuild is triggered instead.
    """

    executable = os.path.join(
        config.get("pipelines", "environment"), "bin", "summarypages"
    )
    name = "PESummary"

    def __init__(self, production, category=None):
        # Imported here rather than at module level: asimov's own
        # asimov/analysis.py imports asimov/pipelines/__init__.py (to build
        # known_pipelines) before it finishes defining SubjectAnalysis, and
        # pipelines/__init__.py loads every registered third-party pipeline
        # plugin -- including this one -- as part of that same import. A
        # module-level `from asimov.analysis import SubjectAnalysis` here
        # would hit asimov.analysis mid-initialisation and raise ImportError,
        # which asimov's plugin loader swallows silently, dropping this
        # pipeline (and this package's other entry points) from
        # known_pipelines with no visible error.
        from asimov.analysis import SubjectAnalysis

        self.production = production
        self.subject = production.event
        self.is_subject_analysis = isinstance(production, SubjectAnalysis)

        self.category = category if category else production.category
        self.logger = logger
        self.meta = self.production.meta["postprocessing"][self.name.lower()]

        # Required by the base Pipeline.scheduler property; not calling
        # super().__init__() here since this class sets up its attributes
        # differently (e.g. category fallback, plain module logger).
        self._scheduler = None

    def _webdir(self):
        return os.path.join(
            config.get("project", "root"),
            config.get("general", "webroot"),
            self.subject.name,
            self.production.name,
            "pesummary",
        )

    def results(self):
        """
        Fetch the results file from this post-processing step.

        A dictionary of results will be returned with the description
        of each results file as the key.  These may be nested if it
        makes sense for the output, for example skymaps.

        For example::

            {'metafile': '/home/asimov/working/samples/metafile.hd5',
             'skymaps': {'H1': '/another/file/path', ...}
            }

        Returns
        -------
        dict
           A dictionary of the results.
        """
        self.outputs = self._webdir()
        metafile = os.path.join(self.outputs, "samples", "posterior_samples.h5")

        return dict(metafile=metafile)

    def collect_assets(self):
        """
        Advertise this pipeline's combined metafile, in case a further
        downstream step ever needs to consume it.
        """
        return {"samples": self.results()["metafile"]}

    def build_dag(self, user=None, dryrun=False):
        """
        No-op: PESummary has no separate build step. All of the work
        happens in ``submit_dag``, but asimov's generic ``manage build
        submit`` CLI unconditionally calls ``build_dag`` on every pipeline
        before ``submit_dag``, so this must exist.
        """
        pass

    def _append_shared_options(self, command):
        """
        Append the ``postprocessing.pesummary`` meta-driven flags shared by
        both single-analysis and subject-analysis submissions.
        """
        if "cosmology" in self.meta:
            command += ["--cosmology", self.meta["cosmology"]]
        if "redshift" in self.meta:
            command += ["--redshift_method", self.meta["redshift"]]
        if "skymap samples" in self.meta:
            command += ["--nsamples_for_skymap", str(self.meta["skymap samples"])]

        if "evolve spins" in self.meta:
            if "forwards" in self.meta["evolve spins"]:
                command += ["--evolve_spins_fowards", "True"]
            if "backwards" in self.meta["evolve spins"]:
                command += ["--evolve_spins_backwards", "precession_averaged"]

        if "multiprocess" in self.meta:
            command += ["--multi_process", str(self.meta["multiprocess"])]

        if self.meta.get("regenerate"):
            posteriors = self.meta.get("regenerate posteriors")
            if not posteriors:
                raise PipelineException(
                    "postprocessing.pesummary.regenerate is set, but "
                    "'regenerate posteriors' is missing or empty."
                )
            command += ["--regenerate", " ".join(posteriors)]

        if "calculate" in self.meta:
            if "precessing snr" in self.meta["calculate"]:
                command += ["--calculate_precessing_snr"]

    def _submit(self, command, dryrun):
        """
        Write the job script, build the submit description, and submit (or,
        if ``dryrun``, just print what would happen). Shared by both the
        single-analysis and subject-analysis submission paths.
        """
        with utils.set_directory(self.subject.work_dir):
            with open("pesummary.sh", "w") as bash_file:
                bash_file.write(f"{self.executable} " + " ".join(command))

        self.logger.info(
            f"PE summary command: {self.executable} {' '.join(command)}",
        )

        if dryrun:
            print("PESUMMARY COMMAND")
            print("-----------------")
            print(" ".join(command))
        self.subject = self.production.event
        submit_description = {
            "executable": self.executable,
            "arguments": " ".join(command),
            "output": f"{self.subject.work_dir}/pesummary.out",
            "error": f"{self.subject.work_dir}/pesummary.err",
            "log": f"{self.subject.work_dir}/pesummary.log",
            "request_cpus": self.meta["multiprocess"],
            "getenv": "true",
            "batch_name": f"Summary Pages/{self.subject.name}/{self.production.name}",
            "request_memory": "8192MB",
            "should_transfer_files": "YES",
            "request_disk": "8192MB",
        }
        if "accounting group" in self.meta:
            submit_description["accounting_group_user"] = config.get("condor", "user")
            submit_description["accounting_group"] = self.meta["accounting group"]

        if dryrun:
            print("SUBMIT DESCRIPTION")
            print("------------------")
            print(submit_description)

        if not dryrun:
            job = create_job_from_dict(submit_description)
            cluster_id = self.scheduler.submit(job)
        else:
            cluster_id = 0

        return cluster_id

    def submit_dag(self, dryrun=False):
        """
        Run PESummary on the results of this job.
        """
        if self.is_subject_analysis:
            return self._submit_subject_analysis(dryrun=dryrun)
        return self._submit_single_analysis(dryrun=dryrun)

    def _submit_single_analysis(self, dryrun=False):
        configfile = self.production.event.repository.find_prods(
            self.production.name, self.category
        )[0]
        label = str(self.production.name)

        command = ["--webdir", self._webdir(), "--labels", label]

        command += ["--gw"]
        command += [
            "--approximant",
            self.production.meta["waveform"]["approximant"],
        ]

        command += [
            "--f_low",
            str(min(self.production.meta["waveform"]["minimum frequency"].values())),
            "--f_ref",
            str(self.production.meta["waveform"]["reference frequency"]),
        ]

        self._append_shared_options(command)

        if "nrsur" in self.production.meta["waveform"]["approximant"].lower():
            command += ["--NRSur_fits"]

        # Config file
        command += [
            "--config",
            os.path.join(
                self.production.event.repository.directory, self.category, configfile
            ),
        ]
        # Samples
        command += ["--samples"]
        command += [self.production._previous_assets().get("samples", {})]

        # PSDs
        psds = {
            ifo: os.path.abspath(psd)
            for ifo, psd in self.production._previous_assets().get("psds", {}).items()
        }
        if len(psds) > 0:
            command += ["--psds"]
            for key, value in psds.items():
                command += [f"{key}:{value}"]

        # Calibration envelopes
        cals = {
            ifo: os.path.abspath(psd)
            for ifo, psd in self.production._previous_assets()
            .get("calibration", {})
            .items()
        }
        if len(cals) > 0:
            command += ["--calibration"]
            for key, value in cals.items():
                command += [f"{key}:{value}"]

        return self._submit(command, dryrun)

    def _submit_subject_analysis(self, dryrun=False):
        """
        Run PESummary on the combined results of several source analyses.

        On the first run (or if an analysis has been removed from the
        resolved set since the last run), every resolved source analysis is
        submitted together. On a later refresh that only adds analyses to
        an already-published page, just the new analyses are submitted,
        using ``summarypages --add_to_existing`` to append them in place
        rather than recombining everything from scratch.
        """
        source_analyses = list(self.production.analyses)
        if not source_analyses:
            raise PipelineException(
                f"PESummary subject analysis {self.production.name} has no "
                "resolved source analyses."
            )

        current_names = sorted(analysis.name for analysis in source_analyses)
        previous_names = self.production.resolved_dependencies
        webdir = self._webdir()

        incremental = bool(
            previous_names is not None
            and set(previous_names) <= set(current_names)
            and set(current_names) - set(previous_names)
            and os.path.exists(os.path.join(webdir, "home.html"))
        )

        if incremental:
            analyses_to_submit = [
                analysis
                for analysis in source_analyses
                if analysis.name not in previous_names
            ]
        else:
            analyses_to_submit = source_analyses

        labels, approximants, f_lows, f_refs = [], [], [], []
        samples_list, config_list = [], []
        psds, cals = {}, {}

        for analysis in analyses_to_submit:
            assets = analysis.pipeline.collect_assets()
            samples = assets.get("samples")
            if not samples:
                self.logger.warning(
                    f"No samples available for {analysis.name}; skipping"
                )
                continue

            waveform = analysis.meta.get("waveform", {})
            if not {"approximant", "minimum frequency", "reference frequency"} <= (
                waveform.keys()
            ):
                raise PipelineException(
                    f"PESummary subject analysis {self.production.name}: "
                    f"{analysis.name} is missing waveform configuration "
                    "(approximant / minimum frequency / reference frequency) "
                    "required to combine it."
                )

            labels.append(analysis.name)
            samples_list.append(samples)
            approximants.append(waveform["approximant"])
            f_lows.append(str(min(waveform["minimum frequency"].values())))
            f_refs.append(str(waveform["reference frequency"]))

            configfile = analysis.event.repository.find_prods(
                analysis.name, analysis.category
            )[0]
            config_list.append(
                os.path.join(
                    analysis.event.repository.directory, analysis.category, configfile
                )
            )

            if not psds:
                psds = {
                    ifo: os.path.abspath(psd)
                    for ifo, psd in assets.get("psds", {}).items()
                }
            if not cals:
                cals = {
                    ifo: os.path.abspath(cal)
                    for ifo, cal in assets.get("calibration", {}).items()
                }

        if not labels:
            raise PipelineException(
                f"PESummary subject analysis {self.production.name} has no "
                "analyses with samples to add."
            )

        command = ["--webdir", webdir, "--labels"] + labels
        command += ["--gw"]
        command += ["--approximant"] + approximants
        command += ["--f_low"] + f_lows
        command += ["--f_ref"] + f_refs

        self._append_shared_options(command)

        if any("nrsur" in approximant.lower() for approximant in approximants):
            command += ["--NRSur_fits"]

        if incremental:
            command += ["--add_to_existing", "--existing_webdir", webdir]

        command += ["--config"] + config_list
        command += ["--samples"] + samples_list

        if psds:
            command += ["--psds"]
            for key, value in psds.items():
                command += [f"{key}:{value}"]

        if cals:
            command += ["--calibration"]
            for key, value in cals.items():
                command += [f"{key}:{value}"]

        # Set before submitting (matching the single-analysis convention of
        # treating "submitted" as "resolved"), so a later refresh's
        # staleness check compares against what this run is about to
        # process, and detect_completion_processing() knows which HDF5
        # groups to expect once it finishes. Use what was actually
        # submitted (previously-resolved names plus this round's labels),
        # not current_names -- an analysis skipped above (no samples yet)
        # must stay unresolved, or it would never be considered "new" on a
        # later refresh once its samples do appear, and
        # detect_completion_processing() would expect an HDF5 group for it
        # that will never exist.
        self.production.resolved_dependencies = sorted(
            set(previous_names or []) | set(labels)
        )

        return self._submit(command, dryrun)
