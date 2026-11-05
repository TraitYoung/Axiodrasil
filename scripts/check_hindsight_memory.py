"""通过真实 Bina HTTP 入口验证跨会话、更正和共同经历，使用独立测试身份。"""

from __future__ import annotations

import argparse
import json
from urllib.request import Request, urlopen
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    memory_id = "hindsight-acceptance-" + uuid4().hex
    print(f"隔离测试记忆身份 {memory_id}", flush=True)

    def chat(text: str) -> str:
        request = Request(
            args.base_url.rstrip("/") + "/api/v1/chat",
            data=json.dumps({"text": text, "forced_persona": "bina", "group_mode": False,
                             "strip_persona_prefix": True}).encode(),
            headers={"Content-Type": "application/json", "x-memory-thread": memory_id,
                     "x-session-id": "acceptance-conversation-" + uuid4().hex},
        )
        with urlopen(request, timeout=300) as response:
            data = json.load(response)
        if data.get("active_persona") != "bina":
            raise AssertionError("回复人物应为 Bina")
        print(f"Bina {data['reply']}", flush=True)
        return data["reply"]

    def require(reply: str, words: tuple[str, ...]) -> None:
        for word in words:
            if word not in reply:
                raise AssertionError(f"回答缺少验收事实 {word!r}")

    chat("请记住：我现在住在苏州，我最喜欢的饮料是桂花乌龙茶。")
    answer = chat("我现在住在哪座城市，最喜欢什么饮料？请只回答这两个事实。")
    require(answer, ("苏州", "桂花乌龙茶"))
    print("PASS 跨会话记忆", flush=True)

    chat("更正我的居住信息：我已经从苏州搬到了杭州，现在住在杭州。苏州是以前的住处。")
    answer = chat("我现在住在哪座城市？请只回答当前城市，不要提历史住处。")
    require(answer, ("杭州",))
    if "苏州" in answer:
        raise AssertionError("更正后的当前住处不应仍回答苏州")
    print("PASS 事实更正", flush=True)

    chat("记下一段已经发生的共同经历：2026年10月20日，我们在聊天里一起给我的蓝色马克杯取名叫星河杯。我现在回想起这次取名还是很开心。")
    answer = chat("我们之前一起给我的什么物品取了什么名字？那次是哪一天？请具体回答。")
    require(answer, ("蓝色", "星河杯", "20"))
    if not any(name in answer for name in ("马克杯", "杯子", "茶杯", "水杯")):
        raise AssertionError("共同经历应召回物品是杯子")
    if "10" not in answer and "十月" not in answer:
        raise AssertionError("共同经历应召回十月的事件时间")
    print("PASS 共同经历召回", flush=True)
    print("三个场景均通过，每次请求均使用新的会话 ID。测试记忆保存在独立身份中供检查。", flush=True)


if __name__ == "__main__":
    main()
