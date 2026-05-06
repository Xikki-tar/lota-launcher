from PySide6.QtWidgets import QWidget

from services.account_service import AccountService
from window.controllers.account_controller import AccountController
from window.views.account_view import AccountView


class AccountWindow(AccountView):
    def __init__(self, main_window: QWidget):
        self.main_window = main_window
        self.service = AccountService()
        super().__init__(skin_path=str(self.service.skin_file()), parent=main_window)
        self.controller = AccountController(
            view=self,
            main_window=main_window,
            service=self.service,
        )
        self.controller.refresh(remote_skin=True)

    def refresh(self, *, remote_skin: bool = False):
        self.controller.refresh(remote_skin=remote_skin)
