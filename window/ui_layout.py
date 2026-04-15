from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from auth.auth_storage import get_config_dir


FieldKind = Literal[
    "margins",
    "spacing",
    "fixed_width",
    "fixed_height",
    "text",
    "placeholder_text",
    "font_size",
]


@dataclass(frozen=True)
class LayoutField:
    key: str
    label: str
    target: str
    kind: FieldKind
    minimum: int = 0
    maximum: int = 640
    step: int = 1


SOURCE_DEFAULTS_PATH = Path(__file__).resolve().with_name("ui_layout_defaults.json")
RUNTIME_OVERRIDES_FILE = "ui_layout_overrides.json"
OFFSET_OVERRIDES_KEY = "__offsets__"


SCREEN_SPECS: dict[str, dict[str, Any]] = {
    "login": {
        "title": "Login",
        "preview_size": [480, 360],
        "fields": [
            LayoutField("card_width", "Card Width", "card", "fixed_width", 220, 420),
            LayoutField("card_height", "Card Height", "card", "fixed_height", 180, 320),
            LayoutField("root_margins", "Outer Margins", "root_layout", "margins", 0, 80),
            LayoutField("card_margins", "Card Margins", "card_layout", "margins", 0, 80),
            LayoutField("card_spacing", "Card Spacing", "card_layout", "spacing", 0, 48),
            LayoutField("title_text", "Title Text", "title_label", "text"),
            LayoutField("subtitle_text", "Subtitle Text", "subtitle_label", "text"),
            LayoutField("username_placeholder", "Username Placeholder", "username_input", "placeholder_text"),
            LayoutField("code_placeholder", "Password Placeholder", "code_input", "placeholder_text"),
            LayoutField("login_text", "Login Button Text", "login_button", "text"),
            LayoutField("register_text", "Register Button Text", "register_button", "text"),
            LayoutField("title_font_size", "Title Font Size", "title_label", "font_size", 8, 48),
            LayoutField("subtitle_font_size", "Subtitle Font Size", "subtitle_label", "font_size", 8, 32),
            LayoutField("username_width", "Username Width", "username_input", "fixed_width", 120, 360),
            LayoutField("username_height", "Username Height", "username_input", "fixed_height", 18, 80),
            LayoutField("code_width", "Password Width", "code_input", "fixed_width", 120, 360),
            LayoutField("code_height", "Password Height", "code_input", "fixed_height", 18, 80),
            LayoutField("login_width", "Login Button Width", "login_button", "fixed_width", 120, 360),
            LayoutField("login_height", "Login Button Height", "login_button", "fixed_height", 18, 80),
            LayoutField("register_width", "Register Button Width", "register_button", "fixed_width", 80, 320),
            LayoutField("register_height", "Register Button Height", "register_button", "fixed_height", 18, 80),
        ],
    },
    "register_overlay": {
        "title": "Register Overlay",
        "preview_size": [480, 360],
        "fields": [
            LayoutField("panel_width", "Panel Width", "panel", "fixed_width", 220, 460),
            LayoutField("overlay_margins", "Overlay Margins", "root_layout", "margins", 0, 80),
            LayoutField("panel_margins", "Panel Margins", "panel_layout", "margins", 0, 80),
            LayoutField("panel_spacing", "Panel Spacing", "panel_layout", "spacing", 0, 48),
            LayoutField("title_text", "Title Text", "title_label", "text"),
            LayoutField("subtitle_text", "Subtitle Text", "subtitle_label", "text"),
            LayoutField("error_text", "Error Text", "error_label", "text"),
            LayoutField("telegram_text", "Telegram Button Text", "telegram_button", "text"),
            LayoutField("open_text", "Open Link Button Text", "open_link_button", "text"),
            LayoutField("copy_text", "Copy Link Button Text", "copy_link_button", "text"),
            LayoutField("verified_text", "Verified Text", "verified_label", "text"),
            LayoutField("username_placeholder", "Username Placeholder", "username_input", "placeholder_text"),
            LayoutField("complete_text", "Complete Button Text", "complete_button", "text"),
            LayoutField("close_text", "Close Button Text", "close_button", "text"),
            LayoutField("title_font_size", "Title Font Size", "title_label", "font_size", 8, 48),
            LayoutField("close_width", "Close Button Width", "close_button", "fixed_width", 100, 360),
            LayoutField("close_height", "Close Button Height", "close_button", "fixed_height", 18, 80),
            LayoutField("telegram_width", "Telegram Button Width", "telegram_button", "fixed_width", 140, 360),
            LayoutField("telegram_height", "Telegram Button Height", "telegram_button", "fixed_height", 18, 80),
            LayoutField("open_width", "Open Link Button Width", "open_link_button", "fixed_width", 120, 360),
            LayoutField("open_height", "Open Link Button Height", "open_link_button", "fixed_height", 18, 80),
            LayoutField("copy_width", "Copy Link Button Width", "copy_link_button", "fixed_width", 120, 360),
            LayoutField("copy_height", "Copy Link Button Height", "copy_link_button", "fixed_height", 18, 80),
            LayoutField("username_width", "Username Field Width", "username_input", "fixed_width", 120, 360),
            LayoutField("username_height", "Username Field Height", "username_input", "fixed_height", 18, 80),
            LayoutField("complete_width", "Complete Button Width", "complete_button", "fixed_width", 120, 360),
            LayoutField("complete_height", "Complete Button Height", "complete_button", "fixed_height", 18, 80),
        ],
    },
    "home": {
        "title": "Home",
        "preview_size": [960, 640],
        "fields": [
            LayoutField("root_margins", "Root Margins", "root_layout", "margins", 0, 80),
            LayoutField("root_spacing", "Root Spacing", "root_layout", "spacing", 0, 64),
            LayoutField("content_width", "Content Panel Width", "content_panel", "fixed_width", 300, 900),
            LayoutField("content_margins", "Content Margins", "content_layout", "margins", 0, 80),
            LayoutField("content_spacing", "Content Spacing", "content_layout", "spacing", 0, 48),
            LayoutField("news_scroll_height", "News Area Height", "news_scroll", "fixed_height", 120, 520),
            LayoutField("news_spacing", "News Card Spacing", "news_box", "spacing", 0, 48),
            LayoutField("sidebar_width", "Sidebar Width", "sidebar", "fixed_width", 160, 420),
            LayoutField("sidebar_margins", "Sidebar Margins", "sidebar_layout", "margins", 0, 60),
            LayoutField("sidebar_spacing", "Sidebar Spacing", "sidebar_layout", "spacing", 0, 48),
            LayoutField("header_width", "Sidebar Header Width", "header_label", "fixed_width", 80, 220),
            LayoutField("header_height", "Sidebar Header Height", "header_label", "fixed_height", 12, 80),
            LayoutField("profile_margins", "Profile Card Margins", "profile_layout", "margins", 0, 40),
            LayoutField("profile_spacing", "Profile Card Spacing", "profile_layout", "spacing", 0, 32),
            LayoutField("title_text", "Title Text", "title_label", "text"),
            LayoutField("news_title_text", "News Title Text", "news_title", "text"),
            LayoutField("header_text", "Sidebar Header Text", "header_label", "text"),
            LayoutField("play_text", "Play Button Text", "btn_play", "text"),
            LayoutField("account_text", "Account Button Text", "btn_account", "text"),
            LayoutField("library_text", "Library Button Text", "btn_library", "text"),
            LayoutField("settings_text", "Settings Button Text", "btn_settings", "text"),
            LayoutField("exit_text", "Exit Button Text", "btn_exit", "text"),
            LayoutField("play_status_text", "Play Status Text", "play_status", "text"),
            LayoutField("username_text", "Username Text", "username_label", "text"),
            LayoutField("title_font_size", "Title Font Size", "title_label", "font_size", 8, 48),
            LayoutField("title_width", "Title Width", "title_label", "fixed_width", 120, 520),
            LayoutField("title_height", "Title Height", "title_label", "fixed_height", 18, 80),
            LayoutField("news_title_width", "News Label Width", "news_title", "fixed_width", 80, 240),
            LayoutField("news_title_height", "News Label Height", "news_title", "fixed_height", 12, 60),
            LayoutField("play_width", "Play Button Width", "btn_play", "fixed_width", 120, 320),
            LayoutField("play_height", "Play Button Height", "btn_play", "fixed_height", 18, 96),
            LayoutField("account_width", "Account Button Width", "btn_account", "fixed_width", 120, 320),
            LayoutField("account_height", "Account Button Height", "btn_account", "fixed_height", 18, 96),
            LayoutField("library_width", "Library Button Width", "btn_library", "fixed_width", 120, 320),
            LayoutField("library_height", "Library Button Height", "btn_library", "fixed_height", 18, 96),
            LayoutField("settings_width", "Settings Button Width", "btn_settings", "fixed_width", 120, 320),
            LayoutField("settings_height", "Settings Button Height", "btn_settings", "fixed_height", 18, 96),
            LayoutField("profile_width", "Profile Card Width", "profile_card", "fixed_width", 120, 320),
            LayoutField("profile_height", "Profile Card Height", "profile_card", "fixed_height", 28, 120),
            LayoutField("exit_width", "Exit Button Width", "btn_exit", "fixed_width", 120, 320),
            LayoutField("exit_height", "Exit Button Height", "btn_exit", "fixed_height", 18, 96),
        ],
    },
    "news_overlay": {
        "title": "News Overlay",
        "preview_size": [960, 640],
        "fields": [
            LayoutField("overlay_margins", "Overlay Margins", "root_layout", "margins", 0, 80),
            LayoutField("panel_width", "Panel Width", "panel", "fixed_width", 220, 720),
            LayoutField("panel_height", "Panel Height", "panel", "fixed_height", 160, 420),
            LayoutField("panel_margins", "Panel Margins", "panel_layout", "margins", 0, 80),
            LayoutField("panel_spacing", "Panel Spacing", "panel_layout", "spacing", 0, 48),
            LayoutField("title_font_size", "Title Font Size", "title_label", "font_size", 8, 40),
            LayoutField("title_text", "Title Text", "title_label", "text"),
            LayoutField("date_text", "Date Text", "date_label", "text"),
            LayoutField("body_text", "Body Text", "body_label", "text"),
            LayoutField("changes_title_text", "Changes Title Text", "changes_title", "text"),
            LayoutField("changes_text", "Changes Text", "changes_label", "text"),
            LayoutField("close_width", "Close Button Width", "close_btn", "fixed_width", 70, 220),
            LayoutField("close_height", "Close Button Height", "close_btn", "fixed_height", 18, 80),
            LayoutField("close_text", "Close Button Text", "close_btn", "text"),
        ],
    },
    "settings": {
        "title": "Settings",
        "preview_size": [960, 640],
        "fields": [
            LayoutField("root_margins", "Root Margins", "root_layout", "margins", 0, 80),
            LayoutField("root_spacing", "Root Spacing", "root_layout", "spacing", 0, 64),
            LayoutField("left_margins", "Left Panel Margins", "left_layout", "margins", 0, 80),
            LayoutField("left_spacing", "Left Panel Spacing", "left_layout", "spacing", 0, 48),
            LayoutField("title_width", "Title Width", "title_label", "fixed_width", 120, 520),
            LayoutField("title_height", "Title Height", "title_label", "fixed_height", 18, 80),
            LayoutField("java_spacing", "Java Section Spacing", "java_layout", "spacing", 0, 32),
            LayoutField("lang_width", "Language Box Width", "gb_lang", "fixed_width", 160, 680),
            LayoutField("java_group_width", "Java Group Width", "gb_java", "fixed_width", 200, 680),
            LayoutField("java_list_height", "Java List Height", "java_list", "fixed_height", 80, 300),
            LayoutField("sidebar_width", "Sidebar Width", "sidebar", "fixed_width", 160, 420),
            LayoutField("sidebar_margins", "Sidebar Margins", "sidebar_layout", "margins", 0, 60),
            LayoutField("sidebar_spacing", "Sidebar Spacing", "sidebar_layout", "spacing", 0, 48),
            LayoutField("title_text", "Title Text", "title_label", "text"),
            LayoutField("lang_group_text", "Language Group Title", "gb_lang", "text"),
            LayoutField("java_group_text", "Java Group Title", "gb_java", "text"),
            LayoutField("min_mem_text", "Min Memory Label", "mem_min_label", "text"),
            LayoutField("max_mem_text", "Max Memory Label", "mem_max_label", "text"),
            LayoutField("java_path_placeholder", "Java Path Placeholder", "java_path_edit", "placeholder_text"),
            LayoutField("browse_text", "Browse Button Text", "btn_browse", "text"),
            LayoutField("auto_text", "Auto Button Text", "btn_auto", "text"),
            LayoutField("auto_java_text", "Auto Java Checkbox Text", "auto_java_version", "text"),
            LayoutField("java_selected_text", "Java Selected Text", "java_selected_info", "text"),
            LayoutField("java_recommended_text", "Java Recommended Text", "java_recommended", "text"),
            LayoutField("jvm_args_text", "JVM Args Label", "jvm_args_label", "text"),
            LayoutField("jvm_args_placeholder", "JVM Args Placeholder", "jvm_args_edit", "placeholder_text"),
            LayoutField("disable_openal_text", "Disable OpenAL Text", "disable_openal", "text"),
            LayoutField("themes_text", "Themes Button Text", "btn_themes", "text"),
            LayoutField("save_text", "Save Button Text", "btn_save", "text"),
            LayoutField("back_text", "Back Button Text", "btn_back", "text"),
            LayoutField("title_font_size", "Title Font Size", "title_label", "font_size", 8, 48),
            LayoutField("browse_width", "Browse Button Width", "btn_browse", "fixed_width", 80, 220),
            LayoutField("browse_height", "Browse Button Height", "btn_browse", "fixed_height", 18, 80),
            LayoutField("auto_width", "Auto Button Width", "btn_auto", "fixed_width", 80, 220),
            LayoutField("auto_height", "Auto Button Height", "btn_auto", "fixed_height", 18, 80),
            LayoutField("themes_width", "Themes Button Width", "btn_themes", "fixed_width", 120, 320),
            LayoutField("themes_height", "Themes Button Height", "btn_themes", "fixed_height", 18, 96),
            LayoutField("save_width", "Save Button Width", "btn_save", "fixed_width", 120, 320),
            LayoutField("save_height", "Save Button Height", "btn_save", "fixed_height", 18, 96),
            LayoutField("back_width", "Back Button Width", "btn_back", "fixed_width", 120, 320),
            LayoutField("back_height", "Back Button Height", "btn_back", "fixed_height", 18, 96),
            LayoutField("java_path_width", "Java Path Field Width", "java_path_edit", "fixed_width", 180, 620),
            LayoutField("java_path_height", "Java Path Field Height", "java_path_edit", "fixed_height", 18, 80),
            LayoutField("jvm_args_width", "JVM Args Field Width", "jvm_args_edit", "fixed_width", 180, 620),
            LayoutField("jvm_args_height", "JVM Args Field Height", "jvm_args_edit", "fixed_height", 18, 80),
        ],
    },
    "library": {
        "title": "Library",
        "preview_size": [960, 640],
        "fields": [
            LayoutField("root_margins", "Root Margins", "root_layout", "margins", 0, 80),
            LayoutField("root_spacing", "Root Spacing", "root_layout", "spacing", 0, 64),
            LayoutField("left_margins", "Left Panel Margins", "left_layout", "margins", 0, 80),
            LayoutField("left_spacing", "Left Panel Spacing", "left_layout", "spacing", 0, 48),
            LayoutField("title_width", "Title Width", "title_label", "fixed_width", 120, 520),
            LayoutField("title_height", "Title Height", "title_label", "fixed_height", 18, 80),
            LayoutField("info_section_width", "Info Label Width", "info_section", "fixed_width", 80, 240),
            LayoutField("info_section_height", "Info Label Height", "info_section", "fixed_height", 12, 60),
            LayoutField("info_card_width", "Info Card Width", "info_card", "fixed_width", 240, 720),
            LayoutField("info_card_height", "Info Card Height", "info_card", "fixed_height", 120, 440),
            LayoutField("sidebar_width", "Sidebar Width", "sidebar", "fixed_width", 160, 420),
            LayoutField("sidebar_margins", "Sidebar Margins", "sidebar_layout", "margins", 0, 60),
            LayoutField("sidebar_spacing", "Sidebar Spacing", "sidebar_layout", "spacing", 0, 48),
            LayoutField("section_width", "Sidebar Label Width", "section_label", "fixed_width", 80, 220),
            LayoutField("section_height", "Sidebar Label Height", "section_label", "fixed_height", 12, 60),
            LayoutField("builds_width", "Build List Width", "builds_list", "fixed_width", 120, 320),
            LayoutField("builds_height", "Build List Height", "builds_list", "fixed_height", 120, 520),
            LayoutField("builds_spacing", "Build List Spacing", "builds_list", "spacing", 0, 24),
            LayoutField("download_status_width", "Download Status Width", "download_status", "fixed_width", 100, 320),
            LayoutField("download_status_height", "Download Status Height", "download_status", "fixed_height", 12, 100),
            LayoutField("download_progress_width", "Download Bar Width", "download_progress", "fixed_width", 100, 320),
            LayoutField("download_progress_height", "Download Bar Height", "download_progress", "fixed_height", 12, 60),
            LayoutField("add_button_height", "Add Button Height", "add_instance_btn", "fixed_height", 32, 120),
            LayoutField("title_text", "Title Text", "title_label", "text"),
            LayoutField("info_section_text", "Info Section Text", "info_section", "text"),
            LayoutField("section_text", "Sidebar Section Text", "section_label", "text"),
            LayoutField("add_text", "Add Button Text", "add_instance_btn", "text"),
            LayoutField("edit_text", "Edit Button Text", "edit_instance_btn", "text"),
            LayoutField("open_folder_text", "Open Folder Text", "open_build_dir_btn", "text"),
            LayoutField("info_action_text", "Info Action Text", "info_action", "text"),
            LayoutField("back_text", "Back Button Text", "btn_back", "text"),
            LayoutField("download_status_text", "Download Status Text", "download_status", "text"),
            LayoutField("cancel_download_text", "Cancel Download Text", "download_cancel_btn", "text"),
            LayoutField("info_card_title_text", "Info Card Title", "info_card.title_label", "text"),
            LayoutField("info_card_version_text", "Info Card Version", "info_card.version_label", "text"),
            LayoutField("info_card_body_text", "Info Card Body", "info_card.body_label", "text"),
            LayoutField("title_font_size", "Title Font Size", "title_label", "font_size", 8, 48),
            LayoutField("add_button_width", "Add Button Width", "add_instance_btn", "fixed_width", 120, 320),
            LayoutField("edit_width", "Edit Button Width", "edit_instance_btn", "fixed_width", 100, 320),
            LayoutField("edit_height", "Edit Button Height", "edit_instance_btn", "fixed_height", 18, 96),
            LayoutField("open_folder_width", "Open Folder Button Width", "open_build_dir_btn", "fixed_width", 100, 320),
            LayoutField("open_folder_height", "Open Folder Button Height", "open_build_dir_btn", "fixed_height", 18, 96),
            LayoutField("info_action_width", "Info Action Width", "info_action", "fixed_width", 100, 320),
            LayoutField("info_action_height", "Info Action Height", "info_action", "fixed_height", 18, 96),
            LayoutField("back_width", "Back Button Width", "btn_back", "fixed_width", 100, 320),
            LayoutField("back_height", "Back Button Height", "btn_back", "fixed_height", 18, 96),
            LayoutField("cancel_download_width", "Cancel Download Width", "download_cancel_btn", "fixed_width", 100, 320),
            LayoutField("cancel_download_height", "Cancel Download Height", "download_cancel_btn", "fixed_height", 18, 96),
        ],
    },
    "instance_overlay": {
        "title": "Instance Overlay",
        "preview_size": [960, 640],
        "fields": [
            LayoutField("overlay_margins", "Overlay Margins", "root_layout", "margins", 0, 80),
            LayoutField("panel_width", "Panel Width", "panel", "fixed_width", 260, 720),
            LayoutField("panel_height", "Panel Height", "panel", "fixed_height", 220, 560),
            LayoutField("panel_margins", "Panel Margins", "panel_layout", "margins", 0, 80),
            LayoutField("panel_spacing", "Panel Spacing", "panel_layout", "spacing", 0, 48),
            LayoutField("title_text", "Title Text", "title_label", "text"),
            LayoutField("subtitle_text", "Subtitle Text", "subtitle_label", "text"),
            LayoutField("name_label_text", "Name Label Text", "name_label", "text"),
            LayoutField("desc_label_text", "Description Label Text", "desc_label", "text"),
            LayoutField("image_label_text", "Image Label Text", "image_label", "text"),
            LayoutField("build_label_text", "Build Label Text", "build_label", "text"),
            LayoutField("dlc_label_text", "DLC Label Text", "dlc_label", "text"),
            LayoutField("browse_text", "Browse Button Text", "image_browse", "text"),
            LayoutField("cancel_text", "Cancel Button Text", "cancel_btn", "text"),
            LayoutField("delete_text", "Delete Button Text", "delete_btn", "text"),
            LayoutField("create_text", "Create Button Text", "create_btn", "text"),
            LayoutField("title_font_size", "Title Font Size", "title_label", "font_size", 8, 40),
            LayoutField("name_width", "Name Field Width", "name_input", "fixed_width", 140, 480),
            LayoutField("name_height", "Name Field Height", "name_input", "fixed_height", 18, 80),
            LayoutField("desc_width", "Description Width", "desc_input", "fixed_width", 160, 520),
            LayoutField("desc_height", "Description Height", "desc_input", "fixed_height", 48, 220),
            LayoutField("image_path_width", "Image Path Width", "image_input", "fixed_width", 100, 420),
            LayoutField("image_path_height", "Image Path Height", "image_input", "fixed_height", 18, 80),
            LayoutField("browse_width", "Browse Button Width", "image_browse", "fixed_width", 60, 220),
            LayoutField("browse_height", "Browse Button Height", "image_browse", "fixed_height", 18, 80),
            LayoutField("build_width", "Build Combo Width", "build_combo", "fixed_width", 140, 420),
            LayoutField("build_height", "Build Combo Height", "build_combo", "fixed_height", 18, 80),
            LayoutField("dlc_width", "DLC List Width", "dlc_list", "fixed_width", 160, 520),
            LayoutField("dlc_height", "DLC List Height", "dlc_list", "fixed_height", 60, 260),
            LayoutField("cancel_width", "Cancel Button Width", "cancel_btn", "fixed_width", 80, 220),
            LayoutField("cancel_height", "Cancel Button Height", "cancel_btn", "fixed_height", 18, 80),
            LayoutField("delete_width", "Delete Button Width", "delete_btn", "fixed_width", 80, 220),
            LayoutField("delete_height", "Delete Button Height", "delete_btn", "fixed_height", 18, 80),
            LayoutField("create_width", "Create Button Width", "create_btn", "fixed_width", 80, 220),
            LayoutField("create_height", "Create Button Height", "create_btn", "fixed_height", 18, 80),
        ],
    },
    "account": {
        "title": "Account",
        "preview_size": [960, 640],
        "fields": [
            LayoutField("root_margins", "Root Margins", "root_layout", "margins", 0, 80),
            LayoutField("root_spacing", "Root Spacing", "root_layout", "spacing", 0, 64),
            LayoutField("left_margins", "Left Panel Margins", "left_layout", "margins", 0, 80),
            LayoutField("left_spacing", "Left Panel Spacing", "left_layout", "spacing", 0, 48),
            LayoutField("profile_width", "Profile Panel Width", "left_panel", "fixed_width", 180, 420),
            LayoutField("center_margins", "Center Panel Margins", "center_layout", "margins", 0, 80),
            LayoutField("center_width", "Center Panel Width", "center_panel", "fixed_width", 180, 420),
            LayoutField("sidebar_width", "Sidebar Width", "sidebar", "fixed_width", 160, 420),
            LayoutField("sidebar_margins", "Sidebar Margins", "sidebar_layout", "margins", 0, 60),
            LayoutField("sidebar_spacing", "Sidebar Spacing", "sidebar_layout", "spacing", 0, 48),
            LayoutField("profile_label_width", "Profile Label Width", "profile_label", "fixed_width", 80, 220),
            LayoutField("profile_label_height", "Profile Label Height", "profile_label", "fixed_height", 12, 60),
            LayoutField("nick_value_width", "Nickname Value Width", "nick_label", "fixed_width", 120, 320),
            LayoutField("nick_value_height", "Nickname Value Height", "nick_label", "fixed_height", 18, 120),
            LayoutField("rank_value_width", "Rank Value Width", "rank_label", "fixed_width", 120, 320),
            LayoutField("rank_value_height", "Rank Value Height", "rank_label", "fixed_height", 18, 120),
            LayoutField("updates_badge_width", "Status Badge Width", "updates_badge", "fixed_width", 80, 240),
            LayoutField("updates_badge_height", "Status Badge Height", "updates_badge", "fixed_height", 18, 80),
            LayoutField("skin_label_width", "Skin Label Width", "label_skin", "fixed_width", 80, 220),
            LayoutField("skin_label_height", "Skin Label Height", "label_skin", "fixed_height", 12, 60),
            LayoutField("skin_viewer_width", "Skin Viewer Width", "skin_viewer", "fixed_width", 180, 420),
            LayoutField("skin_viewer_height", "Skin Viewer Height", "skin_viewer", "fixed_height", 220, 520),
            LayoutField("section_width", "Sidebar Label Width", "section_label", "fixed_width", 80, 220),
            LayoutField("section_height", "Sidebar Label Height", "section_label", "fixed_height", 12, 60),
            LayoutField("discord_height", "Discord Button Height", "btn_link_discord", "fixed_height", 32, 120),
            LayoutField("back_height", "Back Button Height", "btn_back", "fixed_height", 28, 100),
            LayoutField("profile_text", "Profile Section Text", "profile_label", "text"),
            LayoutField("nick_caption_text", "Nick Caption Text", "nick_caption", "text"),
            LayoutField("rank_caption_text", "Rank Caption Text", "rank_caption", "text"),
            LayoutField("updates_caption_text", "Updates Caption Text", "updates_caption", "text"),
            LayoutField("nick_value_text", "Nickname Value Text", "nick_label", "text"),
            LayoutField("rank_value_text", "Rank Value Text", "rank_label", "text"),
            LayoutField("updates_badge_text", "Status Badge Text", "updates_badge", "text"),
            LayoutField("skin_text", "Skin Section Text", "label_skin", "text"),
            LayoutField("section_text", "Sidebar Section Text", "section_label", "text"),
            LayoutField("change_skin_text", "Change Skin Button Text", "btn_change_skin", "text"),
            LayoutField("discord_text", "Discord Button Text", "btn_link_discord", "text"),
            LayoutField("back_text", "Back Button Text", "btn_back", "text"),
            LayoutField("profile_font_size", "Profile Font Size", "profile_label", "font_size", 8, 40),
            LayoutField("change_skin_width", "Change Skin Width", "btn_change_skin", "fixed_width", 120, 320),
            LayoutField("change_skin_height", "Change Skin Height", "btn_change_skin", "fixed_height", 18, 96),
            LayoutField("discord_width", "Discord Button Width", "btn_link_discord", "fixed_width", 120, 320),
            LayoutField("back_width", "Back Button Width", "btn_back", "fixed_width", 120, 320),
        ],
    },
    "discord_dialog": {
        "title": "Discord Dialog",
        "preview_size": [560, 320],
        "fields": [
            LayoutField("card_width", "Card Width", "card", "fixed_width", 220, 520),
            LayoutField("card_height", "Card Height", "card", "fixed_height", 160, 300),
            LayoutField("root_margins", "Root Margins", "root_layout", "margins", 0, 60),
            LayoutField("card_margins", "Card Margins", "card_layout", "margins", 0, 60),
            LayoutField("card_spacing", "Card Spacing", "card_layout", "spacing", 0, 40),
            LayoutField("info_text", "Info Text", "info_label", "text"),
            LayoutField("command_text", "Command Text", "command_label", "text"),
            LayoutField("open_text", "Open Button Text", "open_button", "text"),
            LayoutField("copy_text", "Copy Button Text", "copy_button", "text"),
            LayoutField("close_text", "Close Button Text", "close_button", "text"),
            LayoutField("info_width", "Info Width", "info_label", "fixed_width", 120, 480),
            LayoutField("info_height", "Info Height", "info_label", "fixed_height", 18, 100),
            LayoutField("command_width", "Command Width", "command_label", "fixed_width", 120, 480),
            LayoutField("command_height", "Command Height", "command_label", "fixed_height", 24, 120),
            LayoutField("open_width", "Open Button Width", "open_button", "fixed_width", 120, 420),
            LayoutField("open_height", "Open Button Height", "open_button", "fixed_height", 18, 96),
            LayoutField("copy_width", "Copy Button Width", "copy_button", "fixed_width", 120, 420),
            LayoutField("copy_height", "Copy Button Height", "copy_button", "fixed_height", 18, 96),
            LayoutField("close_width", "Close Button Width", "close_button", "fixed_width", 120, 420),
            LayoutField("close_height", "Close Button Height", "close_button", "fixed_height", 18, 96),
        ],
    },
}


FALLBACK_DEFAULTS: dict[str, dict[str, Any]] = {
    "login": {
        "card_width": 384,
        "root_margins": [24, 20, 24, 20],
        "card_margins": [22, 20, 22, 18],
        "card_spacing": 8,
        "title_font_size": 24,
        "subtitle_font_size": 13,
        "username_height": 30,
        "code_height": 30,
        "login_height": 38,
        "register_height": 30,
    },
    "register_overlay": {
        "panel_width": 400,
        "overlay_margins": [20, 20, 20, 20],
        "panel_margins": [18, 18, 18, 16],
        "panel_spacing": 8,
        "title_font_size": 22,
        "username_height": 30,
        "complete_width": 340,
        "complete_height": 38,
        "close_width": 340,
        "close_height": 34,
    },
    "home": {
        "root_margins": [24, 24, 24, 24],
        "root_spacing": 20,
        "content_margins": [24, 24, 24, 24],
        "content_spacing": 16,
        "news_spacing": 16,
        "sidebar_width": 240,
        "sidebar_margins": [18, 20, 18, 18],
        "sidebar_spacing": 14,
        "profile_margins": [10, 8, 10, 8],
        "profile_spacing": 10,
    },
    "settings": {
        "root_margins": [24, 24, 24, 24],
        "root_spacing": 20,
        "left_margins": [24, 24, 24, 24],
        "left_spacing": 14,
        "java_spacing": 8,
        "java_list_height": 140,
        "sidebar_width": 240,
        "sidebar_margins": [18, 20, 18, 18],
        "sidebar_spacing": 12,
    },
    "library": {
        "root_margins": [24, 24, 24, 24],
        "root_spacing": 20,
        "left_margins": [24, 24, 24, 24],
        "left_spacing": 16,
        "sidebar_width": 240,
        "sidebar_margins": [6, 14, 12, 12],
        "sidebar_spacing": 12,
        "builds_spacing": 6,
        "add_button_height": 56,
    },
    "instance_overlay": {
        "overlay_margins": [28, 28, 28, 28],
        "panel_width": 760,
        "panel_margins": [18, 16, 18, 16],
        "panel_spacing": 6,
        "title_font_size": 18,
        "name_height": 30,
        "desc_height": 76,
        "image_path_height": 30,
        "browse_width": 120,
        "browse_height": 30,
        "build_height": 30,
        "dlc_height": 78,
        "cancel_width": 90,
        "cancel_height": 32,
        "delete_width": 110,
        "delete_height": 32,
        "create_width": 130,
        "create_height": 32,
    },
    "account": {
        "root_margins": [24, 24, 24, 24],
        "root_spacing": 20,
        "left_margins": [22, 22, 22, 22],
        "left_spacing": 10,
        "center_margins": [40, 24, 40, 24],
        "sidebar_width": 240,
        "sidebar_margins": [18, 20, 18, 20],
        "sidebar_spacing": 14,
        "discord_height": 56,
        "back_height": 38,
    },
}


def runtime_overrides_path() -> Path:
    return get_config_dir() / RUNTIME_OVERRIDES_FILE


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return data if isinstance(data, dict) else fallback


def load_source_defaults() -> dict[str, dict[str, Any]]:
    data = _read_json(SOURCE_DEFAULTS_PATH, FALLBACK_DEFAULTS)
    return _normalize_layout_map(data, FALLBACK_DEFAULTS)


def save_source_defaults(data: dict[str, dict[str, Any]]) -> Path:
    normalized = _normalize_layout_map(data, FALLBACK_DEFAULTS)
    SOURCE_DEFAULTS_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return SOURCE_DEFAULTS_PATH


def load_runtime_overrides() -> dict[str, dict[str, Any]]:
    data = _read_json(runtime_overrides_path(), {})
    return _normalize_layout_map(data, {})


def save_runtime_overrides(data: dict[str, dict[str, Any]]) -> Path:
    normalized = _normalize_layout_map(data, {})
    path = runtime_overrides_path()
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def clear_runtime_overrides(screen_key: str | None = None) -> Path:
    data = load_runtime_overrides()
    if screen_key is None:
        data = {}
    else:
        data.pop(screen_key, None)
    return save_runtime_overrides(data)


def merged_screen_values(screen_key: str, overrides: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    source = load_source_defaults().get(screen_key, {})
    runtime = (overrides or load_runtime_overrides()).get(screen_key, {})
    merged = dict(source)
    merged.update(runtime)
    return merged


def effective_layout_map(overrides: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    return {screen_key: merged_screen_values(screen_key, overrides) for screen_key in SCREEN_SPECS}


def iter_fields(screen_key: str) -> list[LayoutField]:
    spec = SCREEN_SPECS.get(screen_key) or {}
    return list(spec.get("fields") or [])


def apply_layout_overrides(root: Any, screen_key: str, overrides: dict[str, dict[str, Any]] | None = None) -> None:
    values = merged_screen_values(screen_key, overrides)
    for field in iter_fields(screen_key):
        if field.key not in values:
            continue
        target = _resolve_target(root, field.target)
        if target is None:
            continue
        _apply_value(target, field.kind, values[field.key])
    for target_path, offset in _load_offsets(values).items():
        target = _resolve_target(root, target_path)
        if target is not None:
            _apply_widget_offset(target, offset)


def offset_for_target(screen_key: str, target_path: str, overrides: dict[str, dict[str, Any]] | None = None) -> tuple[int, int]:
    values = merged_screen_values(screen_key, overrides)
    offset = _load_offsets(values).get(target_path) or {"x": 0, "y": 0}
    return _normalize_int(offset.get("x"), 0), _normalize_int(offset.get("y"), 0)


def set_target_offset(
    overrides: dict[str, dict[str, Any]],
    screen_key: str,
    target_path: str,
    *,
    x: int | None = None,
    y: int | None = None,
) -> None:
    screen = overrides.setdefault(screen_key, {})
    offsets = screen.setdefault(OFFSET_OVERRIDES_KEY, {})
    entry = offsets.setdefault(target_path, {"x": 0, "y": 0})
    if x is not None:
        entry["x"] = int(x)
    if y is not None:
        entry["y"] = int(y)
    if not entry.get("x") and not entry.get("y"):
        offsets.pop(target_path, None)
    if not offsets:
        screen.pop(OFFSET_OVERRIDES_KEY, None)


def read_field_value(root: Any, field: LayoutField) -> Any | None:
    target = _resolve_target(root, field.target)
    if target is None:
        return None
    if field.kind == "margins":
        margins = target.contentsMargins()
        return [margins.left(), margins.top(), margins.right(), margins.bottom()]
    if field.kind == "spacing":
        return int(target.spacing())
    if field.kind == "fixed_width":
        return int(target.width())
    if field.kind == "fixed_height":
        return int(target.height())
    if field.kind == "text":
        getter = getattr(target, "text", None)
        if not callable(getter):
            getter = getattr(target, "title", None)
        return getter() if callable(getter) else None
    if field.kind == "placeholder_text":
        getter = getattr(target, "placeholderText", None)
        return getter() if callable(getter) else None
    if field.kind == "font_size":
        return int(target.font().pixelSize() or target.font().pointSize() or 0)
    return None


def _resolve_target(root: Any, target_path: str) -> Any | None:
    current = root
    for chunk in target_path.split("."):
        current = getattr(current, chunk, None)
        if current is None:
            return None
    return current


def _apply_value(target: Any, kind: FieldKind, value: Any) -> None:
    if kind == "margins":
        parts = _normalize_margins(value)
        if parts is not None:
            target.setContentsMargins(*parts)
        return
    if kind == "spacing":
        target.setSpacing(_normalize_int(value, fallback=0))
        return
    if kind == "fixed_width":
        target.setFixedWidth(_normalize_int(value, fallback=0))
        return
    if kind == "fixed_height":
        target.setFixedHeight(_normalize_int(value, fallback=0))
        return
    if kind == "text":
        setter = getattr(target, "setText", None)
        if not callable(setter):
            setter = getattr(target, "setTitle", None)
        if callable(setter):
            setter(str(value))
        return
    if kind == "placeholder_text":
        setter = getattr(target, "setPlaceholderText", None)
        if callable(setter):
            setter(str(value))
        return
    if kind == "font_size":
        size = _normalize_int(value, fallback=0)
        if size > 0:
            font = target.font()
            font.setPixelSize(size)
            target.setFont(font)


def _load_offsets(values: dict[str, Any]) -> dict[str, dict[str, int]]:
    raw = values.get(OFFSET_OVERRIDES_KEY)
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, int]] = {}
    for target_path, offset in raw.items():
        if not isinstance(target_path, str) or not isinstance(offset, dict):
            continue
        normalized[target_path] = {
            "x": _normalize_int(offset.get("x"), 0),
            "y": _normalize_int(offset.get("y"), 0),
        }
    return normalized


def _apply_widget_offset(target: Any, offset: dict[str, int]) -> None:
    if not hasattr(target, "setStyleSheet"):
        return
    x = _normalize_int(offset.get("x"), 0)
    y = _normalize_int(offset.get("y"), 0)
    if x == 0 and y == 0:
        css = ""
    else:
        css = (
            f"margin-left: {x}px;"
            f" margin-right: {-x}px;"
            f" margin-top: {y}px;"
            f" margin-bottom: {-y}px;"
        )
    _replace_style_block(target, "codex-offset", css)


def _replace_style_block(target: Any, block_name: str, css: str) -> None:
    start = f"/* {block_name}:start */"
    end = f"/* {block_name}:end */"
    current = str(target.styleSheet() or "")
    while start in current and end in current:
        left = current.find(start)
        right = current.find(end, left)
        if right == -1:
            break
        current = (current[:left] + current[right + len(end):]).strip()
    if css:
        current = (current + "\n" + start + "\n" + css + "\n" + end).strip()
    target.setStyleSheet(current)


def _normalize_layout_map(data: dict[str, Any], fallback: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for screen_key, values in fallback.items():
        normalized[screen_key] = dict(values)
    for screen_key, values in data.items():
        if not isinstance(values, dict):
            continue
        normalized.setdefault(screen_key, {})
        for field in iter_fields(screen_key):
            if field.key not in values:
                continue
            raw_value = values[field.key]
            if field.kind == "margins":
                parts = _normalize_margins(raw_value)
                if parts is not None:
                    normalized[screen_key][field.key] = parts
            elif field.kind in {"text", "placeholder_text"}:
                normalized[screen_key][field.key] = str(raw_value)
            else:
                normalized[screen_key][field.key] = _normalize_int(raw_value, fallback=0)
        offsets = values.get(OFFSET_OVERRIDES_KEY)
        if isinstance(offsets, dict):
            cleaned = _load_offsets({OFFSET_OVERRIDES_KEY: offsets})
            if cleaned:
                normalized[screen_key][OFFSET_OVERRIDES_KEY] = cleaned
    return normalized


def _normalize_margins(value: Any) -> list[int] | None:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return [_normalize_int(part, fallback=0) for part in value]
    return None


def _normalize_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
