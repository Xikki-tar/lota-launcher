import { invoke } from "@tauri-apps/api/core";

export const win = {
  close: () => invoke("close_window"),
  minimize: () => invoke("minimize_window"),
  toggleMaximize: () => invoke("toggle_maximize"),
  hideUntilGameExit: () => invoke("hide_until_game_exit"),
  show: () => invoke("show_window"),
};
