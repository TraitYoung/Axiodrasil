"use client";

import { SplashGate } from "@/host/SplashGate";
import { GroupChatView } from "@/modules/group-chat/GroupChatView";

export default function GroupPage() {
  return (
    <SplashGate>
      <GroupChatView />
    </SplashGate>
  );
}
