from pyjs import js, js_str
from pyjs.dom import HTMLElement, CustomEvent, Event, KeyboardEvent
from pyjs.domx import CustomElement, tag, input, tw


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
class TodoItem(CustomElement):

    def __init__(self, task: str):
        super().__init__()
        self.toggleButton = input(tw("toggle-todo-input"), {"type": "checkbox"})
        self.toggleButton.addEventListener(
            "click", lambda e: self.dispatchEvent(ToggleEvent(self))
        )
        self.todoText = tag("span", tw("todo-item-text truncate-singleline"), {"tabindex": "0"}, task)
        self.todoText.addEventListener("click", self.start_editing)
        self.removeButton = tag("button", tw("remove-todo-button"), {"title": "Remove Todo"})
        self.removeButton.addEventListener(
            "click", lambda e: self.dispatchEvent(DeleteTaskEvent(self))
        )
        self.editInput = input(tw("edit-todo-input"))
        self.editInput.addEventListener("blur", self.stop_editing)
        self.editInput.addEventListener("keydown", self.keydown)
        self.item = tag("li", tw("todo-item"),
            tag("div", tw("display-todo"),
                tag("label", tw("toggle-todo-label visually-hidden"), {"for": "toggle-todo"}, "Toggle Todo"),
                self.toggleButton,
                self.todoText,
                self.removeButton,
            ),
            tag("div", tw("edit-todo-container"),
                tag("label", tw("edit-todo-label visually-hidden"), {"for": "edit-todo"}, "Edit todo"),
                self.editInput,
            ),
        )
        tag(self, self.item)

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

    def __init__(self, count: int):
        super().__init__()
        self.todoInput = input(tw("new-todo-input"), {"placeholder":"What needs to be done?", "autofocus":True})
        self.todoInput.addEventListener('keydown', self.keydown)
        self.toggleButton = input(tw("toggle-all-input"), {"type":"checkbox"})
        self.toggleButton.addEventListener(
            "click", lambda e: self.dispatchEvent(ToggleEvent(self.toggleButton.checked))
        )
        self.toggleContainer = tag("div", tw("toggle-all-container"), {"style":"display:" + ("block" if count > 0 else "none")},
            self.toggleButton,
            tag("label", tw("toggle-all-label"), {"for":"toggle-all"}, "Mark all todos as complete."),
        )
        tag(self,
            tag("header", tw("topbar"),
                tag("div", tw("new-todo-display"),
                    tag("label", tw("visually-hidden"), {"for":"new-todo"}, "Enter a new todo."),
                    self.todoInput,
                ),
                self.toggleContainer
            )
        )

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

    def __init__(self, count: int):
        super().__init__()
        self.allButton = tag("a", tw("filter-link selected"), {"href":"#/", "data-route":"all"}, "All")
        self.allButton.addEventListener("click", self.change_filter)
        self.activeButton = tag("a", tw("filter-link"), {"href":"#/active", "data-route":"active"}, "Active")
        self.activeButton.addEventListener("click", self.change_filter)
        self.completedButton = tag("a", tw("filter-link"), {"href": "#/completed", "data-route":"completed"}, "Completed")
        self.completedButton.addEventListener("click", self.change_filter)
        self.clearCompletedButton = tag("button", tw("clear-completed-button"), "Clear completed")
        self.clearCompletedButton.addEventListener(
            "click", lambda e: self.dispatchEvent(ClearCompletedEvent())
        )
        self.todoCount = tag("div", tw("todo-status"), "1 item left" if count == 1 else f"{count} items left")
        self.element = tag("footer", tw("bottombar"), {"style":"display:" + ("block" if count > 0 else "none")},
            self.todoCount,
            tag("ul", tw("filter-list"),
                tag("li", tw("filter-item"), self.allButton),
                tag("li", tw("filter-item"), self.activeButton),
                tag("li", tw("filter-item"), self.completedButton),
            ),
            self.clearCompletedButton,
        )
        tag(self, self.element)

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

    def __init__(self, tasks: list[str]):
        super().__init__()
        task_elements = [TodoItem(task) for task in tasks]
        has_tasks = len(tasks) > 0
        self.list = tag(
            "ul", tw("todo-list"),
            {"style": "display:" + ("block" if has_tasks else "none")},
            *task_elements
        )
        self.topbar = TodoTopbar(len(tasks))
        self.bottombar = TodoBottombar(len(tasks))
        self.addEventListener(ToggleEvent.eventName, self.toggle_tasks)
        self.addEventListener(FilterEvent.eventName, self.filter_tasks)
        self.addEventListener(ClearCompletedEvent.eventName, self.clear_tasks)
        self.addEventListener(CreateTaskEvent.eventName, self.create_task)
        self.addEventListener(DeleteTaskEvent.eventName, self.delete_task)
        tag(self, tw(".todo-app"),
            tag("section", tw("app"),
                self.topbar,
                tag("main", tw("main"), self.list),
                self.bottombar,
            )
        )

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
        task = TodoItem(text)
        self.list.append(task)
        self.update()

    def delete_task(self, e: DeleteTaskEvent):
        e.preventDefault()
        e.target.remove()
        self.update()


def main(tasks: list[str]):
    return tag('div',
        tag('header', tw("header"),
            tag("h1", tw("title"), "todos")
        ),
        TodoApp(tasks),
    )


if __name__ == "__main__":
    from pathlib import Path
    from pyjs.server import serve
    with open(Path(__file__).resolve().parent / "todo.css") as css_file:
        css = css_file.read()
    serve(Path(__file__).stem, css, main.__name__, *(["one", "two", "three"],))
