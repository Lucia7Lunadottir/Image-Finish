"""Brush size steps for the keyboard ([ ] as in Photoshop, Ctrl + keypad
+/− as in Paint): small steps for a small brush, big ones for a big one."""

MIN_SIZE, MAX_SIZE = 1, 5000

# (size below which the step applies, step)
_STEPS = ((10, 1), (100, 10), (200, 25), (300, 50), (1000, 100), (MAX_SIZE + 1, 250))


def step_size(size: int, direction: int) -> int:
    """The next size up (direction > 0) or down from `size`, snapped to the
    step grid the way Photoshop does (37 → 40 up, 37 → 30 down)."""
    size = max(MIN_SIZE, min(MAX_SIZE, int(size)))
    if direction > 0:
        step = next(s for limit, s in _STEPS if size < limit)
        new = (size // step + 1) * step
    else:
        below = size - 1
        step = next(s for limit, s in _STEPS if below < limit)
        new = (below // step) * step
    return max(MIN_SIZE, min(MAX_SIZE, new))
