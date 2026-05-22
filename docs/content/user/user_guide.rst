###########
User Guide
###########

Installing eomatch
#####################

**Local installation**:

Clone this package:

.. code-block:: bash

   git clone git@gitlab.npl.co.uk:eco/tools/eomatch.git

Navigate to the cloned directory and install it:

.. code-block:: bash

   cd ./eomatch
   pip install -e .

EOMatch depends on several internal NPL packages (``scrappi``, ``orbitx``,
``eoio``, ``processor_tools``) that are available from the NPL GitLab package
registry. Ensure you have a valid GitLab personal access token and that your
``pip`` configuration points to the NPL registry before installing.

Setting up the configuration
############################

EOMatch reads its runtime parameters (platforms, time ranges, spatial
thresholds, catalogue paths, …) from a YAML config file.  A set of defaults is
bundled with the package.

On first import, eomatch initialises a user config directory (printed to the
console).  You can copy the bundled defaults there and edit them to suit your
use-case:

.. code-block:: bash

   python -c "import eomatch"          # triggers first-time init

You can also pass a path to a config file directly when constructing a
`EOMatchContext`:

.. code-block:: python

   from eomatch import EOMatchContext

   ctx = EOMatchContext("/path/to/my_config.yaml")

Any keys in your file are merged on top of the package defaults, so you only
need to supply the values you want to override.

.. toctree::
   :hidden:

   Configuration <configuration>
   Finding matchups <finding_matchups>
   Building collocated datasets <datasets>
   STAC catalogue <catalogue>
   Enriching matchup metadata <enrichment>
   Central catalogue <central_catalogue>
   Registering analysis results <analysis_assets>
   Preview images <previews>
   Guide for external collaborators <external_guide>
