"""Tests for the text normalisation layer."""

import pytest

from bom_validator.core import normalize as nz


class TestClean:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, ""),
            ("", ""),
            ("  hello  ", "hello"),
            ("nan", ""),
            ("NaN", ""),
            ("None", ""),
            ("a\u200bb", "ab"),
            ("a\u00a0b", "a b"),
            ("multi   space", "multi space"),
        ],
    )
    def test_clean(self, raw, expected):
        assert nz.clean(raw) == expected

    def test_persian_digits(self):
        assert nz.clean("۱۲۳۴۵") == "12345"
        assert nz.clean("٩٨٧") == "987"

    def test_mixed(self):
        assert nz.clean(" کد ۱۲۳ ") == "کد 123"


class TestCanonical:
    def test_case_folding(self):
        assert nz.canonical("ABC") == nz.canonical("abc")

    def test_dot_zero_trim(self):
        assert nz.canonical("1110101.0") == "1110101"
        assert nz.canonical("1110101.00") == "1110101"
        assert nz.canonical("11.5") == "11.5"

    def test_leading_zeros(self):
        assert nz.canonical("00042", strip_zeros=True) == "42"
        assert nz.canonical("00042", strip_zeros=False) == "00042"
        assert nz.canonical("0000", strip_zeros=True) == "0"

    def test_arabic_yeh_kaf(self):
        assert nz.canonical("مونتاژ ماشيني") == nz.canonical("مونتاژ ماشینی")
        assert nz.canonical("كار") == nz.canonical("کار")

    def test_case_sensitive_mode(self):
        assert nz.canonical("ABC", case_insensitive=False) == "ABC"


class TestHeaderKey:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Part Name", "partname"),
            ("  Stock No.  ", "stockno"),
            ("Center-X(mm)", "centerxmm"),
            ("QTY", "qty"),
            ("Brand / Supplier ", "brandsupplier"),
            ("SPCO Stock Number", "spcostocknumber"),
        ],
    )
    def test_header_key(self, raw, expected):
        assert nz.header_key(raw) == expected


class TestToInt:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("12", 12),
            ("12.0", 12),
            (12.0, 12),
            ("۱۲", 12),
            (" 7 ", 7),
            ("12 pcs", 12),
            ("", None),
            (None, None),
            ("abc", None),
            ("-5", -5),
            ("2.6", 3),
        ],
    )
    def test_to_int(self, raw, expected):
        assert nz.to_int(raw) == expected

    def test_default(self):
        assert nz.to_int("garbage", default=0) == 0


class TestToFloat:
    def test_basic(self):
        assert nz.to_float("10.5") == pytest.approx(10.5)
        assert nz.to_float("۱۰.۵") == pytest.approx(10.5)
        assert nz.to_float("") is None
        assert nz.to_float("x", default=0.0) == 0.0


class TestDesignators:
    def test_comma_list(self):
        assert nz.expand_designators("C1, C2, C3") == ("C1", "C2", "C3")

    def test_semicolons_and_newlines(self):
        assert nz.expand_designators("R1;R2\nR3") == ("R1", "R2", "R3")

    def test_range_expansion(self):
        assert nz.expand_designators("C1-C5") == ("C1", "C2", "C3", "C4", "C5")
        assert nz.expand_designators("R10~R12") == ("R10", "R11", "R12")

    def test_mixed(self):
        assert nz.expand_designators("U1, C1-C3, R9") == (
            "U1", "C1", "C2", "C3", "R9",
        )

    def test_dedup(self):
        assert nz.expand_designators("C1, C1, c1") == ("C1",)

    def test_empty(self):
        assert nz.expand_designators("") == ()
        assert nz.expand_designators(None) == ()

    def test_absurd_range_not_expanded(self):
        out = nz.expand_designators("C1-C99999")
        assert out == ("C1-C99999",)

    def test_natural_sort(self):
        items = ["C10", "C2", "C1", "R3"]
        assert sorted(items, key=nz.designator_sort_key) == ["C1", "C2", "C10", "R3"]


class TestSimilarity:
    def test_identical(self):
        assert nz.similarity("abc", "abc") == 1.0

    def test_empty(self):
        assert nz.similarity("", "x") == 0.0

    def test_partial(self):
        s = nz.similarity(
            "capacitor,x7r,100n,50v,10%,0603", "capacitor,x7r,100n,50v,10%,0402"
        )
        assert 0.7 < s < 1.0

    def test_unrelated(self):
        assert nz.similarity("capacitor", "microcontroller") < 0.5
