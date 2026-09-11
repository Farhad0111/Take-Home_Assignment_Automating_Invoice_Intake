"""Unit tests for src/normalizer/date_parser.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.normalizer.date_parser import parse_date


class TestWesternDates:
    def test_iso_slash(self):
        assert parse_date("2026/01/15") == "2026-01-15"

    def test_iso_dot(self):
        assert parse_date("2026.01.15") == "2026-01-15"

    def test_iso_dash(self):
        assert parse_date("2026-01-15") == "2026-01-15"

    def test_kanji_western(self):
        assert parse_date("2026年1月15日") == "2026-01-15"

    def test_kanji_western_zero_padded(self):
        assert parse_date("2026年01月15日") == "2026-01-15"


class TestWarekiDates:
    def test_reiwa_kanji(self):
        # 令和8年 = 2026 (2019 + 8 - 1)
        assert parse_date("令和8年1月15日") == "2026-01-15"

    def test_reiwa_kanji_zero_padded(self):
        assert parse_date("令和08年01月15日") == "2026-01-15"

    def test_reiwa_romaji_dot(self):
        assert parse_date("R8.1.15") == "2026-01-15"

    def test_reiwa_romaji_slash(self):
        assert parse_date("R8/01/15") == "2026-01-15"

    def test_heisei_kanji(self):
        # 平成30年 = 2018 (1989 + 30 - 1)
        assert parse_date("平成30年3月20日") == "2018-03-20"

    def test_reiwa_year_1(self):
        # 令和1年 = 2019
        assert parse_date("令和1年5月1日") == "2019-05-01"


class TestRelativeDates:
    def test_翌月末(self):
        from datetime import date
        # Dec 2025 → Jan 2026 end = 2026-01-31
        result = parse_date("翌月末", reference_date=date(2025, 12, 15))
        assert result == "2026-01-31"

    def test_翌月末_feb(self):
        from datetime import date
        # Jan 2024 → Feb 2024 end = 2024-02-29 (leap year)
        result = parse_date("翌月末", reference_date=date(2024, 1, 10))
        assert result == "2024-02-29"


class TestEdgeCases:
    def test_empty_string(self):
        assert parse_date("") is None

    def test_none_input(self):
        assert parse_date(None) is None

    def test_gibberish(self):
        assert parse_date("foobar") is None

    def test_full_width_digits(self):
        # Full-width digits should be normalized
        assert parse_date("２０２６年１月１５日") == "2026-01-15"
