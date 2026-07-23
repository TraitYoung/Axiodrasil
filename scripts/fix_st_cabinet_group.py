"""Clean ST duplicates and recreate Axiodrasil group with ASCII-only files."""
from __future__ import annotations

import json
from pathlib import Path

import requests

ROOT = Path(r"D:\Axiomdrasil\SillyTavern\data\default-user")
chars_dir = ROOT / "characters"
groups_dir = ROOT / "groups"
chats_dir = ROOT / "group chats"
cards_dir = Path(r"D:\1important\aixodrasil_core\sillytavern\character_card\group")

EN_NAMES = {
    "bina": "Bina",
    "bit": "Bit",
    "taki": "Taki",
    "chizheng": "Chizheng",
    "tianji": "Tianji",
    "fukucho": "Fukucho",
    "vinci": "Vinci",
    "planck": "Planck",
    "jiafa": "Jiafa",
    "qianjin": "Qianjin",
    "boming": "Boming",
    "jean": "Jean",
}

PREEXISTING = {"Bina.png", "taki.png", "default_Assistant.png"}


def main() -> None:
    for pid, en in EN_NAMES.items():
        p = cards_dir / f"{pid}.json"
        card = json.loads(p.read_text(encoding="utf-8"))
        card["data"]["name"] = en
        card["data"]["first_mes"] = f"({en} online) I am listening."
        p.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")

    s = requests.Session()
    s.get("http://127.0.0.1:8001/")

    def csrf_headers(json_mode: bool = False) -> dict:
        token = s.get("http://127.0.0.1:8001/csrf-token").json()["token"]
        h = {"X-CSRF-Token": token}
        if json_mode:
            h["Content-Type"] = "application/json"
        return h

    chars = s.post(
        "http://127.0.0.1:8001/api/characters/all",
        headers=csrf_headers(True),
        json={},
    ).json()
    to_delete = []
    for c in chars:
        data = c.get("data") or {}
        tags = [str(t).lower() for t in (data.get("tags") or [])]
        ext = data.get("extensions") or {}
        av = c.get("avatar") or ""
        if "axiodrasil" in tags or "axiodrasil_persona" in ext or av.startswith("ax_"):
            to_delete.append(av)
    print("delete via API", to_delete)
    for av in to_delete:
        r = s.post(
            "http://127.0.0.1:8001/api/characters/delete",
            headers=csrf_headers(True),
            json={"avatar_url": av, "delete_chats": False},
        )
        print(" del", av, r.status_code)

    for p in list(chars_dir.glob("*.png")):
        if p.name not in PREEXISTING:
            try:
                p.unlink()
                print("unlink", p.name)
            except OSError as e:
                print("unlink fail", p.name, e)

    for p in groups_dir.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        cid = d.get("id")
        p.unlink()
        cp = chats_dir / f"{cid}.jsonl"
        if cp.exists():
            cp.unlink()
        print("removed group", cid)

    for pid in EN_NAMES:
        card_path = cards_dir / f"{pid}.json"
        with open(card_path, "rb") as f:
            files = {"avatar": (f"{pid}.json", f, "application/json")}
            data = {"file_type": "json", "preserved_name": f"ax_{pid}"}
            r = s.post(
                "http://127.0.0.1:8001/api/characters/import",
                files=files,
                data=data,
                headers=csrf_headers(False),
            )
        print("import", pid, r.status_code, r.text)

    members = [f"ax_{pid}.png" for pid in EN_NAMES]
    for m in members:
        assert (chars_dir / m).exists(), m

    body = {
        "name": "Axiodrasil-Cabinet",
        "members": members,
        "activation_strategy": 0,
        "generation_mode": 0,
        "allow_self_responses": False,
        "fav": True,
    }
    r = s.post(
        "http://127.0.0.1:8001/api/groups/create",
        headers=csrf_headers(True),
        json=body,
    )
    print("group", r.status_code, r.text)
    g = r.json()
    (chats_dir / f"{g['id']}.jsonl").write_text("", encoding="utf-8")

    chars = s.post(
        "http://127.0.0.1:8001/api/characters/all",
        headers=csrf_headers(True),
        json={},
    ).json()
    ax = [
        c
        for c in chars
        if (c.get("data") or {}).get("extensions", {}).get("axiodrasil_persona")
    ]
    print("ax chars", len(ax), [c.get("avatar") for c in ax])
    print("total chars", len(chars))
    allg = s.post(
        "http://127.0.0.1:8001/api/groups/all",
        headers=csrf_headers(True),
        json={},
    ).json()
    print("groups", [(x.get("name"), len(x.get("members") or [])) for x in allg])
    print("pngs", sorted(p.name for p in chars_dir.glob("*.png")))


if __name__ == "__main__":
    main()
