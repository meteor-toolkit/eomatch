###############
Developer Guide
###############

Setting up the development environment
######################################

Clone the repository and navigate into it:

.. code-block:: bash

   git clone git@gitlab.npl.co.uk:eco/tools/eomatch.git
   cd ./eomatch

Create a new branch for your contributions:

.. code-block:: bash

   git checkout -b new-branch-name
   git push --set-upstream origin new-branch-name

Install the package with the developer optional dependencies:

.. code-block:: bash

   pip install -e .[dev]

Install the pre-commit hooks:

.. code-block:: bash

   pre-commit install

Before you push
###############

Code formatting
---------------

eomatch uses `black`_ for code formatting (enforced via a pre-commit hook).
To format your code manually:

.. code-block:: bash

   black .

Type checking
-------------

eomatch uses `mypy`_ for static type analysis (``ignore_missing_imports = True``).
Run it before pushing:

.. code-block:: bash

   mypy ./eomatch

Linting
-------

eomatch uses `flake8`_ with a maximum line length of 120:

.. code-block:: bash

   flake8 --max-line-length=120 ./eomatch

Running tests
-------------

Tests are stored in ``eomatch/tests/``, ``eomatch/finder/tests/``, and
``eomatch/enrich/tests/``, and use
`pytest`_.  Run the full suite with:

.. code-block:: bash

   pytest

To run a single test file:

.. code-block:: bash

   pytest eomatch/tests/test_domain.py

To run a single test:

.. code-block:: bash

   pytest eomatch/tests/test_domain.py::TestMatchup::test_collocation_region

Compiling documentation
-----------------------

eomatch uses `sphinx`_ to build its documentation.  After editing the
``docs/`` source files, verify that everything compiles correctly:

.. code-block:: bash

   sphinx-build docs docs/_build -b html

Then open ``docs/_build/index.html`` in a browser to review the output.

When adding a new public class or function:

- List it in ``docs/content/user/api.rst`` (or ``backend_documentation.rst``
  for internal utilities).
- Add a usage example in the relevant user-guide page.
- Make sure every public method has a Sphinx-style docstring with ``:param:``
  and ``:return:`` entries.

.. _black: https://black.readthedocs.io
.. _mypy: https://mypy.readthedocs.io
.. _flake8: https://flake8.pycqa.org
.. _pytest: https://docs.pytest.org
.. _sphinx: https://www.sphinx-doc.org
