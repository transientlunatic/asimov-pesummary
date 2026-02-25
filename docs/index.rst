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

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api
