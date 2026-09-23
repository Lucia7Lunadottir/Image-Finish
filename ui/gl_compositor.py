"""GPU-accelerated blit of the document composite for CanvasWidget.

CanvasWidget is a QOpenGLWidget whose paintGL() still does most of its
drawing with QPainter (grid, guides, selection marching ants, rulers,
brush cursor, ...) exactly as before. The one part that used to cost real
CPU time every frame — `painter.drawImage()` resampling the whole
composited QImage on every repaint, including every pan/zoom step — is
replaced by GLCompositor: it uploads the composite to a GPU texture only
when the image actually changes (tracked via QImage.cacheKey()) and then
draws it as a textured quad, so panning/zooming an unchanged composite is
free CPU-side.

Verified experimentally (not from Qt docs alone) against this app's actual
PyQt6/Qt6 build:
- The mix-QPainter-with-raw-GL pattern only composites correctly when the
  raw GL calls happen inside `paintGL()` (wrapped in
  painter.beginNativePainting()/endNativePainting()). The same code inside
  a hand-rolled `paintEvent()` override produced a blank grabFramebuffer()
  — QOpenGLWidget's internal FBO setup apparently isn't engaged unless
  paintGL() is what triggers it. So CanvasWidget's frame-drawing method is
  named paintGL(), not paintEvent(); QOpenGLWidget's own paintEvent()
  drives initializeGL()/paintGL() for us.
- QImage.Format_ARGB32_Premultiplied's in-memory byte order matches
  GL_BGRA/GL_UNSIGNED_BYTE directly — no channel swizzling needed.
"""

import ctypes

from OpenGL import GL as gl
from PyQt6.QtCore import QRect

from core.app_logging import get_logger

logger = get_logger("gl_compositor")

_VERTEX_SRC = """
#version 330 core
layout(location = 0) in vec2 aPos;
layout(location = 1) in vec2 aTex;
out vec2 vTex;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    vTex = aTex;
}
"""

_FRAGMENT_SRC = """
#version 330 core
in vec2 vTex;
out vec4 FragColor;
uniform sampler2D uTex;
void main() {
    FragColor = texture(uTex, vTex);
}
"""


class GLCompositor:
    """One shader program + one texture + one dynamic quad VBO, owned by a
    single CanvasWidget's GL context. `ready` is False (and every method a
    no-op) if setup failed for any reason — callers must keep the existing
    QPainter.drawImage() path as a fallback, this class never being usable
    is an expected, silently-handled outcome, not an error to surface."""

    def __init__(self):
        self.ready = False
        self._program = None
        self._vao = None
        self._vbo = None
        self._texture = None
        self._tex_w = 0
        self._tex_h = 0
        self._cache_key = None
        try:
            self._init_gl()
            self.ready = True
        except Exception:
            logger.exception("GPU compositor setup failed — canvas falls back to CPU blit")

    @staticmethod
    def _compile_shader(src, kind):
        sh = gl.glCreateShader(kind)
        gl.glShaderSource(sh, src)
        gl.glCompileShader(sh)
        if not gl.glGetShaderiv(sh, gl.GL_COMPILE_STATUS):
            log = gl.glGetShaderInfoLog(sh)
            gl.glDeleteShader(sh)
            raise RuntimeError(f"shader compile failed: {log}")
        return sh

    def _init_gl(self):
        vs = self._compile_shader(_VERTEX_SRC, gl.GL_VERTEX_SHADER)
        fs = self._compile_shader(_FRAGMENT_SRC, gl.GL_FRAGMENT_SHADER)
        prog = gl.glCreateProgram()
        gl.glAttachShader(prog, vs)
        gl.glAttachShader(prog, fs)
        gl.glLinkProgram(prog)
        gl.glDeleteShader(vs)
        gl.glDeleteShader(fs)
        if not gl.glGetProgramiv(prog, gl.GL_LINK_STATUS):
            log = gl.glGetProgramInfoLog(prog)
            gl.glDeleteProgram(prog)
            raise RuntimeError(f"shader link failed: {log}")
        self._program = prog

        self._vao = gl.glGenVertexArrays(1)
        self._vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self._vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo)
        # 4 verts * (pos.xy + tex.xy) floats; refilled every draw() call,
        # since pan/zoom move the quad — texcoords are the only fixed part.
        gl.glBufferData(gl.GL_ARRAY_BUFFER, 4 * 4 * 4, None, gl.GL_DYNAMIC_DRAW)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, False, 16, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(1, 2, gl.GL_FLOAT, False, 16, ctypes.c_void_p(8))
        gl.glBindVertexArray(0)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

        self._texture = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._texture)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

    def _update_texture(self, img, dirty_rect=None):
        key = img.cacheKey()
        if key == self._cache_key:
            return
        w, h = img.width(), img.height()
        stride_px = img.bytesPerLine() // 4
        ptr = img.constBits()
        buf = (ctypes.c_uint8 * img.sizeInBytes()).from_address(int(ptr))

        # A dirty-rect brush stroke patches the *same* QImage in place
        # (core/document.py's get_composite), so QImage.cacheKey() still
        # changes on every dab — it has no concept of "how much changed",
        # only "did anything". Re-uploading the whole texture every dab on
        # an 8K canvas (256MB+ each time) is the actual cost of drawing
        # lag; glTexSubImage2D of just the touched rect is the fix. Only
        # trusted when the texture already holds this exact image at this
        # exact size — a resize, a channel-view swap, undo/redo, or the
        # very first frame all go through the full-image path instead.
        full_upload = (dirty_rect is None or self._cache_key is None
                       or w != self._tex_w or h != self._tex_h)

        gl.glBindTexture(gl.GL_TEXTURE_2D, self._texture)
        gl.glPixelStorei(gl.GL_UNPACK_ROW_LENGTH, stride_px)
        if full_upload:
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
                             gl.GL_BGRA, gl.GL_UNSIGNED_BYTE, buf)
        else:
            rect = dirty_rect.intersected(QRect(0, 0, w, h))
            if not rect.isEmpty():
                gl.glPixelStorei(gl.GL_UNPACK_SKIP_PIXELS, rect.x())
                gl.glPixelStorei(gl.GL_UNPACK_SKIP_ROWS, rect.y())
                gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, rect.x(), rect.y(),
                                   rect.width(), rect.height(),
                                   gl.GL_BGRA, gl.GL_UNSIGNED_BYTE, buf)
                gl.glPixelStorei(gl.GL_UNPACK_SKIP_PIXELS, 0)
                gl.glPixelStorei(gl.GL_UNPACK_SKIP_ROWS, 0)
        gl.glPixelStorei(gl.GL_UNPACK_ROW_LENGTH, 0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        self._cache_key = key
        self._tex_w, self._tex_h = w, h

    def draw(self, img, pan_x, pan_y, zoom, widget_w, widget_h, dpr, dirty_rect=None):
        """Draw `img` (document pixels) positioned at `pan` and scaled by
        `zoom`, using the same widget-space convention as CanvasWidget's own
        QPainter transform (translate(pan) then scale(zoom)). Must be called
        between painter.beginNativePainting()/endNativePainting().
        `dirty_rect` (document pixels, or None for "whole image may have
        changed") enables the partial-upload fast path in _update_texture."""
        if not self.ready:
            return
        self._update_texture(img, dirty_rect)
        w, h = self._tex_w, self._tex_h
        if w == 0 or h == 0:
            return

        x0, y0 = pan_x, pan_y
        x1, y1 = x0 + w * zoom, y0 + h * zoom
        ww = max(float(widget_w), 1.0)
        wh = max(float(widget_h), 1.0)

        def to_ndc(x, y):
            return (2.0 * x / ww - 1.0, 1.0 - 2.0 * y / wh)

        nx0, ny0 = to_ndc(x0, y0)
        nx1, ny1 = to_ndc(x1, y1)

        # Order: top-left, top-right, bottom-left, bottom-right (matches
        # QImage row 0 == top, sampled at texcoord v=0 == top vertices —
        # verified against a reference render, see module docstring).
        verts = (ctypes.c_float * 16)(
            nx0, ny0, 0.0, 0.0,
            nx1, ny0, 1.0, 0.0,
            nx0, ny1, 0.0, 1.0,
            nx1, ny1, 1.0, 1.0,
        )

        # Nearest-neighbor once zoomed in enough to see individual pixels,
        # same 0.9 threshold and same intent as the CPU path's
        # SmoothPixmapTransform toggle in CanvasWidget.paintGL().
        filt = gl.GL_NEAREST if zoom > 0.9 else gl.GL_LINEAR

        gl.glViewport(0, 0, int(ww * dpr), int(wh * dpr))
        gl.glEnable(gl.GL_BLEND)
        # Premultiplied-alpha source (QImage::Format_ARGB32_Premultiplied).
        gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE_MINUS_SRC_ALPHA)

        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo)
        gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, ctypes.sizeof(verts), verts)

        gl.glUseProgram(self._program)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._texture)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, filt)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, filt)
        gl.glBindVertexArray(self._vao)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        gl.glUseProgram(0)
        gl.glDisable(gl.GL_BLEND)
