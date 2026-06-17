"""MA-XRF edit module."""

from .compile_tab import MaxrfCompileTab
from .false_colour_tab import MaxrfFalseColourTab
from .map_setup_tab import MapSetupTab
from .ui import MaxrfEditTab

__all__ = ["MapSetupTab", "MaxrfFalseColourTab", "MaxrfEditTab", "MaxrfCompileTab"]
