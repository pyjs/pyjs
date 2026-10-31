import pytest

from pyjs import js
from pyjs.tooling.npm import NpmImport, NpmPackage
from pyjs.web.dom import Element, window
from pyjs.web.domx import require_element, tag
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.ui.ai import (
    Checkpoint,
    Confirmation,
    Context,
    FileTree,
    FileTreeFile,
    FileTreeFolder,
    InlineCitation,
    ModelSelector,
    Plan,
    PromptInput,
    Queue,
    QueueItem,
    Reasoning,
    Sources,
    StackTrace,
    Subagent,
    Suggestion,
    Task,
    Terminal,
    TestResults,
    Tool,
)
from pyjs.web.ui.input_group import InputGroupTextarea
from pyjs.web.ui.markdown import Markdown
from pyjs.web.ui.native_select import NativeSelectOption
from pyjs.web.ui.trace import CodeBlock, Trace
from tests.web.ui.browser import mount

pytestmark = pytest.mark.pyjs_web


@js
def test_ai_compositions_mount_with_native_disclosure_and_explicit_actions():
    tree = FileTree(FileTreeFolder('src', FileTreeFile('app.py'), open=True))
    panel = Trace(
        Tool('Read', '{"path":"app.py"}', 'done', status='completed'),
        Reasoning('Public summary', running=True),
        Plan('Plan', Queue(QueueItem('Read', completed=True), QueueItem('Edit')), completed=1, total=2),
        Task('Discovering work', tree, status='running'),
        Confirmation('Run command?', Suggestion('Approve'), Suggestion('Deny'), description='Review first'),
        Checkpoint('Saved', Suggestion('Restore')),
        Context(500, 1000, tag('p', 'Half used')),
        InlineCitation('1', 'Source details', href='https://example.com'),
        Sources(tag('a', {'href': 'https://example.com'}, 'Source')),
        ModelSelector(NativeSelectOption('fast', 'Fast')),
        StackTrace('Failure', CodeBlock('file.py:1')),
        Subagent('Worker', 'Summary', status='running'),
        Terminal('pytest', 'ok', status='completed'),
        TestResults('Suite details', passed=2, failed=1),
        PromptInput(InputGroupTextarea('Message'), Suggestion('Send')),
    )
    mount(panel)
    assert panel.querySelectorAll('details[open]').length >= 5
    assert panel.querySelector('[data-slot=confirmation]') is not None
    assert require_element(panel, 'progress').getAttribute('value') == '500'
    assert require_element(panel, 'select').getAttribute('aria-label') == 'Model'
    assert panel.querySelectorAll('button[type=button]').length >= 5
    assert 'Half used' in panel.textContent


@js
def test_markdown_updates_fences_lists_and_blocks_active_content():
    message = Markdown('## Result\n\n- **Ready**\n- Next\n\n```python\nprint(1)')
    mount(message)
    assert require_element(message, 'h2').textContent == 'Result'
    assert message.querySelectorAll('li').length == 2
    assert require_element(message, 'pre code').textContent.strip() == 'print(1)'
    message.set_text('Done\n\n<script>alert(1)</script><img src="https://example.com/track">\n\n'
                     '[bad](javascript:alert(1)) [local](/api/action) [safe](https://example.com)'
                     '<input autofocus><iframe src="https://example.com"></iframe>')
    assert message.querySelector('h2') is None
    assert message.body.querySelector('script,img,input,iframe,style') is None
    assert message.querySelectorAll('a[href]').length == 1
    assert require_element(message, 'a[href]').getAttribute('rel') == 'noopener noreferrer'
    assert require_element(message, 'a[href]').getAttribute('target') == '_blank'


@js
class Submissions:
    def __init__(self):
        self.count = 0

    def handleEvent(self, event: Event):
        event.preventDefault()
        self.count += 1


@js
def consume_enter(event: Event):
    event.preventDefault()


@js
def test_prompt_input_enter_preserves_shift_and_composition():
    textarea = InputGroupTextarea('Message')
    form = tag('form', PromptInput(textarea, Suggestion('Send')))
    submissions = Submissions()
    form.addEventListener('submit', submissions)
    mount(form)
    textarea.dispatchEvent(KeyboardEvent('keydown', key='Enter', shiftKey=True, bubbles=True, cancelable=True))
    textarea.dispatchEvent(KeyboardEvent('keydown', key='Enter', isComposing=True, bubbles=True, cancelable=True))
    assert submissions.count == 0
    textarea.addEventListener('keydown', consume_enter)
    textarea.dispatchEvent(KeyboardEvent('keydown', key='Enter', bubbles=True, cancelable=True))
    assert submissions.count == 0
    textarea.removeEventListener('keydown', consume_enter)
    textarea.dispatchEvent(KeyboardEvent('keydown', key='Enter', bubbles=True, cancelable=True))
    assert submissions.count == 1


@js
def test_markdown_pre_mount_updates_and_remount_keep_original_source():
    message = Markdown('Old')
    message.set_text('**Latest** and `<b>`')
    mount(message)
    assert require_element(message, 'strong').textContent == 'Latest'
    assert require_element(message, 'code').textContent == '<b>'
    message.remove()
    mount(message)
    assert require_element(message, 'strong').textContent == 'Latest'
    assert require_element(message, 'code').textContent == '<b>'


__pyjs_npm_imports__ = (NpmImport(NpmPackage('dompurify', '3.4.17'), '$purify'),)


@js.inline("""(() => {{
    const original = $purify.default.sanitize;
    $purify.default.sanitize = () => {{ throw new Error('sanitizer unavailable'); }};
    try {{ {message}.set_text('<img src=x onerror=alert(1)>'); }}
    finally {{ $purify.default.sanitize = original; }}
}})()""")
def render_with_failed_sanitizer(message: Markdown) -> None:
    raise NotImplementedError


@js
def test_markdown_pathological_input_and_renderer_failure_recover():
    message = Markdown('Before')
    mount(message)
    message.set_text('> ' * 2000 + 'deep quote')
    assert 'deep quote' in message.body.textContent
    assert message.querySelectorAll('blockquote').length <= 20
    message.set_text('*a ' * 4000)
    assert len(message.body.textContent) >= 8000
    render_with_failed_sanitizer(message)
    assert message.body.textContent == '<img src=x onerror=alert(1)>'
    assert message.body.querySelector('img') is None
    message.set_text('**Recovered**')
    assert require_element(message, 'strong').textContent == 'Recovered'
    assert message.body.className == ''


@js.inline('{element}.click()')
def activate(element: Element) -> None:
    raise NotImplementedError


@js
def test_context_and_untrusted_citations_are_buttons():
    panel = tag('div', Context(1, 2),
                InlineCitation('Bad', href=' javascript:alert(1)'),
                InlineCitation('Local', href='/api/action'),
                InlineCitation('Source', href=' https://example.com '))
    mount(panel)
    assert panel.querySelectorAll('button[type=button]').length == 3
    assert panel.querySelectorAll('a[href]').length == 1
    assert require_element(panel, 'a').getAttribute('href') == 'https://example.com'
    original_url = window.location.href
    activate(require_element(panel, 'button'))
    assert window.location.href == original_url
    assert require_element(panel, '[data-slot=hover-card]').getAttribute('data-state') == 'open'


@js
def test_prompt_input_honors_disabled_submitter_repeat_and_ime_keycode():
    textarea = InputGroupTextarea('Message')
    send = tag('button', {'type': 'submit', 'disabled': ''}, 'Send')
    fieldset = tag('fieldset', send)
    form = tag('form', PromptInput(textarea, fieldset))
    submissions = Submissions()
    form.addEventListener('submit', submissions)
    mount(form)
    textarea.dispatchEvent(KeyboardEvent('keydown', key='Enter', bubbles=True, cancelable=True))
    assert submissions.count == 0
    send.removeAttribute('disabled')
    fieldset.setAttribute('disabled', '')
    textarea.dispatchEvent(KeyboardEvent('keydown', key='Enter', bubbles=True, cancelable=True))
    assert submissions.count == 0
    fieldset.removeAttribute('disabled')
    textarea.dispatchEvent(KeyboardEvent('keydown', key='Enter', repeat=True, bubbles=True, cancelable=True))
    textarea.dispatchEvent(KeyboardEvent('keydown', key='Enter', keyCode=229, bubbles=True, cancelable=True))
    assert submissions.count == 0
    textarea.dispatchEvent(KeyboardEvent('keydown', key='Enter', bubbles=True, cancelable=True))
    assert submissions.count == 1
