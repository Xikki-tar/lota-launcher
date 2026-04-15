from PySide6.QtWidgets import QWidget

from auth.api_base import get_api_base
from auth.auth_storage import get_data_dir
from services.library_service import LibraryService
from window.controllers.library_controller import LibraryController
from window.views.library_view import LibraryView


class LibraryWindow(LibraryView):
    def __init__(self, main_window: QWidget):
        self.main_window = main_window
        self.library_service = LibraryService(get_data_dir(), get_api_base)
        super().__init__(
            parent=main_window,
            overlay_submit=self._handle_overlay_submit,
            image_picker=self.library_service.pick_random_cached_image,
        )
        self.controller = LibraryController(self, main_window, self.library_service)

    def _handle_overlay_submit(self, payload: dict):
        self.controller.handle_overlay_submit(payload)

    def refresh(self):
        self.controller.refresh()

    def apply_language(self):
        self.controller.apply_language()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.controller.resize()
