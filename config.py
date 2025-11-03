import os
from dotenv import load_dotenv

# โหลด .env จากโฟลเดอร์เดียวกับไฟล์นี้
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=env_path, override=True)

def get_config():
    """อ่านค่าคอนฟิกทั้งหมดจาก .env และคืนเป็น dict"""
    try:
        return {
            "LOGIN_URL": os.environ["LOGIN_URL"],
            "USER": os.environ["USER"],
            "PASS": os.environ["PASS"],
            "TARGET_TERM_TEXT": os.environ["TARGET_TERM_TEXT"],
            "REFRESH_MIN_SEC": int(os.environ.get("REFRESH_MIN_SEC", 300)),
            "REFRESH_MAX_SEC": int(os.environ.get("REFRESH_MAX_SEC", 600)),
            "DISCORD_WEBHOOK": os.environ["DISCORD_WEBHOOK"],
        }
    except KeyError as e:
        raise RuntimeError(f"Missing environment variable: {e}")
