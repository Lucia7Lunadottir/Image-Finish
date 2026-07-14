import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication(["imagefinish-tests"])
    yield app


@pytest.fixture()
def mocked_dialogs(qapp, monkeypatch):
    """Neutralize every modal dialog so menu actions run headless."""
    from PyQt6.QtWidgets import (QDialog, QFileDialog, QMessageBox,
                                 QInputDialog, QColorDialog)
    from PyQt6.QtGui import QColor
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)
    monkeypatch.setattr(QMessageBox, "exec", lambda self, *a: 0)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Cancel))
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    monkeypatch.setattr(QInputDialog, "getInt", staticmethod(lambda *a, **k: (0, False)))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("", False)))
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a, **k: QColor()))


@pytest.fixture()
def main_window(qapp):
    from ui.main_window import MainWindow
    w = MainWindow()
    yield w
    w._doc_tabs.clear()
    w.deleteLater()
    _drain_thread_pool()


def _drain_thread_pool():
    """Background QRunnables (thumbnails, histogram) still running at
    interpreter teardown crash the test process on exit."""
    from PyQt6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone(10000)


@pytest.fixture(scope="session", autouse=True)
def _drain_pool_at_session_end():
    yield
    _drain_thread_pool()
