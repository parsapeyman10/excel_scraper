"""Input selector: one combined workbook, or three separate files.

Mode ``single`` keeps the historical behaviour (one workbook holding the BOM
plus its ``top``/``bot`` tabs). Mode ``multi`` exposes three independent
slots — *مونتاژ ماشینی* (BOM), **TOP** and **BOT** — for shops whose machine
room exports each layer as its own file.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...sources import SourceError, SourceSet

WORKBOOK_FILTER = "Workbooks (*.xlsx *.xlsm *.xls *.csv *.tsv);;All files (*)"


class FileSlot(QWidget):
    """A labelled read-only path field with Browse / Clear buttons."""

    changed = pyqtSignal()
    activated = pyqtSignal()  # a file was picked (double-click-ish intent)

    def __init__(
        self,
        title: str,
        placeholder: str = "",
        *,
        browse_text: str = "Browse…",
        clear_text: str = "Clear",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.label = QLabel(title)
        self.label.setMinimumWidth(150)
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText(placeholder)
        self.btn_browse = QPushButton(browse_text)
        self.btn_browse.setObjectName("secondary")
        self.btn_browse.setMinimumWidth(96)
        self.btn_browse.setToolTip(title)
        # every slot keeps a clear button so the three rows stay aligned
        self.btn_clear = QPushButton(clear_text)
        self.btn_clear.setObjectName("secondary")
        self.btn_clear.setMinimumWidth(80)

        lay.addWidget(self.label)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn_browse)
        lay.addWidget(self.btn_clear)

        self.btn_browse.clicked.connect(self.browse)
        self.btn_clear.clicked.connect(self.clear)
        self.setAcceptDrops(True)

    # -- value ---------------------------------------------------------
    def path(self) -> str:
        return self.edit.text().strip()

    def set_path(self, value: str) -> None:
        text = str(Path(value).resolve()) if value else ""
        if text != self.edit.text():
            self.edit.setText(text)
            self.edit.setToolTip(text)
            self.changed.emit()

    def clear(self) -> None:
        self.set_path("")

    def set_title(self, title: str) -> None:
        self.label.setText(title)
        self.btn_browse.setToolTip(title)

    def set_button_texts(self, browse: str, clear: str) -> None:
        self.btn_browse.setText(browse)
        self.btn_clear.setText(clear)

    # -- interaction ---------------------------------------------------
    def browse(self) -> None:
        start = str(Path(self.path()).parent) if self.path() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, self.label.text(), start, WORKBOOK_FILTER
        )
        if path:
            self.set_path(path)
            self.activated.emit()

    # drag & drop is how operators actually load these files
    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        urls = event.mimeData().urls()
        if urls:
            self.set_path(urls[0].toLocalFile())
            self.activated.emit()
            event.acceptProposedAction()


class _FittedStack(QStackedWidget):
    """A stack that is only as tall as the page currently shown.

    The default QStackedWidget always reserves room for its tallest page,
    which would leave a three-row gap under the single-workbook view.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def sizeHint(self):  # noqa: N802
        page = self.currentWidget()
        return page.sizeHint() if page else super().sizeHint()

    def minimumSizeHint(self):  # noqa: N802
        page = self.currentWidget()
        return page.minimumSizeHint() if page else super().minimumSizeHint()


class SourcePanel(QWidget):
    """Mode switch plus the file slots for the selected mode."""

    sources_changed = pyqtSignal()
    validate_requested = pyqtSignal()

    def __init__(self, tr, parent: QWidget | None = None):
        super().__init__(parent)
        self.tr_ = tr
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # ---- mode selector --------------------------------------------
        modes = QHBoxLayout()
        modes.setSpacing(14)
        self.rb_single = QRadioButton(tr("mode_single"))
        self.rb_multi = QRadioButton(tr("mode_multi"))
        self.rb_single.setChecked(True)
        self.rb_single.setToolTip(tr("mode_single_hint"))
        self.rb_multi.setToolTip(tr("mode_multi_hint"))
        modes.addWidget(QLabel("<b>" + tr("source_mode") + "</b>"))
        modes.addWidget(self.rb_single)
        modes.addWidget(self.rb_multi)
        modes.addStretch(1)
        lay.addLayout(modes)

        # ---- page 0: single workbook -----------------------------------
        page_single = QWidget()
        ps = QVBoxLayout(page_single)
        ps.setContentsMargins(0, 0, 0, 0)
        self.slot_workbook = self._slot(tr("file_workbook"), tr("no_file"))
        ps.addWidget(self.slot_workbook)

        # ---- page 1: three files ---------------------------------------
        page_multi = QWidget()
        pm = QGridLayout(page_multi)
        pm.setContentsMargins(0, 0, 0, 0)
        pm.setVerticalSpacing(4)
        self.slot_bom = self._slot(tr("file_bom"), tr("no_file"))
        self.slot_top = self._slot(tr("file_top"), tr("optional_file"))
        self.slot_bot = self._slot(tr("file_bot"), tr("optional_file"))
        for row, slot in enumerate((self.slot_bom, self.slot_top, self.slot_bot)):
            pm.addWidget(slot, row, 0)

        self.stack = _FittedStack()
        self.stack.addWidget(page_single)
        self.stack.addWidget(page_multi)
        lay.addWidget(self.stack)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setObjectName("hint")
        self.lbl_hint.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        lay.addWidget(self.lbl_hint)

        # ---- wiring -----------------------------------------------------
        self.rb_single.toggled.connect(self._on_mode_toggled)
        for slot in self._slots():
            slot.changed.connect(self._emit_changed)
            slot.activated.connect(self.validate_requested.emit)
        self._update_hint()

    # -- helpers --------------------------------------------------------
    def _slot(self, title: str, placeholder: str) -> FileSlot:
        return FileSlot(
            title,
            placeholder,
            browse_text=self.tr_("browse"),
            clear_text=self.tr_("clear_file"),
        )

    def _slots(self) -> list[FileSlot]:
        return [self.slot_workbook, self.slot_bom, self.slot_top, self.slot_bot]

    def _on_mode_toggled(self, _checked: bool) -> None:
        self.stack.setCurrentIndex(0 if self.rb_single.isChecked() else 1)
        self._emit_changed()

    def _emit_changed(self) -> None:
        self._update_hint()
        self.sources_changed.emit()

    def _update_hint(self) -> None:
        """Only surface problems here — the control row shows the happy path."""
        tr = self.tr_
        try:
            src = self.sources()
        except SourceError:
            self.lbl_hint.setText("⚠ " + tr("need_placement_file"))
            self.lbl_hint.setVisible(True)
            return
        if src is None:
            # in single mode the field placeholder already says it all
            if self.mode == "single":
                self.lbl_hint.clear()
                self.lbl_hint.setVisible(False)
            else:
                self.lbl_hint.setText(tr("select_bom_first"))
                self.lbl_hint.setVisible(True)
            return
        self.lbl_hint.clear()
        self.lbl_hint.setVisible(False)

    # -- public API -------------------------------------------------------
    @property
    def mode(self) -> str:
        return "single" if self.rb_single.isChecked() else "multi"

    def set_mode(self, mode: str) -> None:
        (self.rb_multi if mode == "multi" else self.rb_single).setChecked(True)

    def sources(self) -> SourceSet | None:
        """Current selection, or ``None`` when nothing is chosen yet.

        Raises :class:`SourceError` when the selection is incomplete.
        """
        if self.mode == "single":
            if not self.slot_workbook.path():
                return None
            return SourceSet.single(self.slot_workbook.path())
        if not self.slot_bom.path():
            return None
        return SourceSet.multi(
            self.slot_bom.path(),
            self.slot_top.path() or None,
            self.slot_bot.path() or None,
        ).validate()

    def is_ready(self) -> bool:
        try:
            return self.sources() is not None
        except SourceError:
            return False

    def set_sources(self, src: SourceSet) -> None:
        """Load a whole set back into the UI (recent files, restored state)."""
        blocked = [(s, s.blockSignals(True)) for s in self._slots()]
        try:
            if src.is_multi:
                self.set_mode("multi")
                self.slot_bom.set_path(str(src.bom))
                self.slot_top.set_path(str(src.top) if src.top else "")
                self.slot_bot.set_path(str(src.bot) if src.bot else "")
            else:
                self.set_mode("single")
                self.slot_workbook.set_path(str(src.bom))
        finally:
            for slot, prev in blocked:
                slot.blockSignals(prev)
        self.stack.setCurrentIndex(1 if src.is_multi else 0)
        self._emit_changed()

    def retranslate(self, tr) -> None:
        self.tr_ = tr
        for slot in self._slots():
            slot.set_button_texts(tr("browse"), tr("clear_file"))
        self.rb_single.setText(tr("mode_single"))
        self.rb_multi.setText(tr("mode_multi"))
        self.slot_workbook.set_title(tr("file_workbook"))
        self.slot_bom.set_title(tr("file_bom"))
        self.slot_top.set_title(tr("file_top"))
        self.slot_bot.set_title(tr("file_bot"))
        self._update_hint()
