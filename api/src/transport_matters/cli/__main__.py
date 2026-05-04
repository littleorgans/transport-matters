"""Enable `python -m transport_matters.cli` as a dev convenience.

The installed `transport-matters` script (via `[project.scripts]`) uses
`transport_matters.cli:main` directly and does not go through this module.
"""

from transport_matters.cli import main

if __name__ == "__main__":
    main()
