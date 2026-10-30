from typing import cast

import pytest

from pyjs import js
from pyjs.web.dom import document
from pyjs.web.html import HTMLTextAreaElement

pytestmark = pytest.mark.pyjs_web


@js
def test_document_edit_commands_preserve_native_textarea_history():
    editor = cast(HTMLTextAreaElement, document.createElement('textarea'))
    document.body.appendChild(editor)
    try:
        editor.value = 'alpha gr'
        editor.focus()
        editor.setSelectionRange(6, 8)
        assert document.execCommand('insertText', False, 'greeting')
        assert editor.value == 'alpha greeting'
        assert document.execCommand('undo')
        assert editor.value == 'alpha gr'
        assert document.execCommand('redo')
        assert editor.value == 'alpha greeting'
        assert not document.execCommand('nonexistentEditingCommand')
    finally:
        editor.remove()
