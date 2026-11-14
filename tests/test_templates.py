"""Проверка, что все шаблоны дашборда компилируются."""

from __future__ import annotations

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "dashboard" / "templates"


class TemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
        self.env.filters["dt"] = lambda value: value
        self.env.filters["num"] = lambda value: value
        self.env.filters["duration"] = lambda value: value
        self.env.globals.update(
            avatar_url=lambda *args: "",
            guild_icon=lambda *args: "",
            condition_labels={},
            all_event_keys=[],
            duration_input=lambda value: "",
        )

    def test_templates_compile(self) -> None:
        for name in self.env.list_templates():
            with self.subTest(template=name):
                self.env.get_template(name)

    def test_picker_macros_render(self) -> None:
        class ChannelType:
            name = "text"

        class Channel:
            id = 10
            name = "general"
            type = ChannelType()

        class Role:
            id = 20
            name = "VIP"
            color = "#5865f2"
            managed = False

        template = self.env.from_string(
            '{% from "components.html" import channel_picker, role_picker %}'
            '{{ channel_picker("channels", channels, [10]) }}'
            '{{ role_picker("roles", roles, [20]) }}'
        )
        html = template.render(channels=[Channel()], roles=[Role()])
        self.assertIn('name="channels"', html)
        self.assertIn('name="roles"', html)
        self.assertIn("general", html)
        self.assertIn("VIP", html)


if __name__ == "__main__":
    unittest.main()
