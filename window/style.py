from pathlib import Path


APP_QSS_TEMPLATE = """
/* === base === */
QWidget {
    color: #F3E7D6;
    font-size: 18px;
    font-family: "Monocraft", "Minecraftia", "Trebuchet MS", "Segoe UI", sans-serif;
}

QWidget#RootWindow {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #0B0A08, stop: 0.55 #15100B, stop: 1 #1B140E
    );
}

QWidget[windowContent="true"] {
    background: transparent;
}

QFrame[windowTitleBar="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #18110C, stop: 0.5 #20160F, stop: 1 #241910
    );
    border-bottom: 1px solid #3A2A1A;
}

QLabel[windowTitleLabel="true"] {
    font-size: 14px;
    font-weight: 700;
    color: #F5DFC0;
    letter-spacing: 0.4px;
}

QLabel[windowVersionLabel="true"] {
    font-size: 10px;
    font-weight: 600;
    color: rgba(203, 183, 158, 0.58);
    letter-spacing: 0.8px;
    padding-left: 6px;
}

QLabel[windowLogo="true"] {
    background: transparent;
    border: none;
}

QPushButton[windowControl="true"] {
    background-color: rgba(255,255,255,0.05);
    border: 1px solid rgba(233, 163, 68, 0.25);
    border-radius: 5px;
    color: #EAD3B5;
    font-size: 12px;
    font-weight: 700;
    padding: 0;
}

QPushButton[windowControl="true"]:hover {
    background-color: rgba(233, 163, 68, 0.16);
    border-color: rgba(233, 163, 68, 0.55);
}

QPushButton[windowClose="true"] {
    border-color: rgba(239, 68, 68, 0.35);
}

QPushButton[windowClose="true"]:hover {
    background-color: rgba(239, 68, 68, 0.22);
    border-color: rgba(239, 68, 68, 0.65);
}

QFrame[toastPopup="true"] {
    background-color: rgba(35, 18, 14, 0.96);
    border: 1px solid rgba(239, 68, 68, 0.45);
    border-radius: 10px;
}

QLabel[toastLabel="true"] {
    color: #F7E4C8;
    font-size: 14px;
    font-weight: 700;
}

QDialog[appDialog="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #18110C, stop: 1 #251912
    );
    border: 1px solid rgba(233, 163, 68, 0.45);
    border-radius: 14px;
}

QLabel[appDialogIcon="true"] {
    background-color: rgba(233, 163, 68, 0.18);
    color: #F5B449;
    border: 1px solid rgba(233, 163, 68, 0.55);
    border-radius: 8px;
    font-size: 16px;
    font-weight: 900;
}

QLabel[appDialogIcon="true"][dialogKind="error"] {
    background-color: rgba(239, 68, 68, 0.16);
    color: #F18A80;
    border-color: rgba(239, 68, 68, 0.55);
}

QLabel[appDialogTitle="true"] {
    color: #F7E4C8;
    font-size: 18px;
    font-weight: 800;
}

QLabel[appDialogText="true"] {
    color: #D9C8B1;
    font-size: 14px;
    font-family: "Noto Sans", "Segoe UI", "Ubuntu", sans-serif;
}

QTextEdit[appDialogTextBox="true"] {
    background-color: rgba(31, 18, 14, 0.96);
    color: #F3A59B;
    border: 1px solid rgba(239, 68, 68, 0.35);
    border-radius: 10px;
    padding: 8px 10px;
    selection-background-color: rgba(233, 163, 68, 0.45);
    selection-color: #FFF6E7;
    font-size: 13px;
    font-family: "Noto Sans Mono", "DejaVu Sans Mono", "Consolas", monospace;
}

QFrame[registerOverlay="true"] {
    background-color: rgba(7, 5, 3, 0.75);
}

QFrame[registerPanel="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #18110C, stop: 1 #23170F
    );
    border: 1px solid #3A2A1A;
    border-radius: 18px;
}

QFrame[registerPanel="true"] QPushButton[registerService="telegram"],
QFrame[registerPanel="true"] QPushButton[registerService="discord"] {
    text-align: left;
    padding: 14px 18px;
    border-radius: 13px;
    font-size: 16px;
    font-weight: 700;
    min-height: 46px;
}

QFrame[registerPanel="true"] QPushButton[registerService="telegram"] {
    background-color: #2AABEE;
    color: #FFFFFF;
    border: 1px solid #53BDF2;
}

QFrame[registerPanel="true"] QPushButton[registerService="telegram"]:hover {
    background-color: #3AB4F1;
    border-color: #7BCEF6;
}

QFrame[registerPanel="true"] QPushButton[registerService="discord"] {
    background-color: #5865F2;
    color: #FFFFFF;
    border: 1px solid #7A84F6;
}

QFrame[registerPanel="true"] QPushButton[registerService="discord"]:hover {
    background-color: #6974F4;
    border-color: #939BF8;
}

QScrollArea {
    background: transparent;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}

QScrollBar:vertical {
    background: rgba(0, 0, 0, 0.18);
    width: 12px;
    margin: 2px 0 2px 2px;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background: rgba(245, 180, 73, 0.6);
    border-radius: 6px;
    min-height: 24px;
    margin: 2px;
    border: 1px solid rgba(233, 163, 68, 0.6);
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

/* === panels === */
QWidget[panel="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #1C1510, stop: 1 #241A12
    );
    border-radius: 24px;
    border: 1px solid #3A2A1A;
}

QWidget[panel2="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #17120E, stop: 1 #1E1610
    );
    border-radius: 22px;
    border: 1px solid #2E2014;
}

QLabel[avatar="true"] {
    background: transparent;
    border: none;
}

/* === titles / captions === */
QLabel[title="true"] {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: 0.3px;
    color: #F7E4C8;
}

QLabel[caption="true"] {
    font-size: 14px;
    color: #CBB79E;
}

QLabel[section="true"] {
    font-size: 14px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: #9C8368;
}

/* === news cards === */
QFrame[newsCard="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #1D1712, stop: 1 #261C13
    );
    border-radius: 18px;
    border: 1px solid #3A2A1A;
    min-height: 260px;
}

QLabel[newsTitle="true"] {
    font-size: 16px;
    font-weight: 800;
    color: #F7E4C8;
}

QLabel[newsDate="true"] {
    font-size: 14px;
    letter-spacing: 0.4px;
    color: #A58E75;
}

QLabel[newsBody="true"] {
    font-size: 14px;
    color: #CBB79E;
}

QLabel[newsImage="true"] {
    background-color: #1B140E;
    border: 1px solid #3A2A1A;
    border-radius: 12px;
}

QLabel[newsTypeBadge="true"] {
    font-size: 14px;
    letter-spacing: 0.6px;
    text-transform: uppercase;
    padding: 6px 12px;
    border-radius: 10px;
    background-color: #2A1E16;
    color: #EAD3B5;
}

QLabel[newsTypeKey="update"] { background-color: rgba(244, 145, 56, 0.2); color: #F2B46B; border: 1px solid rgba(244, 145, 56, 0.45); }
QLabel[newsTypeKey="news"] { background-color: rgba(78, 142, 255, 0.18); color: #9AB8FF; border: 1px solid rgba(78, 142, 255, 0.4); }
QLabel[newsTypeKey="patch"] { background-color: rgba(74, 222, 128, 0.18); color: #B6F3D0; border: 1px solid rgba(74, 222, 128, 0.4); }
QLabel[newsTypeKey="fix"] { background-color: rgba(74, 222, 128, 0.18); color: #B6F3D0; border: 1px solid rgba(74, 222, 128, 0.4); }
QLabel[newsTypeKey="hotfix"] { background-color: rgba(74, 222, 128, 0.18); color: #B6F3D0; border: 1px solid rgba(74, 222, 128, 0.4); }

QPushButton[ghost="true"] {
    background-color: rgba(42, 30, 22, 0.5);
    border: 1px solid rgba(233, 163, 68, 0.55);
    padding: 4px 8px;
    border-radius: 10px;
    font-size: 12px;
    min-height: 20px;
}

QPushButton[ghost="true"]:hover {
    background-color: rgba(51, 36, 25, 0.7);
    border-color: rgba(233, 163, 68, 0.8);
}

QPushButton[accent="true"] {
    background-color: rgba(233, 163, 68, 0.25);
    color: #F3E7D6;
    border: 1px solid rgba(233, 163, 68, 0.6);
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 700;
}

QPushButton[accent="true"]:hover {
    background-color: rgba(233, 163, 68, 0.4);
    border-color: rgba(233, 163, 68, 0.85);
}

/* === news details overlay === */
QFrame[newsOverlay="true"] {
    background-color: rgba(7, 5, 3, 0.75);
}

QFrame[newsDetailPanel="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #1D1712, stop: 1 #261C13
    );
    border-radius: 18px;
    border: 1px solid #3A2A1A;
}

QFrame[friendsSearchCard="true"],
QFrame[friendsSection="true"],
QFrame[friendsCard="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #1D1712, stop: 1 #261C13
    );
    border-radius: 18px;
    border: 1px solid #3A2A1A;
}

QLabel[friendsUserTitle="true"] {
    font-size: 18px;
    font-weight: 800;
    color: #F7E4C8;
}

QLabel[friendsStatus="true"] {
    font-size: 13px;
    color: #D5C3AB;
}

QLabel[friendsMeta="true"] {
    font-size: 12px;
    color: #BFA88C;
}

QLabel[friendsBadge="true"],
QLabel[friendsCountBadge="true"] {
    background-color: rgba(233, 163, 68, 0.18);
    color: #F2C37F;
    border: 1px solid rgba(233, 163, 68, 0.45);
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 700;
    min-width: 24px;
}

QLabel[newsDetailTitle="true"] {
    font-size: 18px;
    font-weight: 800;
    color: #F7E4C8;
}

QLabel[newsDetailDate="true"] {
    font-size: 14px;
    color: #A58E75;
}

QLabel[newsDetailText="true"] {
    font-size: 14px;
    color: #D5C3AB;
}

QLabel[newsDetailSection="true"] {
    font-size: 14px;
    letter-spacing: 1.0px;
    text-transform: uppercase;
    color: #9C8368;
}

/* === instance overlay === */
QFrame[instanceOverlay="true"] {
    background-color: rgba(7, 5, 3, 0.75);
}

QFrame[instancePanel="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #1D1712, stop: 1 #261C13
    );
    border-radius: 18px;
    border: 1px solid #3A2A1A;
}

QLabel[instanceTitle="true"] {
    font-size: 18px;
    font-weight: 800;
    color: #F7E4C8;
}

QFrame[instancePanel="true"] QLabel[caption="true"],
QFrame[instancePanel="true"] QLabel[section="true"] {
    font-size: 12px;
}

QLineEdit[instanceField="true"],
QComboBox[instanceField="true"] {
    font-size: 12px;
    padding: 5px 28px 5px 10px;
    min-height: 24px;
}

QTextEdit[instanceText="true"] {
    font-size: 12px;
    padding: 6px 8px;
}

QListWidget[instanceList="true"] {
    font-size: 12px;
    padding: 4px;
}

QListWidget[instanceList="true"]::item {
    padding: 4px 8px;
}

QPushButton[instanceButton="true"] {
    font-size: 12px;
    padding: 5px 10px;
    min-height: 24px;
}

QFrame[instanceInfoCard="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #1D1712, stop: 1 #261C13
    );
    border-radius: 18px;
    border: 1px solid #3A2A1A;
}

QLabel[instanceInfoTitle="true"] {
    font-size: 16px;
    font-weight: 800;
    color: #F7E4C8;
}

QLabel[instanceInfoMeta="true"] {
    font-size: 14px;
    color: #A58E75;
}

QLabel[instanceInfoBody="true"] {
    font-size: 14px;
    color: #D5C3AB;
}

QLabel[instanceInfoImage="true"] {
    background-color: #1B140E;
    border: 1px solid #3A2A1A;
    border-radius: 12px;
}

/* === buttons === */
QPushButton {
    background-color: rgba(42, 30, 22, 0.72);
    color: #F3E7D6;
    border-radius: 12px;
    padding: 5px 10px;
    border: 1px solid rgba(74, 53, 35, 0.65);
    min-height: 24px;
}

QPushButton:hover {
    background-color: rgba(51, 36, 25, 0.82);
    border-color: rgba(233, 163, 68, 0.75);
}

QPushButton:pressed {
    background-color: rgba(58, 42, 29, 0.9);
}

QProgressBar {
    background-color: rgba(20, 14, 10, 0.92);
    color: #F7E4C8;
    border: 1px solid #3A2A1A;
    border-radius: 10px;
    text-align: center;
    min-height: 18px;
}

QProgressBar::chunk {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(245, 180, 73, 0.95),
        stop: 1 rgba(224, 118, 43, 0.95)
    );
    border-radius: 8px;
    margin: 1px;
}

QProgressBar[installerProgress="true"] {
    min-height: 24px;
    font-size: 13px;
    font-weight: 700;
}

QProgressBar[installerProgress="true"]::chunk {
    border-radius: 9px;
}

QPushButton[installerPrimary="true"] {
    min-height: 42px;
    font-size: 15px;
    font-weight: 800;
}

QPushButton[installerPrimary="true"]:disabled {
    background-color: rgba(72, 54, 39, 0.75);
    color: rgba(243, 231, 214, 0.65);
    border-color: rgba(110, 86, 62, 0.7);
}

QLabel[installerError="true"] {
    color: #F18A80;
    font-size: 13px;
}

QLabel[installerText="true"] {
    color: #D9C8B1;
    font-size: 14px;
    font-family: "Noto Sans", "Segoe UI", "Ubuntu", sans-serif;
}

QLabel[installerMeta="true"] {
    color: #A58E75;
    font-size: 13px;
    font-family: "Noto Sans", "Segoe UI", "Ubuntu", sans-serif;
}

QTextEdit[installerErrorBox="true"] {
    background-color: rgba(31, 18, 14, 0.96);
    color: #F3A59B;
    border: 1px solid rgba(239, 68, 68, 0.35);
    border-radius: 12px;
    padding: 8px 10px;
    selection-background-color: rgba(233, 163, 68, 0.45);
    selection-color: #FFF6E7;
    font-size: 13px;
    font-family: "Noto Sans Mono", "DejaVu Sans Mono", "Consolas", monospace;
}

QTextEdit[installerErrorBox="true"] QScrollBar:vertical {
    margin: 2px;
}

/* === primary (EMBER) === */
QPushButton[primary="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(245, 180, 73, 0.9), stop: 1 rgba(224, 118, 43, 0.9)
    );
    color: #1A120B;
    border: 1px solid rgba(240, 193, 107, 0.8);
    border-radius: 12px;
    padding: 6px 11px;
    font-weight: 800;
    min-height: 24px;
}

QPushButton[primary="true"]:hover {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(255, 208, 107, 0.95), stop: 1 rgba(240, 139, 62, 0.95)
    );
}

QPushButton[primary="true"]:pressed { background-color: #D86A23; }

/* === secondary (GRAY) === */
QPushButton[secondary="true"] {
    background-color: rgba(120, 120, 120, 0.55);
    color: rgba(245, 245, 245, 0.9);
    border: 1px solid rgba(170, 170, 170, 0.6);
    border-radius: 12px;
    padding: 6px 11px;
    font-weight: 700;
    min-height: 24px;
}

QPushButton[secondary="true"]:hover {
    background-color: rgba(140, 140, 140, 0.7);
}

QPushButton[secondary="true"][compact="true"] {
    border-radius: 10px;
    padding: 4px 8px;
    font-size: 14px;
    font-weight: 600;
    min-height: 20px;
}

/* === confirm (GREEN) === */
QPushButton[confirm="true"] {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(74, 222, 128, 0.92), stop: 1 rgba(22, 163, 74, 0.92)
    );
    color: #0F1A10;
    border: 1px solid rgba(22, 163, 74, 0.85);
    border-radius: 12px;
    padding: 6px 11px;
    font-weight: 800;
    min-height: 24px;
}

QPushButton[confirm="true"]:hover {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(110, 245, 170, 0.96), stop: 1 rgba(34, 197, 94, 0.96)
    );
}

QPushButton[confirm="true"]:disabled {
    background-color: rgba(120, 120, 120, 0.35);
    color: rgba(230, 230, 230, 0.6);
    border-color: rgba(160, 160, 160, 0.4);
}

QPushButton[settingsButton="true"] {
    padding: 5px 10px;
    min-height: 24px;
    font-size: 12px;
}

QPushButton[settingsSidebarButton="true"] {
    font-size: 12px;
    padding: 6px 10px;
    min-height: 26px;
}

QPushButton[primary="true"][settingsButton="true"],
QPushButton[secondary="true"][settingsButton="true"],
QPushButton[confirm="true"][settingsButton="true"] {
    padding: 5px 10px;
    min-height: 24px;
}

QPushButton[primary="true"][settingsSidebarButton="true"],
QPushButton[secondary="true"][settingsSidebarButton="true"],
QPushButton[confirm="true"][settingsSidebarButton="true"] {
    padding: 6px 10px;
    min-height: 26px;
}

QPushButton[authButton="true"] {
    padding: 6px 12px;
    min-height: 27px;
    font-size: 14px;
}

QPushButton[primary="true"][authButton="true"],
QPushButton[secondary="true"][authButton="true"],
QPushButton[confirm="true"][authButton="true"] {
    padding: 6px 12px;
    min-height: 27px;
}

QPushButton[authCompactButton="true"] {
    padding: 6px 12px;
    min-height: 28px;
    font-size: 14px;
}

QLineEdit[authField="true"] {
    font-size: 12px;
    padding: 5px 8px;
    min-height: 21px;
}

QPushButton[authPlatformButton="true"] {
    padding: 4px 8px;
    min-height: 18px;
    font-size: 12px;
}

QFrame[registerPanel="true"] QPushButton[registerService="telegram"][authPlatformButton="true"] {
    padding: 8px 12px;
    font-size: 12px;
    min-height: 24px;
}

QLineEdit[settingsField="true"],
QComboBox[settingsField="true"],
QSpinBox[settingsField="true"],
QDoubleSpinBox[settingsField="true"] {
    font-size: 12px;
    padding: 6px 10px;
    min-height: 24px;
}

QComboBox[settingsField="true"],
QSpinBox[settingsField="true"],
QDoubleSpinBox[settingsField="true"] {
    padding-right: 28px;
}

QCheckBox[settingsCheck="true"] {
    font-size: 12px;
    spacing: 6px;
}

QLabel[settingsCaption="true"] {
    font-size: 12px;
}

QGroupBox[settingsGroup="true"] {
    margin-top: 8px;
    padding: 10px;
}

QGroupBox[settingsGroup="true"]::title {
    left: 10px;
    padding: 0 4px;
    font-size: 12px;
}

/* === inputs === */
QLineEdit {
    background-color: #20170F;
    border: 1px solid #4A3523;
    border-radius: 12px;
    padding: 12px 14px;
    color: #F3E7D6;
    min-height: 44px;
}

QLineEdit:focus {
    border-color: #F5B449;
}

QTextEdit {
    background-color: #20170F;
    border: 1px solid #4A3523;
    border-radius: 12px;
    padding: 10px 12px;
    color: #F3E7D6;
}

QTextEdit:focus {
    border-color: #F5B449;
}

/* === combobox === */
QComboBox {
    background-color: #20170F;
    border: 1px solid #4A3523;
    border-radius: 12px;
    padding: 10px 34px 10px 14px;
    min-height: 44px;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    border-left: 1px solid #4A3523;
    background: transparent;
}

/* === spinbox === */
QSpinBox, QDoubleSpinBox {
    background-color: #20170F;
    border: 1px solid #4A3523;
    border-radius: 12px;
    padding: 10px 34px 10px 14px;
    min-height: 44px;
}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #2A1E16;
    border-left: 1px solid #4A3523;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: #332419;
}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url(__ARROW_UP__);
    width: 12px;
    height: 12px;
}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url(__ARROW_DOWN__);
    width: 12px;
    height: 12px;
}

/* === lists === */
QListWidget {
    background-color: #20170F;
    border: 1px solid #4A3523;
    border-radius: 14px;
    padding: 8px;
}

QListWidget::item {
    padding: 8px 10px;
    border-radius: 10px;
}

QListWidget::item:hover {
    background-color: #2A1E16;
}

QListWidget::item:selected {
    background-color: rgba(245, 180, 73, 0.18);
    border: 1px solid rgba(245, 180, 73, 0.45);
}

/* === groupboxes === */
QGroupBox {
    border: 1px solid #4A3523;
    border-radius: 16px;
    margin-top: 10px;
    padding: 12px;
    background-color: #20170F;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #CBB79E;
}
"""



APP_QSS = APP_QSS_TEMPLATE


def _qss_url(path: Path) -> str:
    return path.resolve().as_posix()


def build_app_qss(asset_dir: str) -> str:
    base = Path(asset_dir)
    qss = APP_QSS_TEMPLATE
    qss = qss.replace("__ARROW_UP__", _qss_url(base / "arrow_up.svg"))
    qss = qss.replace("__ARROW_DOWN__", _qss_url(base / "arrow_down.svg"))
    return qss
