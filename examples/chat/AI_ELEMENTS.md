# Agent conversation patterns

PyJS supplies composable controls rather than an agent transport. Use
`MessageScroller` for the conversation, `Message` and `MessageContent` for
replies, and a muted `Bubble` for the user's messages. Assistant responses can
use `Markdown`; actions and timestamps belong in `MessageFooter`.

The controls correspond to the [AI Elements patterns][patterns]:

| Pattern | PyJS composition |
| --- | --- |
| Chat | `MessageScroller`, `MessageScrollerItem`, `PromptInput` |
| Message | `Message`, `MessageContent`, `MessageFooter`, `Bubble`, `Markdown` |
| Chain of thought | `Trace` containing public `Reasoning` summaries and steps |
| Checkpoint | `Checkpoint` with a caller-owned restore button |
| Confirmation | `Confirmation` with caller-owned approval buttons |
| Context | `Context` hover card and usage progress |
| File tree | `FileTree`, `FileTreeFolder`, `FileTreeFile` |
| Inline citation | `InlineCitation` hover card |
| Model selector | `ModelSelector` with `NativeSelectOption` |
| Plan | `Plan` with completion counts and step children |
| Prompt input | `PromptInput` around a textarea and action controls |
| Queue | `Queue`, `QueueItem` |
| Reasoning | `Reasoning` for a public summary and running/duration state |
| Sources | `Sources` with source links |
| Stack trace | `StackTrace` with expandable frames or `CodeBlock` |
| Subagent | `Subagent` with status and activity children |
| Suggestion | `Suggestion`, connected to the application's draft/send action |
| Task | `Task` with dynamically discovered steps |
| Terminal | `Terminal` for captured output; `pyjs.web.xterm` for a live PTY |
| Test results | `TestResults` with counts and suite children |
| Tool | `Tool` with arguments, output, and status |

Import the higher-level compositions from `pyjs.web.ui.ai`, diagnostic
primitives from `pyjs.web.ui.trace`, and Markdown from
`pyjs.web.ui.markdown`. The other primitives retain their focused UI modules.
Native disclosure controls support keyboard operation without JavaScript.
Only offer model selection, restoration, approval, or stop actions when the
connected agent actually supports them. Presentation never authorizes an action.

## Conversation behavior

Use `auto_scroll=True` on `MessageScroller`. It follows new content while the
reader is at the live edge, preserves their position when they scroll away,
and provides a jump-to-latest control. Prepend earlier messages using
`prepend_messages`; do not create a second scrolling conversation. Keep stable
message identities when combining saved history and streamed updates.

Pass a caller-owned textarea and buttons to `PromptInput`. The application
owns sending, cancellation, attachments, retries, and draft persistence. This
keeps transport failures from destroying a draft or sending a prompt twice.

## Markdown and code

`Markdown(text)` renders escaped text on the server and sanitized Markdown in
the browser. Call `set_text(text)` as a reply grows; unfinished code fences
remain readable. Browser builds need the managed npm dependencies:

```bash
pyjs npm sync your_app:main
```

The renderer uses pinned markdown-it and DOMPurify packages. It allows
formatting, code, lists, tables, and absolute HTTP(S) links. It excludes images, embedded
media, styles, scripts, forms, application-relative links, and automatic
external resource fetching. Links open in a separate tab without an opener.
Raw HTML and image descriptions remain literal text. Bare HTTP(S) URLs become
links; hostnames without a scheme remain text. Parsing limits nesting and token
creation before rendering, including tables that pad sparse rows. Replies
that reach either limit, or encounter a parser or sanitizer failure, remain
visible as complete plain text. Citations also accept only HTTP(S) URLs.
`CodeBlock` displays literal text; it does not execute or syntax-highlight code.

Do not pass private model reasoning to a `Reasoning` control. It is intended
for the public summaries an agent explicitly makes available to the user.

[patterns]: https://ui.shadcn.com/docs/ai-elements/base/message
