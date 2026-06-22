"""
gumloop_telegram — Shared Telegram bot library for 100 telegram-bot skills.
"""
import requests, os, json, time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

@dataclass
class BotConfig:
    bot_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    chat_id: str   = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID", ""))
    poll_interval: int = int(os.environ.get("POLL_INTERVAL", "300"))
    def validate(self):
        if not self.bot_token: raise RuntimeError("TELEGRAM_BOT_TOKEN required")

def send_alert(text: str, cfg: BotConfig = None) -> bool:
    c = cfg or BotConfig(); c.validate()
    url = f"https://api.telegram.org/bot{c.bot_token}/sendMessage"
    resp = requests.post(url, json={"chat_id":c.chat_id,"text":text,"parse_mode":"Markdown","disable_web_page_preview":True}, timeout=15)
    resp.raise_for_status(); return True

def escape_md(text: str) -> str:
    for c in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(c, f"\\{c}")
    return text

def build_alert(title: str, fields: List[tuple], risk: str = None) -> str:
    lines = [f"🚨 {escape_md(title)}"]
    for k,v in fields: lines.append(f"  • {escape_md(str(k))}: {escape_md(str(v))}")
    if risk: lines.append(f"  ⚠️ {escape_md(risk)}")
    lines.append(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    return "\n".join(lines[:12])

class ScheduledBot:
    def __init__(self, cfg: BotConfig = None):
        self.cfg = cfg or BotConfig(); self.cfg.validate()
        self._seen = set()
    def detect(self) -> List[Dict]: raise NotImplementedError
    def format_alert(self, item: Dict) -> str: raise NotImplementedError
    def tick(self) -> int:
        count = 0
        for item in self.detect():
            key = json.dumps(item, sort_keys=True)
            if key in self._seen: continue
            self._seen.add(key)
            send_alert(self.format_alert(item), self.cfg)
            count += 1
        if len(self._seen) > 10000: self._seen = set(list(self._seen)[-5000:])
        return count
    def run_forever(self, interval: int = None):
        iv = interval or self.cfg.poll_interval
        print(f"Starting {type(self).__name__} — poll every {iv}s")
        while True:
            try: n = self.tick(); print(f"[{datetime.now(timezone.utc).isoformat()}] tick → {n}")
            except Exception as e: print(f"[ERROR] {e}")
            time.sleep(iv)