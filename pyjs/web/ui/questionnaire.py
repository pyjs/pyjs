from typing import cast

from pyjs import js
from pyjs.web.dom import Element, HTMLCollection
from pyjs.web.domx import ProxyElement, button, div, input, ref, span, tag, tw
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.html import HTMLElement, HTMLInputElement
from pyjs.web.ui import Widget


@js
def QuestionnaireProgress():
    return div(
        tw("min-h-[1lh] w-fit min-w-[14ch] text-sm font-medium text-slate-500"),
        {
            "aria-label": "Questionnaire progress",
            "aria-live": "polite",
            "data-slot": "questionnaire-progress",
            "role": "progressbar",
        },
        "Question 1 of 1",
    )


@js
def QuestionnaireTitle(*children):
    return tag(
        "legend",
        tw("text-balance text-xl font-semibold text-slate-950"),
        {"data-slot": "questionnaire-title"},
        *children,
    )


@js
def QuestionnaireDescription(*children):
    return tag(
        "p",
        tw("mt-2 text-pretty text-sm leading-6 text-slate-500"),
        {"data-slot": "questionnaire-description"},
        *children,
    )


@js
def QuestionnaireChoices(*children):
    return div(
        tw("mt-6 grid min-w-0 gap-3"),
        {"data-slot": "questionnaire-choices"},
        *children,
    )


@js
class QuestionnaireChoice(ProxyElement):
    def __init__(
        self,
        value: str,
        *children,
        checked: bool = False,
        disabled: bool = False,
        shortcut: str = "",
    ):
        self.control = input(
            tw("absolute inset-0 z-10 size-full cursor-pointer opacity-0"),
            {
                "data-shortcut": shortcut,
                "data-slot": "questionnaire-choice-input",
                "type": "radio",
                "value": value,
            },
        )
        self.control.checked = checked
        self.control.disabled = disabled
        if checked:
            self.control.setAttribute("checked", "")
        if disabled:
            self.control.setAttribute("disabled", "")
        shortcut_element = span(
            tw(
                "pointer-events-none ml-auto hidden shrink-0 rounded border border-slate-300 "
                "px-1.5 py-0.5 text-xs text-slate-500 data-[visible=true]:inline-flex"
            ),
            {
                "aria-hidden": "true",
                "data-slot": "questionnaire-choice-shortcut",
                "data-visible": "true" if shortcut != "" else "false",
            },
            shortcut,
        )
        self.element = tag(
            "label",
            tw(
                "group/questionnaire-choice relative flex min-h-12 cursor-pointer items-start "
                "gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left text-sm "
                "transition-colors outline-none hover:bg-slate-50 "
                "has-[:checked]:border-violet-500 has-[:checked]:bg-violet-50 "
                "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-violet-300 "
                "has-[:disabled]:pointer-events-none has-[:disabled]:opacity-50"
            ),
            {"data-slot": "questionnaire-choice", "data-value": value},
            self.control,
            span(
                tw(
                    "pointer-events-none mt-0.5 flex size-4 shrink-0 items-center "
                    "justify-center rounded-full border border-slate-400 "
                    "after:hidden after:size-2 after:rounded-full after:bg-violet-600 "
                    "group-has-[:checked]/questionnaire-choice:border-violet-600 "
                    "group-has-[:checked]/questionnaire-choice:after:block"
                ),
                {"aria-hidden": "true", "data-slot": "questionnaire-choice-indicator"},
            ),
            span(
                tw("flex min-w-0 flex-1 flex-col leading-snug"),
                {"data-slot": "questionnaire-choice-label"},
                *children,
            ),
            shortcut_element,
        )


@js
def QuestionnaireChoiceDescription(*children):
    return span(
        tw("mt-1 text-xs font-normal leading-5 text-slate-500"),
        {"data-slot": "questionnaire-choice-description"},
        *children,
    )


@js
def QuestionnaireInput(
    placeholder: str = "",
    input_type: str = "text",
    value: str = "",
    label: str = "",
):
    control = input(
        tw(
            "mt-4 min-h-11 w-full min-w-0 rounded-xl border border-slate-300 bg-white "
            "px-3 text-sm text-slate-950 outline-none placeholder:text-slate-400 "
            "focus:border-violet-500 focus:ring-2 focus:ring-violet-200"
        ),
        {
            "aria-label": label or placeholder,
            "data-slot": "questionnaire-input",
            "placeholder": placeholder,
            "type": input_type,
        },
    )
    control.value = value
    return control


@js
def QuestionnaireError(*children):
    return div(
        tw("mt-3 text-sm font-medium text-red-600"),
        {
            "data-slot": "questionnaire-error",
            "hidden": "",
            "role": "alert",
        },
        *children,
    )


@js
def QuestionnaireActions(*children):
    return div(
        tw(
            "mt-6 grid min-h-11 w-full grid-cols-[minmax(0,1fr)_auto_auto] "
            "items-center gap-2"
        ),
        {"data-slot": "questionnaire-actions"},
        *children,
    )


@js
def questionnaire_action(label: str, action: str, variant: str, button_type: str):
    return button(
        tw(
            "inline-flex min-h-10 items-center justify-center rounded-lg px-4 text-sm "
            "font-medium outline-none focus-visible:ring-2 focus-visible:ring-violet-300 "
            "data-[variant=default]:bg-violet-600 data-[variant=default]:text-white "
            "data-[variant=default]:hover:bg-violet-700 data-[variant=outline]:border "
            "data-[variant=outline]:border-slate-300 data-[variant=outline]:bg-white "
            "data-[variant=outline]:text-slate-700 data-[variant=outline]:hover:bg-slate-50"
        ),
        {
            "data-action": action,
            "data-slot": "questionnaire-" + action,
            "data-variant": variant,
            "type": button_type,
        },
        label,
    )


@js
def QuestionnairePrevious(label: str = "Previous"):
    return questionnaire_action(label, "previous", "outline", "button")


@js
def QuestionnaireSkip(label: str = "Skip"):
    return questionnaire_action(label, "skip", "outline", "button")


@js
def QuestionnaireNext(label: str = "Next"):
    return questionnaire_action(label, "next", "default", "button")


@js
def QuestionnaireSubmit(label: str = "Submit"):
    return questionnaire_action(label, "submit", "default", "submit")


@js
class QuestionnaireItem(Widget):
    def __init__(
        self,
        name: str,
        *children,
        required: bool = False,
        multiple: bool = False,
    ):
        super().__init__()
        self.fieldset = ref(
            tag(
                "fieldset",
                tw("min-w-0 border-0 p-0 outline-none"),
                {"data-slot": "questionnaire-item-fieldset", "tabindex": "-1"},
                *children,
            )
        )
        self.add(
            tw("block min-w-0"),
            {
                "data-multiple": "true" if multiple else "false",
                "data-name": name,
                "data-required": "true" if required else "false",
                "data-slot": "questionnaire-item",
            },
            self.fieldset,
        )
        self.configure_controls()

    def configure_controls(self):
        name = self.get_name()
        input_type = "checkbox" if self.allows_multiple() else "radio"
        choices = self.find_slots("questionnaire-choice-input")
        for choice in choices:
            choice.setAttribute("name", name)
            choice.setAttribute("type", input_type)
        inputs = self.find_slots("questionnaire-input")
        for control in inputs:
            control.setAttribute("name", name)

    def find_slots(self, slot: str) -> list[Element]:
        matches: list[Element] = []
        remaining: list[Element] = [self.fieldset]
        index = 0
        while index < len(remaining):
            element = remaining[index]
            index += 1
            if element.getAttribute("data-slot") == slot:
                matches.append(element)
            for child in element.children:
                remaining.append(child)
        return matches

    def get_name(self) -> str:
        name = self.getAttribute("data-name")
        return "" if name is None else name

    def is_required(self) -> bool:
        return self.getAttribute("data-required") == "true"

    def allows_multiple(self) -> bool:
        return self.getAttribute("data-multiple") == "true"

    def is_answered(self) -> bool:
        choices = self.find_slots("questionnaire-choice-input")
        for choice in choices:
            control = cast(HTMLInputElement, choice)
            if control.checked:
                return True
        inputs = self.find_slots("questionnaire-input")
        for item in inputs:
            control = cast(HTMLInputElement, item)
            if control.value.strip() != "":
                return True
        return False

    def validate(self) -> bool:
        valid = not self.is_required() or self.is_answered()
        self.set_invalid(not valid)
        if not valid:
            controls = self.find_slots("questionnaire-choice-input")
            if len(controls) == 0:
                controls = self.find_slots("questionnaire-input")
            if len(controls) > 0:
                cast(HTMLElement, controls[0]).focus()
        return valid

    def set_invalid(self, invalid: bool):
        if invalid:
            self.fieldset.setAttribute("aria-invalid", "true")
        else:
            self.fieldset.removeAttribute("aria-invalid")
        errors = self.find_slots("questionnaire-error")
        if len(errors) > 0:
            error = errors[0]
            if invalid:
                error.removeAttribute("hidden")
            else:
                error.setAttribute("hidden", "")

    def set_active(self, active: bool):
        if active:
            self.setAttribute("data-active", "")
            self.removeAttribute("hidden")
        else:
            self.removeAttribute("data-active")
            self.setAttribute("hidden", "")


@js
class Questionnaire(Widget):
    def __init__(self, *items: QuestionnaireItem):
        super().__init__()
        self.progress = ref(QuestionnaireProgress())
        self.item_container = ref(div(tw("mt-5"), *items))
        self.previous = ref(QuestionnairePrevious())
        self.skip = ref(QuestionnaireSkip())
        self.next = ref(QuestionnaireNext())
        self.submit = ref(QuestionnaireSubmit())
        self.form = ref(
            tag(
                "form",
                tw("flex w-full min-w-0 flex-col"),
                {"data-slot": "questionnaire-form", "novalidate": ""},
                self.progress,
                self.item_container,
                QuestionnaireActions(
                    self.previous,
                    self.skip,
                    self.next,
                    self.submit,
                ),
            )
        )
        self.add(
            tw("block w-full min-w-0"),
            {"data-current": "0", "data-slot": "questionnaire"},
            self.form,
        )
        self.form.addEventListener("click", self.clicked)
        self.form.addEventListener("keydown", self.keydown)
        self.form.addEventListener("submit", self.submitted)
        self.show_item(0)

    def get_items(self) -> HTMLCollection[QuestionnaireItem]:
        return cast(HTMLCollection[QuestionnaireItem], self.item_container.children)

    def current_index(self) -> int:
        value = self.getAttribute("data-current")
        return 0 if value is None else int(value)

    def current_item(self) -> QuestionnaireItem | None:
        index = self.current_index()
        item_index = 0
        for item in self.get_items():
            if item_index == index:
                return item
            item_index += 1
        return None

    def show_item(self, index: int, focus: bool = False):
        items = self.get_items()
        total = len(items)
        if total == 0:
            return
        if index < 0:
            index = 0
        if index >= total:
            index = total - 1
        item_index = 0
        for item in items:
            item.set_active(item_index == index)
            item_index += 1
        self.setAttribute("data-current", str(index))
        label = "Question " + str(index + 1) + " of " + str(total)
        self.progress.replaceChildren(label)
        self.progress.setAttribute("aria-valuemin", "1")
        self.progress.setAttribute("aria-valuemax", str(total))
        self.progress.setAttribute("aria-valuenow", str(index + 1))
        self.progress.setAttribute("aria-valuetext", label)
        self.set_visible(self.previous, index > 0)
        self.set_visible(self.next, index < total - 1)
        self.set_visible(self.submit, index == total - 1)
        current = self.current_item()
        self.set_visible(self.skip, current is not None and not current.is_required())
        if focus and current is not None:
            current.fieldset.focus()

    def set_visible(self, element: Element, visible: bool):
        if visible:
            element.removeAttribute("hidden")
        else:
            element.setAttribute("hidden", "")

    def advance(self, validate: bool):
        current = self.current_item()
        if current is None:
            return
        if validate and not current.validate():
            return
        current.set_invalid(False)
        self.show_item(self.current_index() + 1, focus=True)

    def clicked(self, event: Event):
        target = cast(Element, event.target)
        action_element = target.closest("[data-action]")
        if action_element is None:
            return
        action = action_element.getAttribute("data-action")
        if action == "previous":
            self.show_item(self.current_index() - 1, focus=True)
        elif action == "next":
            self.advance(True)
        elif action == "skip":
            self.advance(False)

    def keydown(self, event: KeyboardEvent):
        target = cast(Element, event.target)
        if target.getAttribute("data-slot") == "questionnaire-input":
            return
        current = self.current_item()
        if current is None:
            return
        key = event.key.lower()
        for element in current.find_slots("questionnaire-choice-input"):
            shortcut = element.getAttribute("data-shortcut")
            if shortcut is not None and shortcut != "" and shortcut.lower() == key:
                event.preventDefault()
                cast(HTMLElement, element).click()
                return

    def submitted(self, event: Event):
        event.preventDefault()
        current = self.current_item()
        if current is not None:
            current.validate()
