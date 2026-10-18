"""View menu toggles (rulers, guides, grid, slices, snapping), theme and language (moved out of MainWindow)."""

from PyQt6.QtGui import QAction
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QMenu
from core.locale import available_languages
from core.locale import current as locale_current
from core.locale import load as locale_load
from core.locale import tr
from ui.document_controller import require_document


class ViewActionsMixin:
    def _sync_view_actions(self):
        """Sync View menu action checked states with the current document/canvas."""
        doc = self._document
        canvas = self._canvas
        if doc:
            self._act_guides.setChecked(getattr(doc, "show_guides", True))
            self._act_grid.setChecked(getattr(doc, "show_grid", False))
            self._act_slices.setChecked(getattr(doc, "show_slices", True))
            snap = getattr(doc, "snap_enabled", True)
            self._act_snap.setChecked(snap)
            self._act_snap_guides.setChecked(getattr(doc, "snap_to_guides", True))
            self._act_snap_guides.setEnabled(snap)
            self._act_snap_grid.setChecked(getattr(doc, "snap_to_grid", False))
            self._act_snap_grid.setEnabled(snap)
            self._act_snap_bounds.setChecked(getattr(doc, "snap_to_bounds", True))
            self._act_snap_bounds.setEnabled(snap)
            self._act_snap_layers.setChecked(getattr(doc, "snap_to_layers", True))
            self._act_snap_layers.setEnabled(snap)
        if canvas:
            self._act_rulers.setChecked(getattr(canvas, "show_rulers", False))

    # ================================================================= Events
    @require_document
    def _toggle_rulers(self):
        self._canvas.show_rulers = self._act_rulers.isChecked(); self._canvas.update()

    def _toggle_guides(self):
        if hasattr(self._document, "show_guides"): self._document.show_guides = self._act_guides.isChecked(); self._canvas.update()

    def _toggle_grid(self):
        if hasattr(self._document, "show_grid"): self._document.show_grid = self._act_grid.isChecked(); self._canvas.update()

    def _toggle_slices(self):
        if hasattr(self._document, "show_slices"): self._document.show_slices = self._act_slices.isChecked(); self._canvas.update()

    def _toggle_snap(self):
        enabled = self._act_snap.isChecked()
        self._act_snap_guides.setEnabled(enabled); self._act_snap_grid.setEnabled(enabled)
        self._act_snap_bounds.setEnabled(enabled); self._act_snap_layers.setEnabled(enabled)
        if hasattr(self._document, "snap_enabled"): self._document.snap_enabled = enabled

    def _toggle_snap_guides(self):
        if hasattr(self._document, "snap_to_guides"): self._document.snap_to_guides = self._act_snap_guides.isChecked()

    def _toggle_snap_grid(self):
        if hasattr(self._document, "snap_to_grid"): self._document.snap_to_grid = self._act_snap_grid.isChecked()

    def _toggle_snap_bounds(self):
        if hasattr(self._document, "snap_to_bounds"): self._document.snap_to_bounds = self._act_snap_bounds.isChecked()

    def _toggle_snap_layers(self):
        if hasattr(self._document, "snap_to_layers"): self._document.snap_to_layers = self._act_snap_layers.isChecked()

    @require_document
    def _clear_guides(self):
        if hasattr(self._document, "guides_v"): self._document.guides_v.clear()
        if hasattr(self._document, "guides_h"): self._document.guides_h.clear()
        self._canvas.update()

    # ── Language ───────────────────────────────────────────────────────────────
    def _build_language_menu(self, parent_menu: QMenu):
        lang_m = self._menu(parent_menu, "menu.language")
        cur = locale_current()
        for code, name in available_languages():
            act = QAction(name, self, checkable=True)
            act.setChecked(code == cur)
            act.triggered.connect(lambda checked, c=code: self._set_language(c))
            lang_m.addAction(act)
            self._lang_acts[code] = act

    def _build_theme_menu(self, parent_menu):
        from ui import theme
        theme_m = self._menu(parent_menu, "menu.theme")
        self._theme_acts = {}
        for name, key in (("dark", "menu.theme_dark"),
                          ("light", "menu.theme_light"),
                          ("custom", "menu.theme_custom")):
            act = QAction(tr(key), self)
            act.setCheckable(True)
            act.setChecked(theme.current_theme() == name)
            act.triggered.connect(lambda checked, n=name: self._set_theme(n))
            theme_m.addAction(act)
            self._all_acts.append((key, act))
            self._theme_acts[name] = act
        theme_m.addSeparator()
        self._act(theme_m, "menu.theme_configure", self._configure_custom_theme)

    def _set_theme(self, name: str):
        from ui import theme
        if name == theme.current_theme():
            self._theme_acts[name].setChecked(True)
            return
        theme.set_theme(name)
        theme.save_theme(name)
        self._apply_theme_live()

    def _configure_custom_theme(self):
        """One main color drives the whole palette (surfaces take its hue,
        accents are the color itself), on a dark or light lightness base."""
        from ui import theme
        from PyQt6.QtWidgets import QColorDialog, QMessageBox
        from PyQt6.QtCore import QSettings
        s = QSettings("ImageFinish", "ImageFinish")
        start = QColor(str(s.value("theme_custom_color", "#7c3aed")))
        color = QColorDialog.getColor(start, self, tr("dlg.theme_main_color"))
        if not color.isValid():
            return
        base = "dark"
        reply = QMessageBox.question(
            self, tr("menu.theme"), tr("dlg.theme_base_question"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No:
            base = "light"
        s.setValue("theme_custom_color", color.name())
        s.setValue("theme_custom_base", base)
        theme.set_theme("custom")
        theme.save_theme("custom")
        self._apply_theme_live()

    def _apply_theme_live(self):
        from ui import theme
        for n, act in self._theme_acts.items():
            act.setChecked(n == theme.current_theme())
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.build_stylesheet())
        self.setStyleSheet(theme.build_stylesheet())
        theme.repolish_all()
        self._toolbar.retheme()
        self._refresh_layers()
        self._refresh_secondary_panels()
        for i in range(self._doc_tabs.count()):
            self._doc_tabs.widget(i).update()
        self._status.showMessage(tr("status.theme_applied"), 4000)

    def _set_language(self, code: str):
        if code == locale_current():
            return
        locale_load(code)
        self._apply_language()

    def _apply_language(self):
        from ui.qt_translations import install_qt_translator
        install_qt_translator(locale_current())
        for key, act in self._all_acts:
            act.setText(tr(key))
        for key, menu in self._all_menus:
            menu.setTitle(tr(key))
        cur = locale_current()
        for code, act in self._lang_acts.items():
            act.setChecked(code == cur)
        self._update_mode_menu()
        self._update_recent_menu()
        self._toolbar.retranslate()
        self._opts_bar.retranslate()
        self._layers_panel.retranslate()
        self._color_panel.retranslate()
        self._channels_panel.retranslate()
        self._panel_manager.retranslate()
        for panel in (self._history_panel, self._navigator_panel, self._info_panel,
                      self._histogram_panel, self._brushes_panel, self._swatches_panel,
                      self._paths_panel, self._properties_panel, self._actions_panel,
                      self._tool_presets_panel, self._character_panel,
                      self._paragraph_panel, self._glyphs_panel):
            if hasattr(panel, "retranslate"):
                panel.retranslate()
        if hasattr(self, "_welcome_panel"):
            self._welcome_panel.retranslate()
        self._refresh_layers()
