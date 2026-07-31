"use client";

import { useSyncExternalStore } from "react";

const USER_LOCAL_KEY = "ax-user-local-id";

export function getOrCreateUserLocalId(): string {
  if (typeof window === "undefined") return "ssr";
  let id = localStorage.getItem(USER_LOCAL_KEY);
  if (!id) {
    id = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
    localStorage.setItem(USER_LOCAL_KEY, id);
  }
  return id;
}

function subscribe(_onStoreChange: () => void) {
  void _onStoreChange;
  // 本地 ID 只在首次创建后固定，无需跨标签同步。
  return () => {};
}

export function useUserLocalId(): string {
  return useSyncExternalStore(subscribe, getOrCreateUserLocalId, () => "");
}
