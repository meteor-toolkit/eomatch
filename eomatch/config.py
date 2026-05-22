from processor_tools.config import ConfigInit
import os.path

config_init = ConfigInit(
    package_name="eomatch",
    configs={
        "user_config.yaml": os.path.join(os.path.dirname(__file__), "etc", "user_config.yaml"),
    },
    config_directory=None,  # default is ~/.config/eomatch, but can be set to a different directory if desired (e.g. for testing)
    config_directory_file_path=None,  # default is ~/.config/eomatch/eomatch_config_directory.txt, but can be set to a different file if desired (e.g. for testing)
)


def init_cli():
    config_init.cli()
