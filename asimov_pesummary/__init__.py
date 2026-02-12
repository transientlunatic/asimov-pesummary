"""PESummary Pipeline integration for Asimov."""

from .pesummary import PESummary

__all__ = ["PESummary"]

try:
    from importlib.metadata import version, PackageNotFoundError
except ImportError:
    from importlib_metadata import version, PackageNotFoundError

try:
    __version__ = version(__name__)
except PackageNotFoundError:
    __version__ = "unknown"
