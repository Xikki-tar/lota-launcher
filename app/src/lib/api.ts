import { invoke } from "@tauri-apps/api/core";

export interface AuthData {
  token: string;
  username: string;
  status: string;
  sub_level: number;
  player_uuid: string;
}

export interface RegisterLink {
  link_token: string;
  telegram_url: string;
}

export interface ApiResult {
  ok: boolean;
  status: number;
  data: Record<string, unknown>;
}

export const auth = {
  load: () => invoke<AuthData | null>("auth_load"),
  save: (d: AuthData) =>
    invoke("auth_save", {
      token: d.token,
      username: d.username,
      status: d.status,
      subLevel: d.sub_level,
      playerUuid: d.player_uuid,
    }),
  clear: () => invoke("auth_clear"),
};

export const registerLink = {
  load: () => invoke<RegisterLink | null>("register_link_load"),
  save: (linkToken: string, telegramUrl: string) =>
    invoke("register_link_save", { linkToken, telegramUrl }),
  clear: () => invoke("register_link_clear"),
};

export const api = {
  login: (username: string, code: string) =>
    invoke<ApiResult>("api_login", { username, code }),
  registerTelegramLink: () =>
    invoke<ApiResult>("api_register_telegram_link"),
  registerPoll: (linkToken: string) =>
    invoke<ApiResult>("api_register_poll", { linkToken }),
  registerComplete: (linkToken: string, username: string) =>
    invoke<ApiResult>("api_register_complete", { linkToken, username }),
};
