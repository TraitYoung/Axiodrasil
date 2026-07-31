"use client";

import { SplashGate } from "@/host/SplashGate";
import { GroupChatView } from "@/modules/group-chat/GroupChatView";

/**
 * 软归档：公开入口已收敛到 /solo（Bina）。
 * 本页仍可直接访问以便恢复群聊；见 docs/archive_ui.md。
 */
export default function GroupPage() {
  return (
    <SplashGate>
      <GroupChatView />
    </SplashGate>
  );
}
