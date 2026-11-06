"""Every test run gets its own STRATLAB_HOME, so tests never touch a real lab."""

import os
import tempfile

_HOME = tempfile.mkdtemp(prefix="stratlab-test-home-")
os.environ["STRATLAB_HOME"] = _HOME
