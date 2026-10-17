"""File > Open as Layer — adds a raster image as a new layer on the
CURRENT document instead of _open_file's "always a new tab/window"
behavior. Requested directly: opening images always spawned a separate
document, with no way to bring one into an already-open composition.
"""
import tempfile
import os

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from core.document import Document


def _write_temp_png(w, h, color=QColor(255, 0, 0, 255)):
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(color)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(path, "PNG")
    return path


def test_open_as_layer_adds_centered_layer_to_current_document(main_window, monkeypatch):
    w = main_window
    w._add_tab(Document(200, 150), "t")
    doc = w._document
    n_before = len(doc.layers)

    path = _write_temp_png(40, 20, QColor(10, 20, 30, 255))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, "")))

    w._open_file_as_layer()

    assert len(doc.layers) == n_before + 1
    assert doc.active_layer_index == len(doc.layers) - 1
    new_layer = doc.layers[-1]
    assert new_layer.name == os.path.basename(path)
    # centered: (200-40)/2=80, (150-20)/2=65
    assert new_layer.image.pixelColor(80, 65) == QColor(10, 20, 30, 255)
    assert new_layer.image.pixelColor(0, 0).alpha() == 0  # outside placed image stays transparent
    assert w._history.can_undo()

    os.remove(path)


def test_open_as_layer_cancelled_dialog_does_nothing(main_window, monkeypatch):
    w = main_window
    w._add_tab(Document(200, 150), "t")
    doc = w._document
    n_before = len(doc.layers)

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    w._open_file_as_layer()

    assert len(doc.layers) == n_before


def test_open_as_layer_bad_path_shows_error_and_adds_nothing(main_window, monkeypatch):
    w = main_window
    w._add_tab(Document(200, 150), "t")
    doc = w._document
    n_before = len(doc.layers)

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("/no/such/file.png", "")))
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: shown.append(a)))

    w._open_file_as_layer()

    assert len(doc.layers) == n_before
    assert len(shown) == 1


def test_open_as_layer_does_nothing_without_an_open_document(main_window, monkeypatch):
    """require_document guard — no tab open at all."""
    w = main_window
    calls = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: calls.append(1) or ("", "")))

    w._open_file_as_layer()

    assert calls == []  # bailed out before even showing the dialog
