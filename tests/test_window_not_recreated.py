"""Opening the first document must not recreate the main window's native
window (the "app closes and reopens / window vanishes on Wayland" bug):
adding the first QOpenGLWidget canvas to a window that had none makes Qt
destroy and recreate the native window to switch to GPU composition."""
from PyQt6.QtCore import QEvent, QObject

from core.document import Document


class _SurfaceSpy(QObject):
    def __init__(self):
        super().__init__()
        self.events = []

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.PlatformSurface:
            self.events.append(ev.surfaceEventType())
        return False


def test_first_document_keeps_the_native_window(main_window, qapp):
    w = main_window
    w.winId()               # the native window exists (no show: nothing paints GL offscreen)
    window = w.windowHandle()
    spy = _SurfaceSpy()
    window.installEventFilter(spy)
    w._add_tab(Document(64, 64), "a")
    qapp.processEvents()
    assert spy.events == []
    assert w.windowHandle() is window
