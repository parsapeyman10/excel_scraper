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
            # the engine already parsed the placement sheets during the run —
            # reuse them instead of paying for a second pass over the workbook
            placements = list(engine.last_placements)
            if not placements:
                placements = self._collect_placements()
            self.signals.finished.emit(report, placements)
        except ValidationCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:
            self.signals.failed.emit(str(exc), traceback.format_exc())

    def _collect_placements(self) -> list[Placement]:
        """Fallback placement read (grids come from the shared workbook cache)."""
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


class LoadSignals(QObject):
    finished = pyqtSignal(object, list)  # loader, sheet names
    failed = pyqtSignal(str)


class WorkbookLoadWorker(QRunnable):
    """Parses a workbook off the UI thread so opening a file never blocks.

    The parsed grids land in the shared loader cache, so the validation run
    that usually follows costs nothing extra.
    """

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.signals = LoadSignals()

    @pyqtSlot()
    def run(self) -> None:  # noqa: D102
        try:
            loader = rd.WorkbookLoader(self.file_path)
            names = loader.sheet_names()  # forces the parse
            self.signals.finished.emit(loader, names)
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class HistorySignals(QObject):
    finished = pyqtSignal(int)
    failed = pyqtSignal(str)


class HistorySaveWorker(QRunnable):
    """Writes the audit-trail row in the background (SQLite + JSON payload)."""

    def __init__(self, store, report: ValidationReport, operator: str = ""):
        super().__init__()
        self.store = store
        self.report = report
        self.operator = operator
        self.signals = HistorySignals()

    @pyqtSlot()
    def run(self) -> None:  # noqa: D102
        try:
            self.signals.finished.emit(int(self.store.save(self.report, self.operator)))
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


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
    """Validates a whole folder in the background, several files at a time."""

    def __init__(self, files: list[str], profile: ValidationProfile, out_dir: str,
                 formats: list[str], workers: int = 0):
        super().__init__()
        self.files = files
        self.profile = profile
        self.out_dir = Path(out_dir)
        self.formats = formats
        self.workers = workers
        self.signals = BatchSignals()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:  # noqa: D102
        import os
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from ..reporting import exporters

        self.out_dir.mkdir(parents=True, exist_ok=True)
        total = len(self.files)
        workers = self.workers or min(max(1, (os.cpu_count() or 2) - 1), total, 8)

        def one(path: str) -> ValidationReport:
            # a private engine per file keeps the run thread-safe
            report = BomValidationEngine(self.profile).run(
                path, cancel=lambda: self._cancelled
            )
            for fmt in self.formats:
                exporters.export(
                    report, fmt, self.out_dir / exporters.default_filename(report, fmt)
                )
            return report

        done = 0
        finished = 0
        if workers <= 1:
            for path in self.files:
                if self._cancelled:
                    break
                finished += 1
                self.signals.progress.emit(finished, total, Path(path).name)
                try:
                    self.signals.file_done.emit(path, one(path))
                    done += 1
                except Exception as exc:
                    self.signals.failed.emit(Path(path).name, str(exc))
            self.signals.finished.emit(done)
            return

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="batch") as ex:
            futures = {ex.submit(one, f): f for f in self.files}
            for fut in as_completed(futures):
                path = futures[fut]
                finished += 1
                self.signals.progress.emit(finished, total, Path(path).name)
                if self._cancelled:
                    continue
                try:
                    self.signals.file_done.emit(path, fut.result())
                    done += 1
                except Exception as exc:
                    self.signals.failed.emit(Path(path).name, str(exc))
        self.signals.finished.emit(done)
