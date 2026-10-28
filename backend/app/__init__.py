"""JustForms backend."""

import os

# The release the image was built for (Dockerfile ARG JUSTFORMS_RELEASE, set by release builds).
__version__ = os.environ.get("JUSTFORMS_RELEASE", "").strip() or "0.0.0-dev"
