# -*- coding: utf-8 -*-
"""
🤖 بوت تيليجرام – استخراج ايبيات
════════════════════════════════════════════════════════════════
• زر «🚀 استخراج ايبيات» يرسل ملف txt فيه 5000 IP في كل ضغطة.
• الايبيات لا تتكرر لنفس المستخدم؛ وعند انتهاء المخزون تبدأ دورة جديدة.
• ثلاثة أنواع من المصادر تُدمج وتُحدَّث تلقائياً كل 30 دقيقة:
    1) روابط قوائم ضخمة   ← قائمة SOURCES أدناه (أضف مصادرك هنا)
    2) نطاقات CIDR        ← أي رابط/ملف فيه سطور مثل 1.2.3.0/24 يُولَّد منه ايبيات عشوائية
    3) ملفات محلية        ← ضع أي ملف .txt داخل مجلد sources/ بجانب bot.py

المتغيرات (GitHub ← Settings ← Secrets and variables ← Actions):
    BOT_TOKEN      إجباري    توكن البوت من @BotFather
    ALLOWED_USERS  اختياري   آيديات مسموحة مفصولة بفاصلة (فارغ = البوت للجميع)
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
)

# ══════════════════════════════ الإعدادات ══════════════════════════════


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
IPS_PER_REQUEST = env_int("IPS_PER_REQUEST", 5000)   # عدد الايبيات في كل سحب
CACHE_TTL = env_int("CACHE_TTL", 1800)               # كل كم ثانية تُحدَّث المصادر
RANGE_SAMPLE = env_int("RANGE_SAMPLE", 100_000)      # كم ايبي يُولَّد من نطاقات CIDR عند كل تحديث
COOLDOWN = env_int("COOLDOWN", 5)                    # ثواني الانتظار بين سحبين لنفس المستخدم
KEEP_PORT = os.getenv("KEEP_PORT", "0") == "1"       # 1 = IP:PORT  |  0 = IP فقط
MAX_SOURCE_BYTES = 60 * 1024 * 1024                  # أقصى حجم يُقرأ من كل مصدر
MAX_TRACKED_USERS = 2000                             # أقصى عدد مستخدمين يُحفظ سجلّهم في الذاكرة
ALLOWED_USERS = {
    int(x)
    for x in os.getenv("ALLOWED_USERS", "").replace(" ", "").split(",")
    if x.isdigit()
}

# ══════════════════════════════ المصادر ══════════════════════════════
# أي رابط نصي (txt / json / api) فيه ايبيات أو نطاقات CIDR.
# المصدر الذي يتوقف يتم تخطيه تلقائياً (زر «حالة المصادر» يعرض المتوقف).
_GH = "https://raw.githubusercontent.com"
SOURCES = [
    # ── قوائم ايبيات عامة (GitHub raw) ──
    f"{_GH}/TheSpeedX/PROXY-List/master/http.txt",
    f"{_GH}/TheSpeedX/PROXY-List/master/socks4.txt",
    f"{_GH}/TheSpeedX/PROXY-List/master/socks5.txt",
    f"{_GH}/monosans/proxy-list/main/proxies/http.txt",
    f"{_GH}/monosans/proxy-list/main/proxies/socks4.txt",
    f"{_GH}/monosans/proxy-list/main/proxies/socks5.txt",
    f"{_GH}/clarketm/proxy-list/master/proxy-list-raw.txt",
    f"{_GH}/ShiftyTR/Proxy-List/master/http.txt",
    f"{_GH}/ShiftyTR/Proxy-List/master/https.txt",
    f"{_GH}/ShiftyTR/Proxy-List/master/socks4.txt",
    f"{_GH}/ShiftyTR/Proxy-List/master/socks5.txt",
    f"{_GH}/hookzof/socks5_list/master/proxy.txt",
    f"{_GH}/jetkai/proxy-list/main/online-proxies/txt/proxies.txt",
    f"{_GH}/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    f"{_GH}/roosterkid/openproxylist/main/SOCKS4_RAW.txt",
    f"{_GH}/roosterkid/openproxylist/main/SOCKS5_RAW.txt",
    f"{_GH}/MuRongPIG/Proxy-Master/main/http.txt",
    f"{_GH}/MuRongPIG/Proxy-Master/main/socks4.txt",
    f"{_GH}/MuRongPIG/Proxy-Master/main/socks5.txt",
    f"{_GH}/mmpx12/proxy-list/master/http.txt",
    f"{_GH}/mmpx12/proxy-list/master/https.txt",
    f"{_GH}/mmpx12/proxy-list/master/socks4.txt",
    f"{_GH}/mmpx12/proxy-list/master/socks5.txt",
    f"{_GH}/Zaeem20/FREE_PROXIES_LIST/master/http.txt",
    f"{_GH}/Zaeem20/FREE_PROXIES_LIST/master/https.txt",
    f"{_GH}/Zaeem20/FREE_PROXIES_LIST/master/socks4.txt",
    f"{_GH}/Zaeem20/FREE_PROXIES_LIST/master/socks5.txt",
    f"{_GH}/ErcinDedeoglu/proxies/main/proxies/http.txt",
    f"{_GH}/ErcinDedeoglu/proxies/main/proxies/https.txt",
    f"{_GH}/ErcinDedeoglu/proxies/main/proxies/socks4.txt",
    f"{_GH}/ErcinDedeoglu/proxies/main/proxies/socks5.txt",
    f"{_GH}/proxifly/free-proxy-list/main/proxies/all/data.txt",
    f"{_GH}/sunny9577/proxy-scraper/master/proxies.txt",
    f"{_GH}/vakhov/fresh-proxy-list/master/http.txt",
    f"{_GH}/vakhov/fresh-proxy-list/master/socks4.txt",
    f"{_GH}/vakhov/fresh-proxy-list/master/socks5.txt",
    f"{_GH}/Anonym0usWork1221/Free-Proxies/main/proxy_files/http_proxies.txt",
    f"{_GH}/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks4_proxies.txt",
    f"{_GH}/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks5_proxies.txt",
    # ── واجهات API عامة ──
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks4&timeout=10000&country=all",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=10000&country=all",
    "https://spys.me/proxy.txt",
    # ── نطاقات CIDR رسمية (ضخمة): يُولَّد منها ايبيات عشوائية جديدة عند كل تحديث ──
    "https://www.cloudflare.com/ips-v4",
    "https://api.fastly.com/public-ip-list",
    # ── أضف مصادرك هنا 👇 ──
    # "https://example.com/my-big-ip-list.txt",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IPExtractorBot/1.0)"}

# ══════════════════════════════ السجلات ══════════════════════════════
logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
for _noisy in ("httpx", "httpcore"):          # httpx يطبع رابط الطلب وفيه التوكن
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger("ipbot")

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


def parse_text(text: str) -> tuple[set[str], set[str]]:
    """يستخرج (ايبيات، نطاقات CIDR) من أي نص."""
    ips: set[str] = set()
    cidrs: set[str] = set()
    for ip, mask, port in IP_RE.findall(text):
        if mask:
            if int(mask) <= 32:
                cidrs.add(f"{ip}/{mask}")
            continue
        if not is_public(ip):
            continue
        if KEEP_PORT and port and 0 < int(port) < 65536:
            ips.add(f"{ip}:{port}")
        else:
            ips.add(ip)
    return ips, cidrs


def sample_ranges(cidrs: set[str], k: int) -> tuple[set[str], int]:
    """يولّد k ايبي عشوائي من نطاقات CIDR (بدون توسيع النطاق كاملاً في الذاكرة)."""
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


def build_pool(fetched: list[tuple[str, str | None]]):
    """يدمج كل المصادر. يعمل داخل thread كي لا يوقف البوت أثناء المعالجة."""
    all_ips: set[str] = set()
    all_cidrs: set[str] = set()
    stats: dict[str, int] = {}
    for name, text in [*fetched, *load_local_files()]:
        if not text:
            stats[name] = 0
            continue
        ips, cidrs = parse_text(text)
        all_ips |= ips
        all_cidrs |= cidrs
        stats[name] = len(ips) + len(cidrs)      # 0 = المصدر لا يحتوي شيئاً مفيداً
    range_ips, range_total = sample_ranges(all_cidrs, RANGE_SAMPLE)
    all_ips |= range_ips
    return list(all_ips), range_total, stats


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


# ══════════════════════════════ مخزون الايبيات ══════════════════════════════
class IPPool:
    def __init__(self) -> None:
        self.ips: list[str] = []
        self.range_total = 0
        self.stats: dict[str, int] = {}
        self.updated = 0.0
        self.history: dict[int, set[str]] = {}     # user_id -> ايبيات استلمها سابقاً
        self._lock: asyncio.Lock | None = None

    def _fresh(self) -> bool:
        return bool(self.ips) and (time.monotonic() - self.updated) < CACHE_TTL

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

            async def job(url: str):
                async with sem:
                    try:
                        return url, await fetch_text(session, url)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("✗ %s → %s", short_name(url), type(exc).__name__)
                        return url, None

            fetched = await asyncio.gather(*(job(u) for u in SOURCES))

        ips, range_total, stats = await asyncio.to_thread(build_pool, list(fetched))
        self.stats = stats
        if not ips:
            log.error("لم يتم تحميل أي ايبي من أي مصدر!")
            return
        self.commit(ips, range_total)

    def commit(self, ips: list[str], range_total: int) -> None:
        self.ips = ips
        self.range_total = range_total
        self.updated = time.monotonic()
        alive = set(ips)
        for seen in self.history.values():        # تنظيف السجل من ايبيات لم تعد موجودة
            seen &= alive
        log.info("✅ المخزون الجاهز: %d ايبي", len(ips))

    def draw(self, user_id: int, n: int) -> tuple[list[str], bool, int]:
        """يسحب n ايبي لم يستلمها هذا المستخدم من قبل. يرجع (الايبيات، بدأت دورة جديدة؟، المتبقي)."""
        if user_id not in self.history and len(self.history) >= MAX_TRACKED_USERS:
            self.history.pop(next(iter(self.history)))
        seen = self.history.setdefault(user_id, set())

        fresh = [ip for ip in self.ips if ip not in seen]
        reset = False
        if len(fresh) < n and seen:               # لم يتبق ما يكفي → دورة جديدة
            seen.clear()
            fresh = self.ips
            reset = True

        picked = random.sample(fresh, min(n, len(fresh)))
        seen.update(picked)
        return picked, reset, len(self.ips) - len(seen)


POOL = IPPool()
LAST_USE: dict[int, float] = {}
BUSY: set[int] = set()
_BG_TASKS: set[asyncio.Task] = set()

# ══════════════════════════════ الواجهة ══════════════════════════════
WELCOME = (
    "أهلاً <b>{name}</b> 👋\n\n"
    "🌐 <b>بوت استخراج الايبيات</b>\n"
    "اضغط الزر بالأسفل وسيصلك ملف فيه <b>{n:,}</b> ايبي في كل مرة — "
    "ايبيات مختلفة وبدون تكرار."
)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 استخراج ايبيات", callback_data="extract")],
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
    await update.effective_message.reply_text(
        WELCOME.format(name=html.escape(user.first_name or ""), n=IPS_PER_REQUEST),
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML,
    )


async def do_extract(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = query.from_user.id
    now = time.monotonic()

    if uid in BUSY:
        await query.answer("⏳ جارِ تجهيز طلبك السابق...")
        return
    wait = COOLDOWN - (now - LAST_USE.get(uid, -1e9))
    if wait > 0:
        await query.answer(f"⏳ انتظر {int(wait) + 1} ثانية")
        return

    BUSY.add(uid)
    LAST_USE[uid] = now
    try:
        await query.answer()
        await safe_edit(query, "⏳ <b>جارِ استخراج الايبيات...</b>")
        await POOL.ensure_fresh()
        if not POOL.ips:
            await safe_edit(query, "⚠️ تعذّر تحميل المصادر حالياً، حاول بعد قليل.", main_menu())
            return

        ips, reset, remaining = POOL.draw(uid, IPS_PER_REQUEST)
        caption = [
            f"✅ <b>تم استخراج {len(ips):,} ايبي</b>",
            f"🔒 المتبقي لك بدون تكرار: {remaining:,}",
            f"🗂 إجمالي المخزون: {len(POOL.ips):,}",
        ]
        if reset:
            caption.append("♻️ انتهت الايبيات الجديدة فبدأت دورة جديدة.")

        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document="\n".join(ips).encode("utf-8"),
            filename=time.strftime("ips_%Y%m%d_%H%M%S.txt"),
            caption="\n".join(caption),
            parse_mode=ParseMode.HTML,
        )
        await safe_edit(
            query,
            "✅ <b>تم الإرسال!</b>\nاضغط مرة أخرى لسحب دفعة جديدة مختلفة 👇",
            main_menu(),
        )
    except Exception:  # noqa: BLE001
        log.exception("فشل الاستخراج")
        await safe_edit(query, "❌ حدث خطأ، حاول مرة أخرى.", main_menu())
    finally:
        BUSY.discard(uid)


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
        f"🌐 ايبيات جاهزة: <b>{len(POOL.ips):,}</b>",
        f"🎲 مدى نطاقات CIDR: <b>{POOL.range_total:,}</b> ايبي ممكن",
        f"📦 حجم كل سحب: <b>{IPS_PER_REQUEST:,}</b>",
        f"🕒 آخر تحديث: قبل {age} دقيقة",
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
        await do_extract(query, context)
    elif query.data == "status":
        await do_status(query)
    else:
        await query.answer()


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("خطأ غير متوقع", exc_info=context.error)


async def post_init(app: Application) -> None:
    async def warmup() -> None:                    # تجهيز المخزون قبل أول ضغطة
        try:
            await POOL.ensure_fresh()
        except Exception:  # noqa: BLE001
            log.exception("فشل التجهيز المبدئي")

    task = asyncio.create_task(warmup())
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
    app.add_error_handler(on_error)

    log.info("🤖 البوت يعمل الآن...")
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
