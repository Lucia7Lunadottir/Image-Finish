class CompositeContext:
    """Mutable state threaded through `Layer.render_into` calls during one
    `Document._render_composite` pass.

    Exists (rather than passing `document`/`painter`/... as separate
    arguments) because two pieces of it are mutated mid-pass by individual
    layers: `painter` is torn down and rebuilt by adjustment layers (they
    need direct pixel access), and `clip_alpha` is written by one layer and
    read by the next sibling in the same list (a clipping group). Both need
    one shared, mutable object every layer's `render_into` call can read
    from and write back to; a plain object with `painter`/`clip_alpha`
    attributes is that object.
    """

    __slots__ = ("document", "result", "painter", "clip_alpha", "children_map", "view_transform")

    def __init__(self, document, result, painter, children_map):
        self.document = document
        self.result = result
        self.painter = painter
        self.clip_alpha = None
        self.children_map = children_map
        # Set by Document.render_view: document -> `result` pixel mapping
        # when `result` is a zoomed viewport rather than a document-sized
        # image. Layers that touch `result`'s pixels directly (adjustment
        # layers) need it to line their document-space masks up.
        self.view_transform = None
