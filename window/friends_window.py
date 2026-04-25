from PySide6.QtWidgets import QWidget

from services.friends_service import FriendsService
from window.controllers.friends_controller import FriendsController
from window.views.friends_view import FriendsView


class FriendsWindow(FriendsView):
    def __init__(self, main_window: QWidget):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.controller = FriendsController(
            view=self,
            main_window=main_window,
            service=FriendsService(),
        )

    def refresh(self):
        self.set_mode(FriendsView.MODE_FRIENDS)
        self.controller.refresh()
