"""The one gate in front of every pixel command (Filter menu, Image >
Adjustments, and on the canvas every tool with a `PIXEL_OP`): which layer
it may change.

Before this, most commands took the active layer as is. On a text, shape
or fill layer they changed only its baked thumbnail copy — nothing visible
on the canvas, yet an undo step was recorded — and on an adjustment layer
they changed its unused image. A few filters instead silently ignored
everything but raster/smart-object layers, and on the canvas a hard-coded
list of tool names was refused on text/smart objects only (a brush stroke
on a shape, fill or adjustment layer vanished). Now, as in Photoshop, a
layer drawn from data is offered for rasterizing first, and a layer
without pixels of its own gets a status-bar message. Painting on a layer
*mask* is always allowed — the mask is real pixels on any layer kind."""
from PyQt6.QtWidgets import QMessageBox

from core.locale import tr


def pixel_layer_for_edit(win, op: str = "filter"):
    """The active layer, ready for a pixel operation *op* ("filter",
    "paint", "transform" — see Layer.pixel_access_for) — or None (the
    command must then do nothing). May rasterize the layer after asking;
    the caller can tell by the returned layer not being the one it saw."""
    doc = win._document
    layer = doc and doc.get_active_layer()
    if layer is None:
        return None
    if op == "paint" and getattr(layer, "editing_mask", False) and layer.mask is not None:
        return layer
    access = layer.pixel_access_for(op)
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
        if layer is None or layer.pixel_access_for(op) != "direct":
            return None
    if layer.image is None or layer.image.isNull():
        return None
    return layer
