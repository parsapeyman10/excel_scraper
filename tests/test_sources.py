"""Three-file input mode: BOM + separate top / bot placement workbooks."""

from __future__ import annotations

import json

import pytest

from bom_validator import ValidationProfile, validate_file, validate_sources
from bom_validator.cli import main as cli_main
from bom_validator.config import AppSettings
from bom_validator.models import Layer, Status
from bom_validator.sources import MULTI, SINGLE, SourceError, SourceSet


class TestSourceSet:
    def test_coerce_path(self, tmp_path):
        f = tmp_path / "a.xlsx"
        f.touch()
        s = SourceSet.coerce(str(f))
        assert s.mode == SINGLE
        assert s.primary == f
        assert s.paths == [f]

    def test_coerce_is_idempotent(self, tmp_path):
        s = SourceSet.single(tmp_path / "a.xlsx")
        assert SourceSet.coerce(s) is s

    def test_coerce_mapping_and_sequence(self, tmp_path):
        a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
        m = SourceSet.coerce({"bom": a, "top": b})
        assert m.mode == MULTI and m.top == b and m.bot is None
        q = SourceSet.coerce([a, b])
        assert q.mode == MULTI and q.top == b

    def test_coerce_rejects_garbage(self):
        with pytest.raises(SourceError):
            SourceSet.coerce(42)

    def test_multi_requires_a_placement_file(self, tmp_path):
        f = tmp_path / "a.xlsx"
        f.touch()
        with pytest.raises(SourceError):
            SourceSet.multi(f).validate()

    def test_missing_file_is_reported(self, tmp_path):
        with pytest.raises(SourceError) as exc:
            SourceSet.single(tmp_path / "ghost.xlsx").validate()
        assert "ghost.xlsx" in str(exc.value)

    def test_roles_and_label(self, make_split_workbooks):
        bom, top, bot = make_split_workbooks()
        s = SourceSet.multi(bom, top, bot).validate()
        assert s.role_of(top) == "top"
        assert s.role_of(bot) == "bot"
        assert s.role_of(bom) == "bom"
        assert "montaj.xlsx" in s.label and "top_export.xlsx" in s.label

    def test_hash_covers_every_file(self, make_split_workbooks):
        bom, top, bot = make_split_workbooks()
        both = SourceSet.multi(bom, top, bot).sha256()
        only_top = SourceSet.multi(bom, top, None).sha256()
        assert both != only_top
        assert SourceSet.single(bom).sha256() != both

    def test_round_trips_through_dict(self, make_split_workbooks):
        bom, top, bot = make_split_workbooks()
        s = SourceSet.multi(bom, top, bot)
        assert SourceSet.from_dict(s.to_dict()) == s
        single = SourceSet.single(bom)
        assert SourceSet.from_dict(single.to_dict()) == single

    def test_duplicate_paths_collapse(self, make_split_workbooks):
        bom, top, _bot = make_split_workbooks()
        s = SourceSet.multi(bom, top, top)
        assert s.paths == [bom, top]


class TestThreeFileValidation:
    def test_matches_single_file_result(self, make_split_workbooks, make_workbook):
        bom, top, bot = make_split_workbooks()
        multi = validate_sources(bom, top, bot)
        single = validate_file(make_workbook())
        assert multi.summary.total_lines == single.summary.total_lines
        assert multi.summary.total_placed == single.summary.total_placed
        assert multi.summary.top_placed == single.summary.top_placed
        assert multi.summary.bot_placed == single.summary.bot_placed
        assert all(r.status is Status.PASS for r in multi.results)

    def test_layer_comes_from_the_file(self, make_split_workbooks):
        bom, top, bot = make_split_workbooks()
        report = validate_sources(bom, top, bot)
        assert report.summary.top_placed == 4
        assert report.summary.bot_placed == 2

    def test_default_sheet_name_is_not_ignored(self, make_split_workbooks):
        # "Sheet1" is in ignore_sheet_patterns, yet a dedicated placement
        # export is usually named exactly that — it must still be read.
        bom, top, bot = make_split_workbooks()
        assert validate_sources(bom, top, bot).summary.total_placed == 6

    def test_layer_named_sheet_overrides_the_file(self, make_split_workbooks):
        bom, top, bot = make_split_workbooks(bot_sheet_name="bot side")
        report = validate_sources(bom, top, bot)
        assert report.summary.bot_placed == 2

    def test_single_sided_board(self, make_split_workbooks):
        bom, top, _ = make_split_workbooks(bot=None)
        report = validate_sources(bom, top)
        assert report.summary.top_placed == 4
        assert report.summary.bot_placed == 0
        # C3 / R2 live only on the bottom, so those lines are short
        assert any(r.status is not Status.PASS for r in report.results)

    def test_metadata_records_the_inputs(self, make_split_workbooks):
        bom, top, bot = make_split_workbooks()
        report = validate_sources(bom, top, bot)
        assert report.metadata["source_mode"] == MULTI
        assert report.metadata["source_files"]["top"] == str(top)
        assert report.metadata["placement_sheet_roles"]["top"]
        assert report.metadata["file_size_bytes"] > bom.stat().st_size

    def test_report_json_carries_sources(self, make_split_workbooks):
        bom, top, bot = make_split_workbooks()
        payload = json.loads(validate_sources(bom, top, bot).to_json())
        assert payload["sources"]["mode"] == MULTI
        assert payload["sources"]["bot"] == str(bot)

    def test_single_file_reports_still_expose_sources(self, make_workbook):
        payload = json.loads(validate_file(make_workbook()).to_json())
        assert payload["sources"]["mode"] == SINGLE
        assert payload["sources"]["top"] == ""

    def test_source_label(self, make_split_workbooks, make_workbook):
        bom, top, bot = make_split_workbooks()
        assert "+" in validate_sources(bom, top, bot).source_label
        assert validate_file(make_workbook()).source_label == "board.xlsx"

    def test_orphans_are_detected_across_files(self, make_split_workbooks):
        bom, top, bot = make_split_workbooks(
            bot=[("X9", 1.0, 1.0, 0, "9999999", "Mystery part")]
        )
        report = validate_sources(bom, top, bot)
        assert report.summary.orphan_placements == 1
        assert report.orphan_placements[0].layer is Layer.BOT

    def test_profile_is_honoured(self, make_split_workbooks):
        bom, top, bot = make_split_workbooks(bot=None)
        strict = validate_sources(bom, top, profile=ValidationProfile(qty_tolerance=0))
        lenient = validate_sources(bom, top, profile=ValidationProfile(qty_tolerance=5))
        assert strict.summary.health_score <= lenient.summary.health_score

    def test_missing_placement_file_raises(self, make_split_workbooks, tmp_path):
        bom, _top, _bot = make_split_workbooks()
        with pytest.raises(SourceError):
            validate_sources(bom, tmp_path / "nope.xlsx")


class TestCliThreeFiles:
    def test_validate_accepts_split_files(self, make_split_workbooks, capsys):
        bom, top, bot = make_split_workbooks()
        code = cli_main(
            [
                "validate", str(bom),
                "--top-file", str(top),
                "--bot-file", str(bot),
                "--no-history", "--no-color",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "top 4 / bot 2" in out
        assert "TOP:top_export.xlsx" in out

    def test_reports_are_written(self, make_split_workbooks, tmp_path, capsys):
        bom, top, bot = make_split_workbooks()
        target = tmp_path / "r.json"
        cli_main(
            [
                "validate", str(bom),
                "--top-file", str(top), "--bot-file", str(bot),
                "-r", f"json:{target}", "--no-history", "--no-color",
            ]
        )
        capsys.readouterr()
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["sources"]["mode"] == MULTI

    def test_missing_file_exits_with_error(self, make_split_workbooks, tmp_path, capsys):
        bom, _t, _b = make_split_workbooks()
        code = cli_main(
            ["validate", str(bom), "--top-file", str(tmp_path / "x.xlsx"), "--no-history"]
        )
        assert code == 2
        assert "not found" in capsys.readouterr().err.lower()

    def test_single_file_mode_unchanged(self, make_workbook, capsys):
        code = cli_main(["validate", str(make_workbook()), "--no-history", "--no-color"])
        capsys.readouterr()
        assert code == 0

    def test_inspect_walks_every_file(self, make_split_workbooks, capsys):
        bom, top, bot = make_split_workbooks()
        cli_main(
            ["inspect", str(bom), "--top-file", str(top), "--bot-file", str(bot)]
        )
        out = capsys.readouterr().out
        assert "Mode   : multi" in out
        assert "[top]" in out and "[bot]" in out


class TestRecentSources:
    def test_push_and_read_back(self, tmp_path):
        s = AppSettings()
        a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
        s.push_recent_sources({"mode": "multi", "bom": str(a), "top": str(b), "bot": ""})
        entry = s.recent_source_sets()[0]
        assert entry["mode"] == "multi"
        assert SourceSet.from_dict(entry).top == b.resolve()
        assert s.source_mode == "multi"
        # legacy field stays in sync for older code paths
        assert s.recent_files[0] == str(a.resolve())

    def test_legacy_recent_files_are_upgraded(self, tmp_path):
        s = AppSettings()
        s.push_recent(str(tmp_path / "old.xlsx"))
        entries = s.recent_source_sets()
        assert entries and entries[0]["mode"] == "single"

    def test_duplicates_are_deduplicated(self, tmp_path):
        s = AppSettings()
        entry = {"mode": "single", "bom": str(tmp_path / "a.xlsx"), "top": "", "bot": ""}
        s.push_recent_sources(dict(entry))
        s.push_recent_sources(dict(entry))
        assert len(s.recent_sources) == 1
