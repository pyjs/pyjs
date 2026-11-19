from pyjs import int8
from pyjs.android import (
    Activity,
    Bundle,
    Button,
    Intent,
    LinearLayout,
    OnClickListener,
    TextView,
    Uri,
    View,
    uri_clip_data,
)
from pyjs.android.files import FileProvider, uri_for_file
from pyjs.java import JVMArray, i32
from pyjs.java.errors import IllegalArgumentException, SecurityException
from pyjs.java.io import (
    ByteArrayOutputStream,
    File,
    FileOutputStream,
    IOException,
    OutputStreamWriter,
)


def content() -> str:
    return "Shared paragraph 雪 😀\n" * 70_000


class SharingProvider(FileProvider):
    pass


class SendFile(OnClickListener):
    def __init__(self, activity: Activity, file: File, grant: bool):
        self.activity = activity
        self.file = file
        self.grant = grant

    def onClick(self, view: View) -> None:
        uri = uri_for_file(self.activity, "org.pyjs.share.sender.files", self.file)
        intent = (Intent().set_action(Intent.ACTION_SEND).set_type("text/plain")
                  .set_class_name("org.pyjs.share.receiver",
                                  "org.pyjs.share.receiver.PyjsAndroid$ReceiveActivity")
                  .put_parcelable_extra(Intent.EXTRA_STREAM, uri))
        intent.set_clip_data(uri_clip_data(self.activity.get_content_resolver(), "Note", uri))
        if self.grant:
            intent.add_flags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        self.activity.start_activity(intent)


class SendActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        directory = File(self.get_cache_dir().getPath() + "/outgoing")
        if not directory.exists():
            assert directory.mkdirs()
        file = File(directory.getPath() + "/note.txt")
        writer = OutputStreamWriter(FileOutputStream(file), "UTF-8")
        try:
            writer.write(content())
        finally:
            writer.close()
        rejected = False
        try:
            uri_for_file(self, "org.pyjs.share.sender.files",
                         File(directory.getPath() + "/../private.txt"))
        except IllegalArgumentException:
            rejected = True
        assert rejected, "Provider accepted a path outside its sharing root"
        root = LinearLayout(self)
        root.setOrientation(LinearLayout.VERTICAL)
        for grant in [False, True]:
            button = Button(self)
            button.setText("Send with grant" if grant else "Send without grant")
            button.setOnClickListener(SendFile(self, file, grant))
            root.addView(button)
        self.setContentView(root)


class ReceiveActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        intent = self.get_intent()
        assert intent is not None
        uri = intent.get_parcelable_extra(Intent.EXTRA_STREAM)
        assert isinstance(uri, Uri)
        status = TextView(self)
        self.setContentView(status)
        try:
            stream = self.get_content_resolver().open_input_stream(uri)
        except SecurityException:
            status.setText("File unavailable without a read grant")
            return
        except IOException:
            # On API 30+, absence of a URI grant can hide the provider itself.
            status.setText("File unavailable without a read grant")
            return
        assert stream is not None
        data = ByteArrayOutputStream()
        buffer = JVMArray[int8](8192)
        try:
            count = stream.read(buffer)
            while count != -1:
                data.write(buffer, i32(0), count)
                count = stream.read(buffer)
        finally:
            stream.close()
        assert data.toString("UTF-8") == content(), "Shared file was changed or truncated"
        rejected = False
        try:
            output = self.get_content_resolver().open_output_stream(uri, "wa")
            if output is not None:
                output.close()
        except SecurityException:
            rejected = True
        assert rejected, "Read-only URI grant allowed writing"
        status.setText("Complete Unicode file received; writes denied")


def main() -> int:
    SharingProvider()
    SendActivity().onCreate(None)
    ReceiveActivity().onCreate(None)
    return 0
