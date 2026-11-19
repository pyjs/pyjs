from pyjs.testing.helpers import assert_transpile
from pyjs.web.sharing import ShareData


def test_share_data_preserves_omitted_and_empty_fields():
    assert vars(ShareData()) == {}
    assert vars(ShareData(text="", files=[])) == {"files": [], "text": ""}
    assert vars(ShareData(title="Title", text="Body", url="https://example.com/")) == {
        "title": "Title", "text": "Body", "url": "https://example.com/",
    }


def test_share_calls_compile_to_native_navigator_and_dictionary():
    assert_transpile(
        '''
        from pyjs.web.sharing import ShareData, navigator

        async def main():
            data = ShareData(title="Title", text="Body")
            if hasattr(navigator, "share") and navigator.canShare(data):
                await navigator.share(data)
        ''',
        '''
        export async function main() {
            var data = {title: 'Title', text: 'Body'};
            if ('share' in navigator && navigator.canShare(data)) {
                await navigator.share(data);
            }
        }
        ''',
    )
