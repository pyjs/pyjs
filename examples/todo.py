from pyjs import js, js_str
from pyjs.dom import (
    HTMLElement, TagNameSetterMetaclass,
    Event, CustomEvent, KeyboardEvent,
    customElements, HTMLInputElement,
    document
)


@js
def tag(name_or_element: str|HTMLElement, *args: str|dict[str,str]|HTMLElement) -> HTMLElement:
    if isinstance(name_or_element, str):
        e = document.createElement(name_or_element)
    else:
        e = name_or_element
    assert isinstance(e, HTMLElement)
    for arg in args:
        if isinstance(arg, str):
            e.append(arg)
        elif isinstance(arg, HTMLElement):
            e.append(arg)
        elif isinstance(arg, dict):
            attrs: dict[str,str] = arg
            for attr, value in attrs.items():
                e.setAttribute(attr, value)
        else:
            raise TypeError
    return e


@js
def tw(classes: str) -> dict[str,str]:
    return {"class": classes}


#@tag.source
#def tag():
#    return """
#    const e = document.createElement(name);
#    for (const [attr, value] of Object.entries(attrs)) {
#        e.setAttribute(attr, value)
#    }
#    if (children) {
#        e.append(...children);
#    }
#    return e;
#    """


@js
class FilterEvent(CustomEvent):
    eventName = js_str("filter-event")
    def __init__(self, filter_name: str):
        super().__init__(FilterEvent.eventName, detail=filter_name, bubbles=True, cancelable=True)


@js
class ToggleEvent(CustomEvent):
    eventName = js_str("toggle-event")
    def __init__(self, task: HTMLElement):
        super().__init__(ToggleEvent.eventName, detail=task, bubbles=True, cancelable=True)


@js
class ClearCompletedEvent(Event):
    eventName = js_str("clear-completed-event")
    def __init__(self):
        super().__init__(ClearCompletedEvent.eventName, bubbles=True, cancelable=True)


@js
class CreateTaskEvent(CustomEvent):
    eventName = js_str("create-task-event")
    def __init__(self, task: str):
        super().__init__(CreateTaskEvent.eventName, detail=task, bubbles=True, cancelable=True)


@js
class DeleteTaskEvent(CustomEvent):
    eventName = js_str("delete-task-event")
    def __init__(self, task: HTMLElement):
        super().__init__(DeleteTaskEvent.eventName, detail=task, bubbles=True, cancelable=True)


@js
class CustomElement(HTMLElement, metaclass=TagNameSetterMetaclass):

    def __init__(self):
        super().__init__()
        self._initialized = False

    @js(include=True)
    def connectedCallback(self):
        if self._initialized: return;
        self.initialize()
        self._initialized = True

    @js(include=True)
    def initialize(self):
        pass

    @js(include=True)
    @classmethod
    def create(cls, *args, **kwargs):
        pass


@js
class TodoItem(CustomElement):

    @js(include=True)
    @classmethod
    def create(cls, task: str):
        return tag(cls(),
            tag("li", tw("todo-item"),
                tag("div", tw("display-todo"),
                    tag("label", tw("toggle-todo-label visually-hidden"), {"for": "toggle-todo"}, "Toggle Todo"),
                    tag("input", tw("toggle-todo-input"), {"id": "toggle-todo", "type": "checkbox"}),
                    tag("span", tw("todo-item-text truncate-singleline"), {"tabindex": "0"}, task),
                    tag("button", tw("remove-todo-button"), {"title": "Remove Todo"}),
                ),
                tag("div", tw("edit-todo-container"),
                    tag("label", tw("edit-todo-label visually-hidden"), {"for": "edit-todo"}, "Edit todo"),
                    tag("input", tw("edit-todo-input"), {"id": "edit-todo"}),
                ),
            )
        )

    @js(include=True)
    def initialize(self):
        self.item = self.children[0]
        self.toggleButton: HTMLInputElement = self.querySelector(".toggle-todo-input")
        self.toggleButton.addEventListener(
            "click", lambda e: self.dispatchEvent(ToggleEvent(self))
        )
        self.todoText = self.querySelector(".todo-item-text")
        self.todoText.addEventListener("click", self.start_editing)
        self.removeButton = self.querySelector(".remove-todo-button")
        self.removeButton.addEventListener(
            "click", lambda e: self.dispatchEvent(DeleteTaskEvent(self))
        )
        self.editInput: HTMLInputElement = self.querySelector(".edit-todo-input")
        self.editInput.addEventListener("blur", self.stop_editing)
        self.editInput.addEventListener("keydown", self.keydown)

    def start_editing(self, e: Event):
        self.item.classList.add("editing")
        self.editInput.value = self.todoText.textContent.strip()
        self.editInput.focus()

    def stop_editing(self, e: Event):
        self.item.classList.remove("editing")

    def cancel_editing(self, e: Event):
        self.editInput.blur()

    def keydown(self, e: KeyboardEvent):
        if e.key == 'Enter':
            e.preventDefault()
            self.todoText.textContent = self.editInput.value
            self.cancel_editing(e)


@js
class TodoTopbar(CustomElement):

    @js(include=True)
    @classmethod
    def create(cls, count: int):
        return tag(cls(),
            tag("header", tw("topbar"),
                tag("div", tw("new-todo-display"),
                    tag("label", tw("visually-hidden"), {"for":"new-todo"}, "Enter a new todo."),
                    tag("input", tw("new-todo-input"), {"id":"new-todo", "placeholder":"What needs to be done?", "autofocus":True}),
                ),
                tag("div", tw("toggle-all-container"), {"style":"display:" + ("block" if count > 0 else "none")},
                    tag("input", tw("toggle-all-input"), {"id":"toggle-all", "type":"checkbox"}),
                    tag("label", tw("toggle-all-label"), {"for":"toggle-all"}, "Mark all todos as complete."),
                )
            )
        )

    @js(include=True)
    def initialize(self):
        self.todoInput: HTMLInputElement = self.querySelector("#new-todo")
        self.todoInput.addEventListener('keydown', self.keydown)
        self.toggleButton: HTMLInputElement = self.querySelector("#toggle-all")
        self.toggleButton.addEventListener(
            "click", lambda e: self.dispatchEvent(ToggleEvent(self.toggleButton.checked))
        )
        self.toggleContainer: HTMLElement = self.querySelector(".toggle-all-container")

    def keydown(self, event: KeyboardEvent):
        if event.key == 'Enter':
            event.preventDefault()
            if not event.target.value:
                return
            self.dispatchEvent(CreateTaskEvent(event.target.value))
            event.target.value = ""

    def update(self, count: int):
        self.toggleContainer.style.display = "block" if count > 0 else "none"


@js
class TodoBottombar(CustomElement):

    @js(include=True)
    @classmethod
    def create(cls, count: int):
        return tag(cls(),
            tag("footer", tw("bottombar"), {"style":"display:" + ("block" if count > 0 else "none")},
                tag("div", tw("todo-status"), "1 item left" if count == 1 else f"{count} items left"),
                tag("ul", tw("filter-list"),
                    tag("li", tw("filter-item"),
                        tag("a", tw("filter-link selected"), {"id":"filter-link-all", "href":"#/", "data-route":"all"}, "All"),
                    ),
                    tag("li", tw("filter-item"),
                        tag("a", tw("filter-link"), {"id":"filter-link-active", "href":"#/active", "data-route":"active"}, "Active"),
                    ),
                    tag("li", tw("filter-item"),
                        tag("a", tw("filter-link"), {"id":"filter-link-completed", "href": "#/completed", "data-route":"completed"}, "Completed"),
                    ),
                ),
                tag("button", tw("clear-completed-button"), {"id":"clear-completed"}, "Clear completed"),
            )
        )

    @js(include=True)
    def initialize(self):
        self.element: HTMLElement = self.children[0]
        self.allButton = self.querySelector("#filter-link-all")
        self.allButton.addEventListener("click", self.change_filter)
        self.activeButton = self.querySelector("#filter-link-active")
        self.activeButton.addEventListener("click", self.change_filter)
        self.completedButton = self.querySelector("#filter-link-completed")
        self.completedButton.addEventListener("click", self.change_filter)
        self.clearCompletedButton = self.querySelector(".clear-completed-button")
        self.clearCompletedButton.addEventListener(
            "click", lambda e: self.dispatchEvent(ClearCompletedEvent())
        )
        self.todoCount = self.querySelector(".todo-status")
        self.filterLinks = self.querySelectorAll(".filter-link")

    def update(self, count: int, active: int):
        self.element.style.display = "block" if count > 0 else "none"
        self.todoCount.textContent = "1 item left" if active == 1 else f"{active} items left"

    def change_filter(self, e: CustomEvent):
        for btn in [self.allButton, self.activeButton, self.completedButton]:
            btn.classList.remove("selected")
        e.target.classList.add("selected")
        html_element: HTMLElement = e.target
        self.dispatchEvent(FilterEvent(html_element.dataset["route"]))


@js
class TodoApp(CustomElement):

    @js(include=True)
    @classmethod
    def create(cls, tasks: list[str]):
        task_elements = [TodoItem.create(task) for task in tasks]
        has_tasks = len(tasks) > 0
        return tag(cls(), tw(".todo-app"),
            tag("section", tw("app"),
                TodoTopbar.create(len(tasks)),
                tag("main", tw("main"),
                    tag(
                        "ul", tw("todo-list"),
                        {"style": "display:" + ("block" if has_tasks else "none")},
                        *task_elements
                    )
                ),
                TodoBottombar.create(len(tasks)),
            )
        )

    @js(include=True)
    def initialize(self):
        self.list: HTMLElement = self.querySelector(".todo-list")
        self.topbar: TodoTopbar = self.querySelector(TodoTopbar.tagName)
        self.bottombar: TodoBottombar = self.querySelector(TodoBottombar.tagName)
        self.addEventListener(ToggleEvent.eventName, self.toggle_tasks)
        self.addEventListener(FilterEvent.eventName, self.filter_tasks)
        self.addEventListener(ClearCompletedEvent.eventName, self.clear_tasks)
        self.addEventListener(CreateTaskEvent.eventName, self.create_task)
        self.addEventListener(DeleteTaskEvent.eventName, self.delete_task)

    def update(self):
        count = len(self.list.children)
        self.list.style.display = "block" if count > 0 else "none"
        self.topbar.update(count)
        self.bottombar.update(count, self.active_count())

    def active_count(self):
        i = 0
        for child in self.list.children:
            task: TodoItem = child
            if not task.toggleButton.checked:
                i += 1
        return i

    def toggle_tasks(self, e: ToggleEvent):
        e.preventDefault()
        checked = e.detail
        if isinstance(checked, bool):
            for task in self.list.children:
                if isinstance(task, TodoItem):
                    task.toggleButton.checked = checked
        self.update()

    def filter_tasks(self, e: FilterEvent):
        e.preventDefault()
        filter: str = e.detail
        for task in self.list.children:
            if isinstance(task, TodoItem):
                if filter == "completed":
                    task.style.display = "block" if task.toggleButton.checked else "none"
                elif filter == "active":
                    task.style.display = "none" if task.toggleButton.checked else "block"
                else:
                    task.style.display = "block"

    def clear_tasks(self, e: ClearCompletedEvent):
        e.preventDefault()
        for child in [*self.list.children]:
            task: TodoItem = child
            if task.toggleButton.checked:
                task.remove()
        self.update()

    def create_task(self, e: CreateTaskEvent):
        e.preventDefault()
        text: str = e.detail
        task = TodoItem.create(text)
        self.list.append(task)
        self.update()

    def delete_task(self, e: DeleteTaskEvent):
        e.preventDefault()
        e.target.remove()
        self.update()


def server_render(tasks: list[str]):
    return tag('div',
        tag('header', tw("header"),
            tag("h1", tw("title"), "todos")
        ),
        TodoApp.create(tasks),
    )


def main():
    customElements.define(TodoItem.tagName, TodoItem)
    customElements.define(TodoTopbar.tagName, TodoTopbar)
    customElements.define(TodoBottombar.tagName, TodoBottombar)
    customElements.define(TodoApp.tagName, TodoApp)


if __name__ == "__main__":
    from pathlib import Path
    from pyjs.server import serve
    client_entry = main.__name__
    server_entry = server_render.__name__
    server_entry_args = (["one", "two", "three"],)
    with open(Path(__file__).resolve().parent / "todo.css") as css_file:
        css = css_file.read()
    serve("todo", client_entry, css, server_entry, *server_entry_args)
