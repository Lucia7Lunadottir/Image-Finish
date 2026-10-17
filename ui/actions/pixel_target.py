"""The one gate in front of every pixel command (Filter menu, Image >
Adjustments): which layer it may change.

Before this, most commands took the active layer as is. On a text, shape
or fill layer they changed only its baked thumbnail copy — nothing visible
on the canvas, yet an undo step was recorded — and on an adjustment layer
they changed its unused image. A few filters instead silently ignored
everything but raster/smart-object layers. Now, as in Photoshop, a layer
drawn from data is offered for rasterizing first, and a layer without
pixels of its own gets a status-bar message."""
from PyQt6.QtWidgets import QMessageBox

from core.locale import tr


def pixel_layer_for_edit(win):
    """The active layer, ready for a pixel edit — or None (the command
    must then do nothing). May rasterize the layer after asking."""
    doc = win._document
    layer = doc and doc.get_active_layer()
    if layer is None:
        return None
    access = layer.pixel_access
    if access == "none":
        win._status.showMessage(tr("err.layer_no_pixels"), 4000)
        return None
    if access == "rasterize":
        reply = QMessageBox.question(
            win, tr("dlg.rasterize.title"), tr("dlg.rasterize.text", name=layer.name),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok)
        if reply != QMessageBox.StandardButton.Ok:
            return None
        win._rasterize_layer()
        layer = doc.get_active_layer()
        if layer is None or layer.pixel_access != "direct":
            return None
    if layer.image is None or layer.image.isNull():
        return None
    return layer
