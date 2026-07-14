from dataclasses import dataclass, field
from core.layer import Layer
from PyQt6.QtGui import QPainterPath
from PyQt6.QtCore import QPointF


def clone_work_path(wp: dict | None) -> dict:
    if not wp: return {"nodes": [], "closed": False}
    nodes = []
    for n in wp.get("nodes", []):
        nodes.append({
            "p": QPointF(n["p"]),
            "c1": QPointF(n["c1"]),
            "c2": QPointF(n["c2"])
        })
    return {"nodes": nodes, "closed": wp.get("closed", False)}


@dataclass
class HistoryState:
    description: str
    layers_snapshot: list[Layer]
    active_layer_index: int
    doc_width:  int = 0
    doc_height: int = 0
    selection_snapshot: QPainterPath | None = None
    work_path_snapshot: dict | None = None
    alpha_channels_snapshot: list[dict] | None = None
    color_mode_snapshot: str = "RGB"
    bit_depth_snapshot: int = 8


def _state_images(state: HistoryState):
    """Yield every QImage referenced by a snapshot (images, masks, smart originals)."""
    for layer in state.layers_snapshot or []:
        img = getattr(layer, "image", None)
        if img is not None:
            yield img
        mask = getattr(layer, "mask", None)
        if mask is not None:
            yield mask
        smd = getattr(layer, "smart_data", None)
        if smd and smd.get("original") is not None:
            yield smd["original"]


class HistoryManager:
    """
    Command-pattern history for undo / redo.
    Stores full layer snapshots (simple & reliable).
    Bounded both by state count and by estimated memory: snapshots taken
    with `modified_index` share unmodified QImages, so byte accounting
    deduplicates by object identity across both stacks.
    """

    DEFAULT_MAX_BYTES = 1_500_000_000  # ~1.5 GB

    def __init__(self, max_states: int = 40, max_bytes: int | None = None):
        self.max_states = max_states
        if max_bytes is None:
            max_bytes = self._max_bytes_from_settings()
        self.max_bytes = max_bytes
        self._undo_stack: list[HistoryState] = []
        self._redo_stack: list[HistoryState] = []

    @classmethod
    def _max_bytes_from_settings(cls) -> int:
        try:
            from PyQt6.QtCore import QSettings
            settings = QSettings("ImageFinish", "ImageFinish")
            return int(settings.value("history/max_bytes", cls.DEFAULT_MAX_BYTES))
        except Exception:
            return cls.DEFAULT_MAX_BYTES

    def estimated_bytes(self) -> int:
        """Total unique image bytes held by both stacks. Snapshots share
        pixel data copy-on-write, so dedup uses QImage.cacheKey(), which
        identifies the underlying data rather than the Python wrapper."""
        seen: set[int] = set()
        total = 0
        for state in self._undo_stack + self._redo_stack:
            for img in _state_images(state):
                key = img.cacheKey()
                if key not in seen:
                    seen.add(key)
                    total += img.sizeInBytes()
        return total

    # ---------------------------------------------------------------- Push
    def push(self, state: HistoryState):
        self._undo_stack.append(state)
        self._redo_stack.clear()
        if len(self._undo_stack) > self.max_states:
            self._undo_stack.pop(0)
        # Evict oldest states while over the memory budget. Keep at least
        # one state so undo of the last operation always works.
        while len(self._undo_stack) > 1 and self.estimated_bytes() > self.max_bytes:
            self._undo_stack.pop(0)

    # --------------------------------------------------------------- Undo/Redo
    def undo(self) -> HistoryState | None:
        if self._undo_stack:
            return self._undo_stack.pop()
        return None

    def redo(self) -> HistoryState | None:
        if self._redo_stack:
            return self._redo_stack.pop()
        return None

    def save_for_redo(self, state: HistoryState):
        self._redo_stack.append(state)

    # ---------------------------------------------------------------- Queries
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo_description(self) -> str:
        return self._undo_stack[-1].description if self._undo_stack else ""

    def redo_description(self) -> str:
        return self._redo_stack[-1].description if self._redo_stack else ""

    def clear(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
