"""Background workers so the UI never freezes on a big workbook."""

from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from ..config import ValidationProfile
from ..core.engine import BomValidationEngine, ValidationCancelled
from ..io_excel import reader as rd
from ..models import Layer, Placement, ValidationReport


class WorkerSignals(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object, object)  # report, placements
    failed = pyqtSignal(str, str)  # message, traceback
    cancelled = pyqtSignal()


class ValidationWorker(QRunnable):
    """Runs one validation on the global thread pool."""

    def __init__(self, file_path: str, profile: ValidationProfile):
        super().__init__()
        self.file_path = file_path
        self.profile = profile
        self.signals = WorkerSignals()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:  # noqa: D102
        try:
            engine = BomValidationEngine(self.profile)
            report = engine.run(
                self.file_path,
                progress=lambda d, t, m: self.signals.progress.emit(d, t, m),
                cancel=lambda: self._cancelled,
            )
            placements = self._collect_placements()
            self.signals.finished.emit(report, placements)
        except ValidationCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:
            self.signals.failed.emit(str(exc), traceback.format_exc())

    def _collect_placements(self) -> list[Placement]:
        """Re-read placement sheets for the board map (cheap, already cached OS-side)."""
        try:
            loader = rd.WorkbookLoader(self.file_path)
            buckets = rd.classify_sheets(loader.sheet_names(), self.profile)
            out: list[Placement] = []
            for name in buckets["top"]:
                out += rd.extract_placements(loader.sheets[name], Layer.TOP, self.profile)
            for name in buckets["bot"]:
                out += rd.extract_placements(loader.sheets[name], Layer.BOT, self.profile)
            return out
        except Exception:
            return []


class ExportSignals(QObject):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)


class ExportWorker(QRunnable):
    def __init__(self, report: ValidationReport, fmt: str, path: str):
        super().__init__()
        self.report = report
        self.fmt = fmt
        self.path = path
        self.signals = ExportSignals()

    @pyqtSlot()
    def run(self) -> None:  # noqa: D102
        try:
            from ..reporting import exporters

            out = exporters.export(self.report, self.fmt, self.path)
            self.signals.finished.emit(str(out))
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class BatchSignals(QObject):
    file_done = pyqtSignal(str, object)
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int)
    failed = pyqtSignal(str, str)


class BatchWorker(QRunnable):
    """Validates a whole folder in the background."""

    def __init__(self, files: list[str], profile: ValidationProfile, out_dir: str,
                 formats: list[str]):
        super().__init__()
        self.files = files
        self.profile = profile
        self.out_dir = Path(out_dir)
        self.formats = formats
        self.signals = BatchSignals()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:  # noqa: D102
        from ..reporting import exporters

        engine = BomValidationEngine(self.profile)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        done = 0
        for i, f in enumerate(self.files, 1):
            if self._cancelled:
                break
            self.signals.progress.emit(i, len(self.files), Path(f).name)
            try:
                report = engine.run(f)
                for fmt in self.formats:
                    exporters.export(
                        report, fmt, self.out_dir / exporters.default_filename(report, fmt)
                    )
                self.signals.file_done.emit(f, report)
                done += 1
            except Exception as exc:
                self.signals.failed.emit(Path(f).name, str(exc))
        self.signals.finished.emit(done)
