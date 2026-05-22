"""eomatch.context - EOMatchContext for eomatch configuration"""

from typing import Optional, Union, List
from processor_tools import Context
from eomatch.config import config_init

__all__ = ["EOMatchContext"]


class EOMatchContext(Context):
    default_config: Optional[Union[str, List[str]]] = None

    def __init__(self, context: Optional[Union[dict, str]] = None):
        self.default_config = []
        super(EOMatchContext, self).__init__(context, config_init=config_init)
