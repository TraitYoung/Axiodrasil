"use client";

import { useEffect, useState } from "react";

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

export function useUserLocalId(): string {
  const [id, setId] = useState("");
  useEffect(() => {
    setId(getOrCreateUserLocalId());
  }, []);
  return id;
}
