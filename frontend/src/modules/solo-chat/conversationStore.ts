/**
 * Bina 单聊对话目录（浏览器 localStorage）。
 * conversation id 管气泡；记忆池 id 恒为 soloSessionId("bina", userLocalId)。
 */

import { soloSessionId } from "@/matrix/types";

export type SoloConversation = {
  id: string;
  title: string;
  updatedAt: string;
  preview: string;
};

export type SoloConversationCatalog = {
  activeId: string;
  items: SoloConversation[];
};

const STORE_PREFIX = "ax-solo-conversations-v1:";

function storageKey(userLocalId: string): string {
  return `${STORE_PREFIX}${userLocalId}`;
}

function nowIso(): string {
  return new Date().toISOString();
}

export function memoryPoolId(userLocalId: string): string {
  return soloSessionId("bina", userLocalId);
}

function legacyConversationId(userLocalId: string): string {
  return memoryPoolId(userLocalId);
}

function newConversationId(userLocalId: string): string {
  const short = Math.random().toString(36).slice(2, 8);
  return `${legacyConversationId(userLocalId)}-c-${short}`;
}

function readRaw(userLocalId: string): SoloConversationCatalog | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(storageKey(userLocalId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SoloConversationCatalog;
    if (!parsed?.activeId || !Array.isArray(parsed.items)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeRaw(userLocalId: string, cat: SoloConversationCatalog): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(storageKey(userLocalId), JSON.stringify(cat));
}

/** 首次把旧固定 session 迁入为「默契谈话」 */
export function ensureCatalog(userLocalId: string): SoloConversationCatalog {
  const existing = readRaw(userLocalId);
  if (existing && existing.items.length > 0) {
    if (!existing.items.some((x) => x.id === existing.activeId)) {
      existing.activeId = existing.items[0].id;
      writeRaw(userLocalId, existing);
    }
    return existing;
  }
  const legacyId = legacyConversationId(userLocalId);
  const cat: SoloConversationCatalog = {
    activeId: legacyId,
    items: [
      {
        id: legacyId,
        title: "默契谈话",
        updatedAt: nowIso(),
        preview: "",
      },
    ],
  };
  writeRaw(userLocalId, cat);
  return cat;
}

export function listConversations(userLocalId: string): SoloConversation[] {
  const cat = ensureCatalog(userLocalId);
  return [...cat.items].sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1));
}

export function getActiveConversation(userLocalId: string): SoloConversation {
  const cat = ensureCatalog(userLocalId);
  return cat.items.find((x) => x.id === cat.activeId) || cat.items[0];
}

export function createConversation(
  userLocalId: string,
  title = "新的谈话",
): SoloConversation {
  const cat = ensureCatalog(userLocalId);
  const item: SoloConversation = {
    id: newConversationId(userLocalId),
    title,
    updatedAt: nowIso(),
    preview: "",
  };
  cat.items = [item, ...cat.items];
  cat.activeId = item.id;
  writeRaw(userLocalId, cat);
  return item;
}

export function selectConversation(userLocalId: string, id: string): void {
  const cat = ensureCatalog(userLocalId);
  if (!cat.items.some((x) => x.id === id)) return;
  cat.activeId = id;
  writeRaw(userLocalId, cat);
}

export function renameConversation(userLocalId: string, id: string, title: string): void {
  const cat = ensureCatalog(userLocalId);
  const next = (title || "").trim().slice(0, 32) || "谈话";
  cat.items = cat.items.map((x) => (x.id === id ? { ...x, title: next, updatedAt: nowIso() } : x));
  writeRaw(userLocalId, cat);
}

export function removeConversation(userLocalId: string, id: string): SoloConversationCatalog {
  const cat = ensureCatalog(userLocalId);
  const next = cat.items.filter((x) => x.id !== id);
  if (next.length === 0) {
    const item: SoloConversation = {
      id: newConversationId(userLocalId),
      title: "新的谈话",
      updatedAt: nowIso(),
      preview: "",
    };
    cat.items = [item];
    cat.activeId = item.id;
    writeRaw(userLocalId, cat);
    return cat;
  }
  cat.items = next;
  if (cat.activeId === id) {
    cat.activeId = next[0].id;
  }
  writeRaw(userLocalId, cat);
  return cat;
}

/** 发送后更新预览；若仍是默认标题则用首句用户消息。 */
export function touchConversation(
  userLocalId: string,
  id: string,
  preview: string,
  options?: { suggestTitleFromPreview?: boolean },
): void {
  const cat = ensureCatalog(userLocalId);
  const clipped = (preview || "").replace(/\s+/g, " ").trim().slice(0, 48);
  const suggest = Boolean(options?.suggestTitleFromPreview);
  cat.items = cat.items.map((x) => {
    if (x.id !== id) return x;
    let title = x.title;
    if (suggest && clipped && (title === "新的谈话" || title === "默契谈话" || !title)) {
      title = clipped.slice(0, 20);
    }
    return {
      ...x,
      title,
      preview: clipped,
      updatedAt: nowIso(),
    };
  });
  writeRaw(userLocalId, cat);
}
