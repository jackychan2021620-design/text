"""Backend-neutral browser script and origin policy."""
import sys
from pathlib import Path
from urllib.parse import urlparse

SNAPSHOT="JSON.stringify(window.__bookWorkbenchPublic ? window.__bookWorkbenchPublic.snapshot() : {url:location.href,documents:[],ready:document.readyState})"

def capture_script():
    root=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    return (root/'resources'/'douyin-public-capture.js').read_text(encoding='utf-8')

def browser_url(url):
    u=urlparse(url)
    return u.scheme=='https' and (u.hostname=='douyin.com' or (u.hostname or '').endswith('.douyin.com') or u.hostname=='www.iesdouyin.com') and not u.username and not u.password
