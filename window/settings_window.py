from PySide6.QtWidgets import QWidget

from services.settings_service import SettingsService
from window.controllers.settings_controller import SettingsController
from window.views.settings_view import SettingsView


class SettingsWindow(SettingsView):
    def __init__(self, main_window: QWidget):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.controller = SettingsController(
            view=self,
            main_window=main_window,
            service=SettingsService(),
        )
        self.controller.load_into_ui()

    def refresh(self):
        self.controller.refresh()
