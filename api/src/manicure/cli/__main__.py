"""Enable `python -m manicure.cli` as a dev convenience.

The installed `manicure` script (via `[project.scripts]`) uses
`manicure.cli:main` directly and does not go through this module.
"""

from manicure.cli import main

if __name__ == "__main__":
    main()
