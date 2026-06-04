import { api as client } from "./client";

export interface GenerateCodeResult {
  code: string;
  expires_at: string;
  bot_username: string;
}

export interface TelegramStatus {
  is_verified: boolean;
  telegram_username?: string | null;
  created_at?: string | null;
  verified_at?: string | null;
}

export function generateTelegramCode(): Promise<GenerateCodeResult> {
  return client.post("/telegram/link").then((r) => r.data);
}

export function getTelegramStatus(): Promise<TelegramStatus> {
  return client.get("/telegram/link/status").then((r) => r.data);
}

export function unlinkTelegram(): Promise<void> {
  return client.delete("/telegram/link");
}
