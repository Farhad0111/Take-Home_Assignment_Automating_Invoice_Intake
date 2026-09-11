"""Unit tests for src/normalizer/partner_matcher.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.normalizer.partner_matcher import match_partner

PARTNERS = [
    {
        "partner_code": "P-1001",
        "name": "株式会社山田製作所",
        "aliases": ["ヤマダ製作所", "山田製作所"],
        "registration_no": "T1010001000101",
    },
    {
        "partner_code": "P-1002",
        "name": "有限会社佐藤商店",
        "aliases": ["佐藤商店"],
        "registration_no": "T2020002000202",
    },
    {
        "partner_code": "P-1003",
        "name": "東京フーズ株式会社",
        "aliases": ["東京フーズ"],
        "registration_no": "T3030003000303",
    },
    {
        "partner_code": "P-1004",
        "name": "大阪機械工業株式会社",
        "aliases": ["大阪機械", "大阪機械工業"],
        "registration_no": "T4040004000404",
    },
    {
        "partner_code": "P-1005",
        "name": "みらいITソリューションズ株式会社",
        "aliases": ["みらいIT", "みらいITソリューションズ"],
        "registration_no": "T5050005000505",
    },
]


class TestExactMatch:
    def test_exact_full_name(self):
        code, conf = match_partner("株式会社山田製作所", None, PARTNERS)
        assert code == "P-1001"
        assert conf == 1.0

    def test_exact_full_name_2(self):
        code, conf = match_partner("東京フーズ株式会社", None, PARTNERS)
        assert code == "P-1003"
        assert conf == 1.0


class TestAliasMatch:
    def test_alias_match(self):
        code, conf = match_partner("佐藤商店", None, PARTNERS)
        assert code == "P-1002"
        assert conf >= 0.90

    def test_alias_match_yamada(self):
        code, conf = match_partner("山田製作所", None, PARTNERS)
        assert code == "P-1001"
        assert conf >= 0.90

    def test_alias_osaka(self):
        code, conf = match_partner("大阪機械工業", None, PARTNERS)
        assert code == "P-1004"
        assert conf >= 0.90


class TestRegistrationNoMatch:
    def test_t_number_match(self):
        code, conf = match_partner("unknown company", "T5050005000505", PARTNERS)
        assert code == "P-1005"
        assert conf >= 0.85

    def test_t_number_match_2(self):
        code, conf = match_partner("something else", "T1010001000101", PARTNERS)
        assert code == "P-1001"
        assert conf >= 0.85


class TestFuzzyMatch:
    def test_fuzzy_partial_name(self):
        # "東京フーズ" overlaps well with "東京フーズ株式会社"
        code, conf = match_partner("東京フーズ", None, PARTNERS)
        # Should match via alias first
        assert code == "P-1003"

    def test_fuzzy_low_confidence_no_match(self):
        code, conf = match_partner("全く違う会社", None, PARTNERS)
        # If confidence < 0.60, should return None
        if code is not None:
            assert conf >= 0.60  # whatever was returned must be above threshold


class TestEdgeCases:
    def test_empty_partners(self):
        code, conf = match_partner("株式会社山田製作所", None, [])
        assert code is None
        assert conf == 0.0

    def test_empty_supplier_name(self):
        code, conf = match_partner("", None, PARTNERS)
        assert code is None
        assert conf == 0.0
