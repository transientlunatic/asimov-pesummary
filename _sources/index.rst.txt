asimov-pesummary
================

``asimov-pesummary`` is a plugin for `Asimov <https://asimov.docs.ligo.org/asimov/>`_ 0.7+
that integrates `PESummary <https://lscsoft.docs.ligo.org/pesummary/>`_ as a post-processing
pipeline.  Once installed, the plugin is discovered automatically via Asimov's entry-point
registry — no extra configuration is required.

**What it does**

* Builds a ``summarypages`` command from the per-production Asimov meta-data
  (waveform, data-quality, calibration, PSDs, …).
* Submits the job to an HTCondor scheduler.
* Returns the path to the resulting PESummary HDF5 metafile so that Asimov can
  track it as a downstream asset.

Installation
------------

From PyPI::

    pip install asimov-pesummary

From source::

    git clone https://git.ligo.org/asimov/asimov-pesummary.git
    cd asimov-pesummary
    pip install -e ".[docs,test]"

Configuration
-------------

Add a ``postprocessing.pesummary`` block to the relevant production in your
Asimov ledger.  All keys are optional unless noted.

.. code-block:: yaml

   postprocessing:
     pesummary:
       accounting group: ligo.dev.o4.cbc.pe.lalinference  # required on LVK clusters
       multiprocess: 4          # number of CPUs (required)
       cosmology: Planck15_lal
       redshift: exact
       skymap samples: 2000
       evolve spins: forwards   # "forwards", "backwards", or "forwards backwards"
       calculate:
         - precessing snr
       regenerate: true
       regenerate posteriors:
         - redshift
         - mass_1_source
         - mass_2_source

Subject analyses
-----------------

``PESummary`` can also be attached to an Asimov ``SubjectAnalysis`` instead
of a single production, in which case it combines several productions'
results into one set of summary pages rather than post-processing just one.
This uses the same ``postprocessing.pesummary`` configuration described
above (inherited from the event/project the same way it is for a regular
production), plus the ``analyses``/``refreshable`` keys, which are generic
Asimov ``SubjectAnalysis`` behaviour rather than anything specific to this
plugin:

.. code-block:: yaml

   kind: analysis
   name: CombinedPESummary
   pipeline: pesummary
   analyses:
     - pipeline: bilby   # combine every bilby production on this event
   refreshable: true
   status: ready

Marking the analysis ``refreshable: true`` means Asimov's own monitor loop
(``asimov monitor``) automatically resubmits it whenever the set of
resolved source analyses changes — for example because a new production
finished, or because a review decision changed which productions match the
``analyses`` selector. See Asimov's own documentation for the
``analyses``/``refreshable`` selector syntax and staleness detection; this
plugin only implements what happens when such a resubmission occurs.

The **first** time a ``SubjectAnalysis`` PESummary production runs (or if a
previously-included analysis has dropped out of the resolved set, for
example after a review decision), it submits a single ``summarypages`` run
combining every currently resolved source analysis.

On a **later refresh that only adds** newly-resolved analyses to an
already-published page, only the new analyses are submitted, using
``summarypages``'s own ``--add_to_existing``/``--existing_webdir`` flags to
append them to the existing pages in place, rather than reprocessing every
source analysis again from scratch.

.. note::

   ``summarypages`` has no way to retract a label from an already-published
   page. If a previously-included analysis is later *removed* from the
   resolved set, the next refresh falls back to a full rebuild (recombining
   every currently resolved analysis) instead of an incremental update.

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api
