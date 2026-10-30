"""
GitHub Actions から定期実行される版。
Discord REST API で新着メッセージを取得し、画像をスロットへ保存する。

必要な環境変数（リポジトリの Secrets に登録する）:
  DISCORD_TOKEN … Bot トークン
  CHANNEL_ID    … 監視するチャンネルID
"""

import io
import json
import os
import pathlib
import sys
import urllib.parse

import requests
from PIL import Image

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]

SLOT_COUNT = 20
SLOT_DIR = pathlib.Path("docs/slots")
STATE_PATH = pathlib.Path("bot_state.json")
MAX_EDGE = 2048
FETCH_LIMIT = 50  # 1回の実行で見に行くメッセージ数

API = "https://discord.com/api/v10"
HEADERS = {
    "Authorization": f"Bot {DISCORD_TOKEN}",
    "User-Agent": "VRCGalleryBot (github-actions, 1.0)",
}


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"last_message_id": None, "next_slot": 0}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2))


def fetch_messages(after):
    """新しいメッセージを古い順に返す。"""
    params = {"limit": FETCH_LIMIT}
    if after:
        params["after"] = after

    r = requests.get(
        f"{API}/channels/{CHANNEL_ID}/messages",
        headers=HEADERS,
        params=params,
        timeout=30,
    )
    if r.status_code == 401:
        sys.exit("Discord トークンが不正です")
    if r.status_code == 403:
        sys.exit("Bot にチャンネルの閲覧権限がありません")
    r.raise_for_status()

    # Discord は新しい順で返すので古い順に並べ替える
    return sorted(r.json(), key=lambda m: int(m["id"]))


def add_check_reaction(message_id):
    emoji = urllib.parse.quote("✅")
    requests.put(
        f"{API}/channels/{CHANNEL_ID}/messages/{message_id}/reactions/{emoji}/@me",
        headers=HEADERS,
        timeout=30,
    )


def to_jpeg(raw):
    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max(img.size) > MAX_EDGE:
        scale = MAX_EDGE / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def main():
    SLOT_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()

    messages = fetch_messages(state["last_message_id"])
    if not messages:
        print("新着なし")
        return

    saved = 0
    for msg in messages:
        state["last_message_id"] = msg["id"]

        if msg.get("author", {}).get("bot"):
            continue

        for att in msg.get("attachments", []):
            ctype = att.get("content_type") or ""
            if not ctype.startswith("image/"):
                continue

            try:
                raw = requests.get(att["url"], timeout=60).content
                jpeg = to_jpeg(raw)
            except Exception as e:
                print(f"変換失敗 ({att.get('filename')}): {e}")
                continue

            idx = state["next_slot"]
            (SLOT_DIR / f"slot_{idx:02d}.jpg").write_bytes(jpeg)
            state["next_slot"] = (idx + 1) % SLOT_COUNT
            saved += 1
            print(f"slot_{idx:02d} <- {att.get('filename')}")

            try:
                add_check_reaction(msg["id"])
            except Exception:
                pass

    save_state(state)
    print(f"{saved} 枚を更新しました")


if __name__ == "__main__":
    main()
