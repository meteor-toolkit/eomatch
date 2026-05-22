"""eomatch - Match up dataset generation for Earth Observation satellites"""

__author__ = "Sam Hunt <sam.hunt@npl.co.uk>"
__all__ = []

from importlib.metadata import version, PackageNotFoundError

import os

THIS_DIRECTORY = os.path.dirname(__file__)

try:
    __version__ = version("eomatch")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

from eomatch.config import config_init

if not config_init.is_initialised():
    print(f"Initialising config at {config_init.get_config_directory()}...")
    config_init.init()

from eomatch.context import EOMatchContext
from eomatch.domain import Matchup, MatchupSet, MatchupEvent, MatchupEventSet
from eomatch.mu_stac import MatchupCatalogue
from eomatch.preview import preview_matchup
