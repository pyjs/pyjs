from pyjs import js
from pyjs.web.domx import img, ref, tag, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
class Avatar(Widget):
    def __init__(
        self,
        *children,
        size: str = "default",
        fallback: str = "",
        src: str = "",
        alt: str = "",
    ):
        super().__init__()
        self.image = ref(
            img(
                tw("absolute inset-0 size-full object-cover"),
                {
                    "alt": alt,
                    "data-slot": "avatar-image",
                    "src": src,
                    "style": "display: none",
                },
            )
        )
        self.fallback = ref(
            tag(
                "span",
                tw(
                    "flex size-full items-center justify-center bg-slate-100 font-medium text-slate-700"
                ),
                {"data-slot": "avatar-fallback"},
                fallback,
            )
        )
        self.image.addEventListener("load", self.image_loaded)
        self.image.addEventListener("error", self.image_failed)
        self.add(
            tw(
                "relative flex size-10 shrink-0 select-none overflow-hidden rounded-full "
                "ring-1 ring-slate-200 data-[size=sm]:size-8 data-[size=sm]:text-xs "
                "data-[size=lg]:size-12"
            ),
            {"data-size": size, "data-slot": "avatar"},
            self.fallback,
            self.image,
            *children,
        )

    def initialize(self):
        if self.image.complete and self.image.naturalWidth > 0:
            self.show_image(True)

    def show_image(self, loaded: bool):
        self.image.setAttribute("style", "display: block" if loaded else "display: none")
        self.fallback.setAttribute(
            "style", "display: none" if loaded else "display: flex"
        )

    def image_loaded(self, event: Event):
        self.show_image(True)

    def image_failed(self, event: Event):
        self.show_image(False)


@js
def AvatarBadge(*children):
    return tag(
        "span",
        tw(
            "absolute bottom-0 right-0 z-10 inline-flex size-2.5 items-center justify-center "
            "rounded-full bg-emerald-500 ring-2 ring-white"
        ),
        {"data-slot": "avatar-badge"},
        *children,
    )


@js
def AvatarGroup(*children):
    return tag(
        "div",
        tw(
            "flex -space-x-2 [&>[data-slot=avatar]]:ring-2 [&>[data-slot=avatar]]:ring-white"
        ),
        {"data-slot": "avatar-group"},
        *children,
    )


@js
def AvatarGroupCount(*children):
    return tag(
        "div",
        tw(
            "relative flex size-10 shrink-0 items-center justify-center rounded-full "
            "bg-slate-100 text-sm font-medium text-slate-700 ring-2 ring-white"
        ),
        {"data-slot": "avatar-group-count"},
        *children,
    )
