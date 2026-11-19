"""AndroidX content URIs for files within configured sharing directories."""
from pyjs import jvm
from pyjs.android import Context, Uri
from pyjs.java.io import File


@jvm.native("androidx/core/content/FileProvider")
class FileProvider:
    def __init__(self) -> None: ...


@jvm.native("androidx/core/content/FileProvider", name="getUriForFile")
def uri_for_file(context: Context, authority: str, file: File) -> Uri:
    """Resolve a file through a manifest-declared FileProvider.

    The provider must have a restricted paths resource. This does not grant
    access: callers set URI permission flags and ClipData on the outgoing
    Intent. Files outside configured roots are rejected by AndroidX.
    """
    ...
