import { invoke } from "@tauri-apps/api/core";

export const win = {
  close: () => invoke("close_window"),
  minimize: () => invoke("minimize_window"),
  toggleMaximize: () => invoke("toggle_maximize"),
  hide: () => invoke("hide_window"),
  show: () => invoke("show_window"),
};
