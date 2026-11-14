"""Тесты разбора длительностей."""

from __future__ import annotations

import unittest

from app.core.durations import DurationError, format_duration, parse_duration, plural_ru


class DurationTests(unittest.TestCase):
    def test_simple_units(self) -> None:
        self.assertEqual(parse_duration("30m"), 1800)
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("7d"), 604800)
        self.assertEqual(parse_duration("1w"), 604800)

    def test_compound(self) -> None:
        self.assertEqual(parse_duration("1h 30m"), 5400)
        self.assertEqual(parse_duration("1d2h3m"), 93780)
        self.assertEqual(parse_duration("1 ч 30 мин"), 5400)

    def test_plain_number_is_minutes(self) -> None:
        self.assertEqual(parse_duration("15"), 900)

    def test_permanent(self) -> None:
        for value in ("perm", "permanent", "навсегда", "0"):
            self.assertIsNone(parse_duration(value))

    def test_invalid(self) -> None:
        with self.assertRaises(DurationError):
            parse_duration("")
        with self.assertRaises(DurationError):
            parse_duration("abc")
        with self.assertRaises(DurationError):
            parse_duration("1h30")
        with self.assertRaises(DurationError):
            parse_duration("10x")
        with self.assertRaises(DurationError):
            parse_duration("0m")

    def test_format(self) -> None:
        self.assertEqual(format_duration(3600), "1 ч")
        self.assertEqual(format_duration(3660), "1 ч 1 мин")
        self.assertEqual(format_duration(None), "бессрочно")
        self.assertEqual(format_duration(0), "0 сек")

    def test_plural(self) -> None:
        self.assertEqual(plural_ru(1, ("день", "дня", "дней")), "день")
        self.assertEqual(plural_ru(3, ("день", "дня", "дней")), "дня")
        self.assertEqual(plural_ru(11, ("день", "дня", "дней")), "дней")
        self.assertEqual(plural_ru(21, ("день", "дня", "дней")), "день")


if __name__ == "__main__":
    unittest.main()
