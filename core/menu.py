"""
Reusable Interactive Menu System for Collig

This module provides a flexible, reusable interactive menu system
that can be used by any skill or tool.
"""

from typing import List, Dict, Any, Callable, Optional, Tuple
from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import to_formatted_text


class MenuItem:
    """Represents a single item in a menu."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        data: Any = None,
        detail: str = ""
    ):
        self.title = title
        self.subtitle = subtitle
        self.data = data
        self.detail = detail


class MenuAction:
    """Represents an action that can be performed from the menu."""

    def __init__(
        self,
        key: str,
        label: str,
        callback: Callable[[MenuItem, int], Any],
        modes: List[str] = None  # Which modes this action is available in
    ):
        self.key = key
        self.label = label
        self.callback = callback
        self.modes = modes or ["list", "detail"]


class InteractiveMenu:
    """
    A reusable interactive menu system.

    Features:
    - List view with navigation
    - Detail view for individual items
    - Custom actions with keyboard shortcuts
    - Stays open after actions (configurable)
    """

    def __init__(
        self,
        title: str = "Menu",
        subtitle: str = "",
        items: List[MenuItem] = None,
        stay_open: bool = True,
        show_detail: bool = True
    ):
        self.title = title
        self.subtitle = subtitle
        self.items = items or []
        self.stay_open = stay_open
        self.show_detail = show_detail

        self.selected_index = 0
        self.mode = "list"  # "list" or "detail"
        self.actions: List[MenuAction] = []
        self._running = False

    def add_item(self, item: MenuItem):
        """Add an item to the menu."""
        self.items.append(item)

    def add_action(self, action: MenuAction):
        """Add a custom action to the menu."""
        self.actions.append(action)

    def _truncate_text(self, text: str, max_len: int = 60) -> str:
        """Truncate text for display."""
        if not text:
            return ""
        return text[:max_len] + "..." if len(text) > max_len else text

    def _get_list_text(self):
        """Get the formatted text for the list view."""
        result = []
        result.append(("bold cyan", self.title))
        if self.subtitle:
            result.append(("", f" - {self.subtitle}"))
        result.append(("", "\n\n"))

        for i, item in enumerate(self.items):
            prefix = " > " if i == self.selected_index else "   "
            display_title = self._truncate_text(item.title, 55)

            if i == self.selected_index:
                result.append(("bold reverse", f"{prefix}{i+1}. {display_title}"))
                if item.subtitle:
                    result.append(("dim", f" ({item.subtitle})"))
                result.append(("", "\n"))
            else:
                line = f"{prefix}{i+1}. {display_title}"
                if item.subtitle:
                    line += f" ({item.subtitle})"
                result.append(("", line + "\n"))

        # Build footer
        result.append(("", "\n"))
        footer_parts = []
        footer_parts.append("[↑/↓/k/j] Navigate")
        if self.show_detail:
            footer_parts.append("[Enter] View")
        # Add custom actions
        for action in self.actions:
            if "list" in action.modes:
                footer_parts.append(f"[{action.key}] {action.label}")
        footer_parts.append("[Esc] Quit")
        result.append(("dim", "  ".join(footer_parts)))

        return to_formatted_text(result)

    def _get_detail_text(self):
        """Get the formatted text for the detail view."""
        item = self.items[self.selected_index]

        result = []
        result.append(("bold cyan", f"{item.title}\n\n"))
        if item.subtitle:
            result.append(("dim", f"{item.subtitle}\n\n"))
        if item.detail:
            result.append(("", f"{item.detail}\n\n"))

        # Build footer
        footer_parts = []
        footer_parts.append("[b] Back")
        # Add custom actions
        for action in self.actions:
            if "detail" in action.modes:
                footer_parts.append(f"[{action.key}] {action.label}")
        footer_parts.append("[Esc] Quit")
        result.append(("dim", "  ".join(footer_parts)))

        return to_formatted_text(result)

    def run(self) -> Optional[Any]:
        """
        Run the interactive menu.

        Returns:
            The result of the final action, or None if cancelled.
        """
        if not self.items:
            return None

        self._running = True

        while self._running:
            kb = KeyBindings()

            @kb.add("up")
            @kb.add("k")
            def move_up(event):
                if self.mode == "list":
                    self.selected_index = (self.selected_index - 1) % len(self.items)
                    menu_control.text = self._get_list_text()

            @kb.add("down")
            @kb.add("j")
            def move_down(event):
                if self.mode == "list":
                    self.selected_index = (self.selected_index + 1) % len(self.items)
                    menu_control.text = self._get_list_text()

            @kb.add("enter")
            def view_detail(event):
                if self.mode == "list" and self.show_detail:
                    self.mode = "detail"
                    menu_control.text = self._get_detail_text()

            @kb.add("b")
            def back_to_list(event):
                if self.mode == "detail":
                    self.mode = "list"
                    menu_control.text = self._get_list_text()

            @kb.add("escape")
            @kb.add("q")
            def quit_menu(event):
                self._running = False
                event.app.exit(result=None)

            @kb.add("c-c")
            def ctrl_c(event):
                self._running = False
                event.app.exit(result=None)

            # Add custom action key bindings
            for action in self.actions:
                @kb.add(action.key)
                def make_action_handler(a=action):
                    def handler(event):
                        item = self.items[self.selected_index]
                        result = a.callback(item, self.selected_index)
                        if not self.stay_open:
                            self._running = False
                            event.app.exit(result=result)
                        else:
                            # Just refresh the display
                            if self.mode == "list":
                                menu_control.text = self._get_list_text()
                            else:
                                menu_control.text = self._get_detail_text()
                    return handler

            menu_control = FormattedTextControl(text=self._get_list_text())
            window = Window(
                content=menu_control,
                width=Dimension(min=60, preferred=90),
                height=Dimension(min=15, preferred=25)
            )

            layout = Layout(HSplit([window]))
            app = Application(layout=layout, key_bindings=kb, full_screen=False)

            try:
                result = app.run()
                if not self._running:
                    return result
            except Exception as e:
                print(f"[dim]Menu error: {e}[/dim]")
                return None

        return None


def create_simple_menu(
    items: List[Dict[str, Any]],
    title: str = "Menu",
    subtitle: str = "",
    stay_open: bool = True,
    actions: List[Dict[str, Any]] = None
) -> InteractiveMenu:
    """
    Create a simple interactive menu from a list of dictionaries.

    Args:
        items: List of dicts with 'title', 'subtitle', 'data', 'detail' keys
        title: Menu title
        subtitle: Menu subtitle
        stay_open: Whether to keep menu open after actions
        actions: List of action dicts with 'key', 'label', 'callback' keys

    Returns:
        Configured InteractiveMenu instance
    """
    menu = InteractiveMenu(
        title=title,
        subtitle=subtitle,
        stay_open=stay_open,
        show_detail=True
    )

    for item_data in items:
        item = MenuItem(
            title=item_data.get("title", ""),
            subtitle=item_data.get("subtitle", ""),
            data=item_data.get("data"),
            detail=item_data.get("detail", "")
        )
        menu.add_item(item)

    if actions:
        for action_data in actions:
            action = MenuAction(
                key=action_data.get("key", ""),
                label=action_data.get("label", ""),
                callback=action_data.get("callback"),
                modes=action_data.get("modes", ["list", "detail"])
            )
            menu.add_action(action)

    return menu
