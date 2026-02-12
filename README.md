# asimov-pesummary

PESummary pipeline integration for [Asimov](https://git.ligo.org/asimov/asimov).

This package provides a plugin for Asimov 0.7+ that enables integration with PESummary for post-processing and visualization of parameter estimation results.

## Features

- 🔌 **Plugin Architecture**: Seamlessly integrates with Asimov via entry points
- 📊 **Result Summarization**: Automatic generation of summary pages from PE results
- 🎨 **Visualization**: Automated plot generation and result presentation
- 📈 **Multi-analysis Support**: Combine results from multiple analyses
- 🚀 **HTCondor Integration**: Automated job submission for large-scale post-processing
- 🧪 **Well Tested**: Comprehensive unit test coverage

## Installation

### Via Asimov (Recommended)

If you have asimov 0.7+, you can install gravitational wave pipelines including PESummary with:

```bash
pip install asimov[gw]
```

This will automatically install asimov-pesummary and other GW analysis plugins.

### From PyPI (when released)

```bash
pip install asimov-pesummary
```

### From Source

```bash
git clone https://git.ligo.org/asimov/asimov-pesummary.git
cd asimov-pesummary
pip install -e .
```

### For Development

```bash
pip install -e ".[docs,test]"
```

## Quick Start

Once installed, the PESummary pipeline is automatically available in Asimov for post-processing parameter estimation results.

## Requirements

- Python >= 3.9
- asimov >= 0.7.0
- pesummary

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please see CONTRIBUTING.md for guidelines.
