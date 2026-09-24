"""The field codex overlay: pages the rule reference built in ``eador.reference``."""

from saga2d import Anchor, Column, Label

from eador.preferences import reading_scale
from eador.reading import reading_pages
from eador.model import HERO_CLASSES
from eador.reference import CATEGORIES, INTRODUCTIONS, codex_entries
from eador.scene import Screen
from eador.style import GOLD, MUTED, TEAL, TEXT


class CodexScene(Screen):
    """Inspect rules without changing the root campaign or writing save files.

    Number keys select a category; Tab/Shift+Tab cycle categories. Left/Right
    or Page Up/Page Down turn measured whole-entry pages. T opens the scoped
    reading-size setting. Escape closes this overlay.
    """

    transparent = True
    pop_on_cancel = True
    controls = {"tab": "next_category", "shift+tab": "previous_category",
                ("left", "pageup"): "previous_page", ("right", "pagedown"): "next_page",
                "home": "first_page", "end": "last_page"}

    def __init__(self, root):
        super().__init__()
        self.root = root
        self.category = 0
        self.page = 0
        self._page_indices = [[]]
        self._laid_out_category = None

    @property
    def pages(self):
        return len(self._page_indices)

    @property
    def visible_entries(self):
        """The whole entries on the current measured page, in reading order."""
        return tuple(self.entries[index] for index in self._page_indices[self.page])

    def on_reveal(self):
        self.refresh()

    def update(self, dt):
        if self._display != (self.game.window_size, reading_scale(self.game)):
            self.refresh()

    def refresh(self):
        anchor = (self._page_indices[self.page][0] if self._laid_out_category == self.category
                  and self._page_indices[self.page] else 0)
        super().refresh()
        self.entries = self.read_entries()
        self.x, self.y = self.game.width / 2 - 520, self.game.height / 2 - 350
        self._display = self.game.window_size, reading_scale(self.game)
        scale = self._display[1] / 100
        intro = Label(INTRODUCTIONS[self.category], width=992, wrap=True, font="Verdana",
                      font_size=round(13 * scale), text_color=MUTED)
        self._blocks = [Column(
            Label(entry.title, width=992, wrap=True, font="Verdana", font_size=round(19 * scale), text_color=TEAL),
            Label(entry.facts, width=992, wrap=True, font="Verdana", font_size=round(12 * scale), text_color=GOLD),
            Label(entry.description, width=992, wrap=True, font="Verdana", font_size=round(13 * scale), text_color=TEXT),
            spacing=6,
        ) for entry in self.entries]
        # Attachment supplies the actual backend/font before public preferred-size
        # queries. Column owns all line and row positions; the game owns paging.
        self.ui.add(Column(intro, *self._blocks, spacing=20, anchor=Anchor.TOP_LEFT,
                           margin=(round(self.x + 24), round(self.y + 163))))
        available = 451 - intro.get_preferred_size()[1] - 20
        heights = [block.get_preferred_size()[1] for block in self._blocks]

        # Reflow around the old first entry, so changing reading size cannot move
        # the reader to a different rule or quietly hide part of that entry.
        self._page_indices, self.page = reading_pages(heights, available, anchor=anchor, spacing=20)
        self._laid_out_category = self.category
        for i, category in enumerate(CATEGORIES):
            self.button(category, self.x + 24 + i * 167, self.y + 104, 157,
                        lambda i=i: self.select_category(i), shortcut=str(i + 1), primary=i == self.category)
        self.button("Text size", self.x + 830, self.y + 41, 186, self.open_text_settings, shortcut="T")
        self._previous = self.button("Previous", self.x + 24, self.y + 634, 150, self.previous_page, hotkey="←")
        self._next = self.button("Next", self.x + 184, self.y + 634, 150, self.next_page, hotkey="→")
        self.button("Close codex", self.x + 830, self.y + 634, 186, self.game.pop, shortcut="Esc")
        self._show_page()

    def _show_page(self):
        visible = self._page_indices[self.page]
        for index, block in enumerate(self._blocks):
            block.visible = index in visible
        self._previous.enabled = self.page > 0
        self._next.enabled = self.page + 1 < self.pages

    def open_text_settings(self):
        from eador.settings_scene import SettingsScene
        self.game.push(SettingsScene(focus="codex_text_scale"))

    def select_category(self, index):
        self.category, self.page = index, 0
        self._laid_out_category = None
        self.refresh()

    def next_category(self):
        self.select_category((self.category + 1) % len(CATEGORIES))

    def previous_category(self):
        self.select_category((self.category - 1) % len(CATEGORIES))

    def previous_page(self):
        self.page = max(0, self.page - 1)
        self._show_page()

    def next_page(self):
        self.page = min(self.pages - 1, self.page + 1)
        self._show_page()

    def first_page(self):
        self.page = 0
        self._show_page()

    def last_page(self):
        self.page = self.pages - 1
        self._show_page()

    def read_entries(self):
        return codex_entries(self.root.state, CATEGORIES[self.category])

    def draw(self):
        x, y = self.x, self.y
        state = self.root.state
        self.draw_rect(0, 0, self.game.width, self.game.height, (6, 14, 19, 225))
        self.box(x, y, 1040, 700)
        self.text("THE FIELD CODEX", x + 24, y + 20, size=10, color=GOLD)
        self.text("Know your forces", x + 24, y + 41, size=30, serif=True)
        self.text(f"{state.hero.hero_class} · {HERO_CLASSES[state.hero.hero_class].description}",
                  x + 24, y + 81, size=12, color=MUTED)
        self.rule(x + 24, y + 148, 992)
        self.rule(x + 24, y + 620, 992)
        self.text(f"{CATEGORIES[self.category]} · Page {self.page + 1} of {self.pages} · {len(self.entries)} entries",
                  x + 354, y + 640, size=13, color=MUTED)
        self.text("1–6 tabs  /  Tab, Shift+Tab cycle  /  ← → pages", x + 354, y + 664,
                  size=10, color=MUTED)
