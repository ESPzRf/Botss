"""Тесты формулы уровней."""

from __future__ import annotations

import unittest

from app.core.levels import (
    format_number,
    level_for_xp,
    level_progress,
    progress_bar,
    xp_for_level,
)


class LevelTests(unittest.TestCase):
    def test_thresholds(self) -> None:
        self.assertEqual(xp_for_level(0), 0)
        self.assertEqual(xp_for_level(1), 100)
        self.assertEqual(xp_for_level(2), 300)
        self.assertEqual(xp_for_level(3), 600)

    def test_level_for_xp(self) -> None:
        self.assertEqual(level_for_xp(0), 0)
        self.assertEqual(level_for_xp(99), 0)
        self.assertEqual(level_for_xp(100), 1)
        self.assertEqual(level_for_xp(299), 1)
        self.assertEqual(level_for_xp(300), 2)
        self.assertEqual(level_for_xp(10_000), level_for_xp(10_000))

    def test_progress(self) -> None:
        level, current, needed, percent = level_progress(150)
        self.assertEqual(level, 1)
        self.assertEqual(current, 50)
        self.assertEqual(needed, 200)
        self.assertEqual(percent, 25)

    def test_progress_bar(self) -> None:
        self.assertEqual(progress_bar(0, 10), "░" * 10)
        self.assertEqual(progress_bar(100, 10), "█" * 10)
        self.assertEqual(len(progress_bar(37, 10)), 10)

    def test_format_number(self) -> None:
        self.assertEqual(format_number(1234567), "1 234 567")


if __name__ == "__main__":
    unittest.main()
