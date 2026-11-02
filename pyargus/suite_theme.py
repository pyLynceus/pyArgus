"""eyeWitness suite appearance, independent of the sibling installation.

Colors and typography follow witness/workspace.json (October 27, 2026).
SURVEY_SUITE_THEME=original restores the original pyArgus light theme at launch.
Only the desktop imports this module; numerical code remains GUI-independent.
"""
import os

SPEC = {'schema': 1,
 'colors': {'background': '#0f1216',
            'panel': '#161b22',
            'field': '#1c232c',
            'border': '#2a323d',
            'text': '#dbe3ec',
            'muted': '#8a97a6',
            'accent': '#4da3ff',
            'warning': '#ffb648',
            'error': '#ff5f56',
            'success': '#4ad07a'},
 'font': 'Segoe UI',
 'font_size': 10,
 'spacing': 8}
COLORS = SPEC["colors"]


def active():
    return os.environ.get("SURVEY_SUITE_THEME", "eyewitness").casefold() in (
        "eyewitness", "witness")


def select_palette(original):
    palette = dict(original)
    if active():
        c = COLORS
        palette.update(ground=c["background"], panel=c["panel"], field=c["field"],
                       ink=c["text"], muted=c["muted"], gold=c["accent"],
                       teal=c["success"], canvas=c["panel"], canvas_text=c["text"])
    return palette


def apply(root):
    from tkinter import font, ttk

    c = COLORS
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=c["background"])
    default_font = font.nametofont("TkDefaultFont", root=root)
    default_font.configure(family=SPEC["font"], size=SPEC["font_size"])
    root.option_add("*Font", "TkDefaultFont")
    # Native Tk widgets do not inherit ttk colors. Cover later-created dialogs,
    # the combobox popdown, review notes, and scrollable settings too.
    defaults = {
        "*Toplevel.background": c["background"],
        "*Frame.background": c["background"],
        "*Label.background": c["background"],
        "*Label.foreground": c["text"],
        "*Canvas.background": c["background"],
        "*Text.background": c["panel"],
        "*Text.foreground": c["text"],
        "*Text.insertBackground": c["text"],
        "*Text.selectBackground": c["accent"],
        "*Text.selectForeground": c["background"],
        "*Text.highlightBackground": c["border"],
        "*Text.highlightColor": c["accent"],
        "*Listbox.background": c["field"],
        "*Listbox.foreground": c["text"],
        "*Listbox.selectBackground": c["accent"],
        "*Listbox.selectForeground": c["background"],
        "*Listbox.disabledForeground": c["muted"],
        "*Menu.background": c["panel"],
        "*Menu.foreground": c["text"],
        "*Menu.activeBackground": c["field"],
        "*Menu.activeForeground": c["accent"],
        "*Menu.disabledForeground": c["muted"],
        "*Menu.selectColor": c["accent"],
    }
    for option, value in defaults.items():
        root.option_add(option, value)
    style.configure(".", font="TkDefaultFont", background=c["background"],
                    foreground=c["text"], fieldbackground=c["field"],
                    troughcolor=c["panel"], bordercolor=c["border"],
                    lightcolor=c["border"], darkcolor=c["border"],
                    focuscolor=c["accent"], selectbackground=c["accent"],
                    selectforeground=c["background"])
    style.map(".", foreground=[("disabled", c["muted"])])
    for name in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(name, foreground=c["text"], fieldbackground=c["field"],
                        background=c["field"], insertcolor=c["text"],
                        arrowcolor=c["text"], padding=5)
        style.map(name, fieldbackground=[("disabled", c["panel"]), ("readonly", c["field"])],
                  foreground=[("disabled", c["muted"]), ("readonly", c["text"])],
                  arrowcolor=[("disabled", c["muted"])],
                  selectbackground=[("!disabled", c["accent"])],
                  selectforeground=[("!disabled", c["background"])])
    for name in ("TButton", "TMenubutton"):
        style.configure(name, background=c["field"], foreground=c["text"],
                        arrowcolor=c["text"], padding=(10, 6))
        style.map(name, background=[("disabled", c["panel"]), ("pressed", c["border"]),
                                    ("active", c["border"])],
                  foreground=[("disabled", c["muted"]), ("active", c["text"])],
                  bordercolor=[("focus", c["accent"]), ("active", c["accent"])],
                  arrowcolor=[("disabled", c["muted"])])
    style.configure("TNotebook", background=c["background"], borderwidth=0)
    for name in ("TNotebook.Tab", "Phase.TNotebook.Tab"):
        style.configure(name, padding=(12, 8), background=c["panel"], foreground=c["muted"])
        style.map(name, background=[("selected", c["field"]), ("active", c["border"])],
                  foreground=[("disabled", c["muted"]), ("selected", c["accent"]),
                              ("active", c["text"])])
    style.configure("Treeview", background=c["panel"], fieldbackground=c["panel"],
                    foreground=c["text"], rowheight=max(28, default_font.metrics("linespace") + 8))
    style.map("Treeview", background=[("selected", c["accent"])],
              foreground=[("selected", c["background"])])
    style.configure("Treeview.Heading", background=c["field"], foreground=c["text"], padding=(8, 6))
    style.map("Treeview.Heading", background=[("active", c["border"])],
              foreground=[("active", c["text"])])
    for name in ("Horizontal.TProgressbar", "Vertical.TProgressbar"):
        style.configure(name, background=c["accent"], troughcolor=c["panel"],
                        bordercolor=c["border"], lightcolor=c["accent"], darkcolor=c["accent"])
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=c["background"], foreground=c["text"],
                        indicatorbackground=c["field"], indicatorforeground=c["background"])
        style.map(name, background=[("active", c["background"])],
                  foreground=[("disabled", c["muted"]), ("active", c["text"])],
                  indicatorbackground=[("disabled", c["border"]), ("selected", c["accent"]),
                                       ("active", c["border"])],
                  indicatorforeground=[("disabled", c["muted"])])
    style.configure("TScrollbar", background=c["field"], arrowcolor=c["text"])
    style.map("TScrollbar", background=[("active", c["border"])], arrowcolor=[("disabled", c["muted"])])
    style.configure("TSeparator", background=c["border"])
    style.configure("TSizegrip", background=c["background"])
    return style
