"""Studio's startup entry point: python3 -I run.py [arguments]

Why this file is needed: when started with -I (isolated mode), Python does not add packages from the current directory or the user directory,
which is exactly what we want (only the pinned dependencies in deps/), but then `-m studio` cannot find the package either.
So here deps/ and this directory are explicitly put first, and then studio is entered.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "deps"), HERE]

from studio.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
