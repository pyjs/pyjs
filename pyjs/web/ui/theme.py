"""Application theme variables and theme-provider controls."""

from pyjs import JS, js
from pyjs.web.domx import div, tag

THEME_STYLES: JS[str] = """
[data-pyjs-theme] {
  background-color: var(--pyjs-background);
  color: var(--pyjs-foreground);
}
[data-pyjs-theme] [data-slot="button"] {
  border-radius: var(--pyjs-radius);
}
[data-pyjs-theme] [data-slot="button"][data-variant="default"] {
  background-color: var(--pyjs-primary);
  color: var(--pyjs-primary-foreground);
}
[data-pyjs-theme] [data-slot="button"][data-variant="default"]:hover {
  background-color: var(--pyjs-primary-hover);
}
[data-pyjs-theme] [data-slot="button"][data-variant="outline"] {
  background-color: var(--pyjs-surface);
  border-color: var(--pyjs-border);
  color: var(--pyjs-foreground);
}
[data-pyjs-theme] [data-slot="button"][data-variant="outline"]:hover,
[data-pyjs-theme] [data-slot="button"][data-variant="ghost"]:hover {
  background-color: var(--pyjs-muted);
}
[data-pyjs-theme] [data-slot="button"][data-variant="secondary"] {
  background-color: var(--pyjs-muted);
  color: var(--pyjs-foreground);
}
[data-pyjs-theme] [data-slot="button"][data-variant="ghost"],
[data-pyjs-theme] [data-slot="button"][data-variant="link"] {
  background-color: transparent;
  color: var(--pyjs-foreground);
}
[data-pyjs-theme] [data-slot="card"] {
  background-color: var(--pyjs-surface);
  border-color: var(--pyjs-border);
  border-radius: var(--pyjs-radius);
  color: var(--pyjs-surface-foreground);
}
[data-pyjs-theme] [data-slot="card-title"],
[data-pyjs-theme] [data-slot="item-title"] {
  color: var(--pyjs-surface-foreground);
}
[data-pyjs-theme] [data-slot="card-content"],
[data-pyjs-theme] [data-slot="item-description"] {
  color: var(--pyjs-muted-foreground);
}
[data-pyjs-theme] [data-slot="input"],
[data-pyjs-theme] [data-slot="native-select"],
[data-pyjs-theme] [data-slot="textarea"] {
  background-color: var(--pyjs-surface);
  border-color: var(--pyjs-border);
  border-radius: var(--pyjs-radius);
  color: var(--pyjs-foreground);
}
[data-pyjs-theme] [data-slot="input"]:focus,
[data-pyjs-theme] [data-slot="native-select"]:focus,
[data-pyjs-theme] [data-slot="textarea"]:focus {
  border-color: var(--pyjs-ring);
}
[data-pyjs-theme] [data-slot="checkbox"] {
  accent-color: var(--pyjs-primary);
  border-color: var(--pyjs-border);
}
[data-pyjs-theme] [data-slot="badge"][data-variant="default"] {
  background-color: var(--pyjs-primary);
  color: var(--pyjs-primary-foreground);
}
[data-pyjs-theme] [data-slot="badge"][data-variant="secondary"] {
  background-color: var(--pyjs-muted);
  color: var(--pyjs-foreground);
}
[data-pyjs-theme] [data-slot="badge"][data-variant="outline"] {
  border-color: var(--pyjs-border);
  color: var(--pyjs-foreground);
}
"""


@js
class Theme:
    def __init__(
        self,
        name: str,
        *,
        background: str = "#f8fafc",
        foreground: str = "#020617",
        surface: str = "#ffffff",
        surface_foreground: str = "#020617",
        primary: str = "#020617",
        primary_hover: str = "#1e293b",
        primary_foreground: str = "#ffffff",
        muted: str = "#f1f5f9",
        muted_foreground: str = "#64748b",
        border: str = "#cbd5e1",
        ring: str = "#94a3b8",
        radius: str = "0.5rem",
    ):
        self.name = name
        self.background = background
        self.foreground = foreground
        self.surface = surface
        self.surface_foreground = surface_foreground
        self.primary = primary
        self.primary_hover = primary_hover
        self.primary_foreground = primary_foreground
        self.muted = muted
        self.muted_foreground = muted_foreground
        self.border = border
        self.ring = ring
        self.radius = radius

    def style(self) -> str:
        return (
            f"--pyjs-background:{self.background};"
            f"--pyjs-foreground:{self.foreground};"
            f"--pyjs-surface:{self.surface};"
            f"--pyjs-surface-foreground:{self.surface_foreground};"
            f"--pyjs-primary:{self.primary};"
            f"--pyjs-primary-hover:{self.primary_hover};"
            f"--pyjs-primary-foreground:{self.primary_foreground};"
            f"--pyjs-muted:{self.muted};"
            f"--pyjs-muted-foreground:{self.muted_foreground};"
            f"--pyjs-border:{self.border};"
            f"--pyjs-ring:{self.ring};"
            f"--pyjs-radius:{self.radius}"
        )


@js
def ThemeProvider(theme: Theme, *children: object):
    return div(
        {
            "data-pyjs-theme": theme.name,
            "style": theme.style(),
        },
        tag("style", THEME_STYLES),
        *children,
    )
