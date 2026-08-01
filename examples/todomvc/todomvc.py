from pyjs import effect, js, js_str, state
from pyjs.web.dom import localStorage, location, window
from pyjs.web.domx import CustomElement, button, input, ref, tag
from pyjs.web.events import CustomEvent, Event, KeyboardEvent
from pyjs.web.javascript import JSON


@js
class TodoRecord:
    def __init__(self, todo_id: str, title: str, completed: bool):
        self.id = todo_id
        self.title = title
        self.completed = completed


@js
class TodoItemEvent(CustomEvent):
    def __init__(self, name: str, item: TodoItem):
        super().__init__(name, detail=item, bubbles=True, cancelable=True)


@js
class ChangeTodoEvent(TodoItemEvent):
    event_name = js_str("todo-change")

    def __init__(self, item: TodoItem):
        super().__init__(ChangeTodoEvent.event_name, item)


@js
class DeleteTodoEvent(TodoItemEvent):
    event_name = js_str("todo-delete")

    def __init__(self, item: TodoItem):
        super().__init__(DeleteTodoEvent.event_name, item)


@js
class TodoItem(CustomElement):
    todo_id = state("")
    title = state("")
    completed = state(False)
    editing = state(False)

    def __init__(self, todo_id: str, title: str, completed: bool = False):
        super().__init__()
        self.todo_id = todo_id
        self.title = title
        self.completed = completed

        self.toggle = ref(
            input(
                {
                    "aria-label": "Toggle todo",
                    "class": "toggle toggle-todo-input",
                    "type": "checkbox",
                }
            )
        )
        self.label = ref(tag("label", {"class": "todo-item-text"}, title))
        self.destroy_button = ref(
            button(
                {
                    "aria-label": "Delete todo",
                    "class": "destroy remove-todo-button",
                    "type": "button",
                }
            )
        )
        self.edit_input = ref(
            input(
                {
                    "aria-label": "Edit todo",
                    "class": "edit edit-todo-input",
                    "type": "text",
                }
            )
        )
        self.item = ref(
            tag(
                "li",
                {"class": "todo-item"},
                tag(
                    "div",
                    {"class": "view display-todo"},
                    self.toggle,
                    self.label,
                    self.destroy_button,
                ),
                tag("div", {"class": "edit-todo-container"}, self.edit_input),
            )
        )
        self.toggle.addEventListener("change", self.toggle_changed)
        self.label.addEventListener("dblclick", self.start_editing)
        self.destroy_button.addEventListener("click", self.delete)
        self.edit_input.addEventListener("blur", self.commit_edit)
        self.edit_input.addEventListener("keydown", self.edit_keydown)
        tag(self, self.item)

    @effect(title)
    def render_title(self):
        self.label.textContent = self.title

    @effect(completed)
    def render_completed(self):
        self.toggle.checked = self.completed
        self.item.classList.toggle("completed", self.completed)

    @effect(editing)
    def render_editing(self):
        self.item.classList.toggle("editing", self.editing)

    def toggle_changed(self, event: Event):
        self.completed = self.toggle.checked
        self.dispatchEvent(ChangeTodoEvent(self))

    def start_editing(self, event: Event):
        self.edit_input.value = self.title
        self.editing = True
        self.edit_input.focus()

    def commit_edit(self, event: Event):
        if not self.editing:
            return
        self.editing = False
        title = self.edit_input.value.strip()
        if title == "":
            self.dispatchEvent(DeleteTodoEvent(self))
            return
        self.title = title
        self.dispatchEvent(ChangeTodoEvent(self))

    def cancel_edit(self):
        self.editing = False
        self.edit_input.value = self.title
        self.edit_input.blur()

    def edit_keydown(self, event: KeyboardEvent):
        if event.key == "Enter":
            event.preventDefault()
            self.edit_input.blur()
        elif event.key == "Escape":
            event.preventDefault()
            self.cancel_edit()

    def delete(self, event: Event):
        self.dispatchEvent(DeleteTodoEvent(self))

    def record(self) -> TodoRecord:
        return TodoRecord(self.todo_id, self.title, self.completed)


@js
class HashChangeListener:
    def __init__(self, app: TodoApp):
        self.app = app

    @js(include=True)
    def handleEvent(self, event: Event):
        self.app.sync_filter_from_location()


@js
class TodoApp(CustomElement):
    storage_key = js_str("todos-pyjs")
    filter = state("all")
    next_id = state(1)

    def __init__(self):
        super().__init__()

        self.new_todo = ref(
            input(
                {
                    "aria-label": "New todo",
                    "autofocus": "",
                    "autocomplete": "off",
                    "class": "new-todo new-todo-input",
                    "placeholder": "What needs to be done?",
                }
            )
        )
        self.toggle_all = ref(
            input(
                {
                    "aria-label": "Mark all as complete",
                    "class": "toggle-all toggle-all-input",
                    "type": "checkbox",
                }
            )
        )
        self.toggle_all_label = ref(
            tag("label", {"class": "toggle-all-label"}, "Mark all as complete")
        )
        toggle_all_control = tag(
            "div",
            {"class": "toggle-all-container"},
            self.toggle_all,
            self.toggle_all_label,
        )
        self.todo_list = ref(tag("ul", {"class": "todo-list"}))
        self.main = ref(
            tag(
                "main",
                {"class": "main", "style": "display:none"},
                toggle_all_control,
                self.todo_list,
            )
        )
        self.count_number = ref(tag("strong", "0"))
        self.count_suffix = ref(tag("span", " items left"))
        self.all_filter = ref(tag("a", {"class": "filter-link selected", "href": "#/"}, "All"))
        self.active_filter = ref(tag("a", {"class": "filter-link", "href": "#/active"}, "Active"))
        self.completed_filter = ref(
            tag("a", {"class": "filter-link", "href": "#/completed"}, "Completed")
        )
        self.clear_completed_button = ref(
            button(
                {
                    "class": "clear-completed clear-completed-button",
                    "style": "display:none",
                    "type": "button",
                },
                "Clear completed",
            )
        )
        self.footer = ref(
            tag(
                "footer",
                {"class": "footer bottombar", "style": "display:none"},
                tag(
                    "span",
                    {"class": "todo-count todo-status"},
                    self.count_number,
                    self.count_suffix,
                ),
                tag(
                    "ul",
                    {"class": "filters filter-list"},
                    tag("li", {"class": "filter-item"}, self.all_filter),
                    tag("li", {"class": "filter-item"}, self.active_filter),
                    tag("li", {"class": "filter-item"}, self.completed_filter),
                ),
                self.clear_completed_button,
            )
        )
        self.new_todo.addEventListener("keydown", self.new_todo_keydown)
        self.toggle_all.addEventListener("change", self.toggle_all_changed)
        self.toggle_all_label.addEventListener("click", self.toggle_all_label_clicked)
        self.clear_completed_button.addEventListener("click", self.clear_completed)
        self.addEventListener(ChangeTodoEvent.event_name, self.todo_changed)
        self.addEventListener(DeleteTodoEvent.event_name, self.delete_todo)
        tag(
            self,
            tag(
                "section",
                {"class": "todoapp app"},
                tag(
                    "header",
                    {"class": "header topbar"},
                    tag("h1", {"class": "title"}, "todos"),
                    self.new_todo,
                ),
                self.main,
                self.footer,
            ),
            tag(
                "footer",
                {"class": "info"},
                tag("p", "Double-click to edit a todo"),
                tag("p", "Created with ", tag("a", {"href": "https://pyjs.org"}, "pyjs")),
                tag("p", "Part of ", tag("a", {"href": "https://todomvc.com"}, "TodoMVC")),
            ),
        )

    def initialize(self):
        self.hash_listener = HashChangeListener(self)
        window.addEventListener("hashchange", self.hash_listener)
        self.load()
        self.sync_filter_from_location()
        self.update()
        self.new_todo.focus()

    @js(include=True)
    def disconnectedCallback(self):
        window.removeEventListener("hashchange", self.hash_listener)

    def active_count(self) -> int:
        count = 0
        for child in self.todo_list.children:
            item: TodoItem = child
            if not item.completed:
                count = count + 1
        return count

    def completed_count(self) -> int:
        return len(self.todo_list.children) - self.active_count()

    def new_todo_keydown(self, event: KeyboardEvent):
        if event.key != "Enter":
            return
        event.preventDefault()
        title = self.new_todo.value.strip()
        if title == "":
            return
        self.add_todo(title)
        self.new_todo.value = ""

    def add_todo(self, title: str) -> TodoItem | None:
        title = title.strip()
        if title == "":
            return None
        next_id = self.next_id
        self.next_id += 1
        item = TodoItem(str(next_id), title)
        self.todo_list.append(item)
        self.update()
        return item

    def todo_changed(self, event: ChangeTodoEvent):
        event.preventDefault()
        self.update()

    def delete_todo(self, event: DeleteTodoEvent):
        event.preventDefault()
        item: TodoItem = event.detail
        item.remove()
        self.update()

    def toggle_all_changed(self, event: Event):
        self.set_all_completed(self.toggle_all.checked)

    def toggle_all_label_clicked(self, event: Event):
        self.set_all_completed(not self.toggle_all.checked)

    def set_all_completed(self, completed: bool):
        for child in self.todo_list.children:
            item: TodoItem = child
            item.completed = completed
        self.update()

    def clear_completed(self, event: Event):
        completed_items: list[TodoItem] = []
        for child in self.todo_list.children:
            item: TodoItem = child
            if item.completed:
                completed_items.append(item)
        for item in completed_items:
            item.remove()
        self.update()

    def update(self):
        total = len(self.todo_list.children)
        active = self.active_count()
        completed = total - active
        display = "block" if total > 0 else "none"
        self.main.style.display = display
        self.footer.style.display = display
        self.count_number.textContent = str(active)
        self.count_suffix.textContent = " item left" if active == 1 else " items left"
        self.toggle_all.checked = total > 0 and completed == total
        self.clear_completed_button.style.display = "block" if completed > 0 else "none"
        self.apply_filter()
        self.save()

    def sync_filter_from_location(self):
        filter_name = "all"
        if location.hash == "#/active":
            filter_name = "active"
        elif location.hash == "#/completed":
            filter_name = "completed"
        self.filter = filter_name
        self.apply_filter()

    def apply_filter(self):
        filter_name = self.filter
        self.all_filter.classList.toggle("selected", filter_name == "all")
        self.active_filter.classList.toggle("selected", filter_name == "active")
        self.completed_filter.classList.toggle("selected", filter_name == "completed")
        for child in self.todo_list.children:
            item: TodoItem = child
            visible = True
            if filter_name == "active":
                visible = not item.completed
            elif filter_name == "completed":
                visible = item.completed
            item.style.display = "block" if visible else "none"

    def save(self):
        records: list[TodoRecord] = []
        for child in self.todo_list.children:
            item: TodoItem = child
            records.append(item.record())
        localStorage.setItem(TodoApp.storage_key, JSON.stringify(records))

    def load(self):
        stored = localStorage.getItem(TodoApp.storage_key)
        if stored is None or stored == "":
            return
        records: list[TodoRecord] = JSON.parse(stored)
        next_id = 1
        for record in records:
            self.todo_list.append(TodoItem(record.id, record.title, completed=record.completed))
            record_id = int(record.id)
            if record_id >= next_id:
                next_id = record_id + 1
        self.next_id = next_id


def main():
    return TodoApp()


if __name__ == "__main__":
    from pathlib import Path

    from pyjs.server import serve

    example_root = Path(__file__).parent
    stylesheet = "\n".join(
        [
            (example_root / "base.css").read_text(),
            (example_root / "index.css").read_text(),
        ]
    )
    serve("todomvc", stylesheet)
