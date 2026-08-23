"""
هستهٔ لایسنس تک‌کاربرهٔ BOM Validator
=====================================

مدل کار (مبتنی بر Device ID):

0. بدون لایسنس، برنامه از اولین اجرا به‌طور خودکار یک‌ماه آزمایشی کار می‌کند؛
   پس از آن بدون لایسنس معتبر از کار می‌افتد.
1. مشتری برنامه را اجرا می‌کند؛ برنامه «شناسهٔ دستگاه» را نمایش می‌دهد.
2. مشتری شناسه را برای صاحبِ نرم‌افزار می‌فرستد.
3. صاحبِ نرم‌افزار با ابزار ``license_generator.py`` (فقط نزد مالک می‌ماند و
   هرگز به مشتری داده نمی‌شود) برای آن شناسه، لایسنس ۱/۳/۶ ماهه می‌سازد.
4. مشتری کلید را در برنامه ثبت می‌کند؛ برنامه آن را در رجیستری ویندوز
   (و در صورت نبودِ ویندوز، در پروندهٔ کاربر) ذخیره می‌کند.

ویژگی‌های امنیتی
----------------
* کلیدِ لایسنس با HMAC-SHA256 امضا می‌شود؛ بدون کلیدِ مخفی، جعل امضاً غیرممکن است.
* کلید مخفی در چند تکهٔ XOR شده درون کد پخش و در زمان اجرا بازسازی می‌شود.
* لایسنس به شناسهٔ سخت‌افزاری دستگاه بسته می‌شود (MAC + MachineGuid/hostname).
* مقایسهٔ امضا با مسیر زمان‌ثابت (hmac.compare_digest) انجام می‌شود.
* کنترل عقب‌گرد ساعت: آخرین زمان اجرای موفق به‌صورت امضاشده ذخیره می‌شود؛
  اگر ساعت سیستم به‌زمان قبل از آن برگردد، لایسنس نامعتبر اعلام می‌شود.
* لایسنس در چند نقطهٔ حیاتی برنامه (شروع، پردازش، خروجی‌گرفتن) بررسی می‌شود.

نکتهٔ صادقانه: هیچ نرم‌افزار پایتونیِ تحویل‌شده به مشتری ۱۰۰٪ ضدکرک نیست؛
برای سخت‌تر شدن، خروجی نهایی را با PyInstaller/Nuitka کامپایل کنید و این
ماژول و license_generator.py را هرگز به‌صورت جداگانه به مشتری ندهید.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import secrets
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# کلید مخفی (تکّه‌تکّه شده – فقط در حافظه بازسازی می‌شود)
# ---------------------------------------------------------------------------
_K_A = [
    142, 33, 201, 87, 250, 12, 177, 64, 230, 5, 98, 156, 41, 219, 130, 72,
    188, 9, 240, 61, 137, 25, 206, 84, 243, 19, 160, 53, 217, 118, 75,
]
_K_B = [
    221, 84, 156, 244, 159, 73, 48, 201, 171, 92, 53, 230, 110, 170, 63, 25,
    215, 66, 149, 100, 202, 82, 163, 253, 146, 111, 209, 14, 162, 231, 38,
]
_SALT = b"BOMV-License-Core::SPCO::v2@2026"


def _master_key() -> bytes:
    """بازسازی کلید یگانه‌سازی در زمان اجرا (هیچ‌وقت روی دیسک نوشته نمی‌شود)."""
    mixed = bytes(a ^ b for a, b in zip(_K_A, _K_B, strict=True))
    return hashlib.sha256(mixed + _SALT).digest()


# ---------------------------------------------------------------------------
# مدل پلن‌ها
# ---------------------------------------------------------------------------
PLAN_DAYS = {"M1": 30, "M3": 90, "M6": 180}
PLAN_TITLES = {"M1": "یک‌ماهه", "M3": "سه‌ماهه", "M6": "شش‌ماهه"}

KEY_PREFIX = "BOM2"
APP_REG_PATH = r"Software\SPCO\BOMValidator"  # مسیر رجیستری (HKCU)
_STORE_FILE = "license_store.json"

# مقدار تحمل برای نوسان ساعت (۲ ساعت) تا برنامه با اختلاف کوچک ساعت قفل نشود
_CLOCK_TOLERANCE_SECONDS = 2 * 3600

# دورهٔ آزمایشی خودکار: از اولین اجرا یک‌ماه بدون لایسنس کار می‌کند
TRIAL_DAYS = 30


# ---------------------------------------------------------------------------
# شناسهٔ دستگاه
# ---------------------------------------------------------------------------
def _machine_guid_windows() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
        ) as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except Exception:
        return ""


def _machine_guid_linux() -> str:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                token = fh.read().strip()
            if token:
                return token
        except Exception:
            continue
    return ""


def _machine_tokens() -> list[str]:
    tokens = [
        platform.system(),
        platform.machine(),
        socket.gethostname(),
        str(uuid.getnode()),  # مبتنی بر آدرس MAC
        _machine_guid_windows(),
        _machine_guid_linux(),
    ]
    return [t for t in tokens if t]


def get_device_id_raw() -> str:
    """اثر انگشت پایدار دستگاه به‌صورت hex (بدون خط‌تیره، حروف بزرگ)."""
    digest = hashlib.sha256("::".join(_machine_tokens()).encode("utf-8")).hexdigest()
    return digest[:40].upper()


def get_device_id() -> str:
    """همان شناسه با قالب خوانا برای نمایش به کاربر: XXXXX-XXXXX-…"""
    raw = get_device_id_raw()
    return "-".join(raw[i : i + 5] for i in range(0, len(raw), 5))


def _normalize_device_id(device_id: str) -> str:
    return "".join(ch for ch in device_id.upper() if ch.isalnum())


# ---------------------------------------------------------------------------
# ذخیره‌سازی (رجیستری ویندوز + fallback فایلی)
# ---------------------------------------------------------------------------
def _reg_available() -> bool:
    return os.name == "nt"


def _store_path() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        root = Path(base) / "SPCO" / "BOMValidator"
    else:
        root = Path.home() / ".config" / "bom_validator"
    root.mkdir(parents=True, exist_ok=True)
    return root / _STORE_FILE


def _store_set(name: str, value: str) -> None:
    ok = False
    if _reg_available():
        try:
            import winreg  # type: ignore

            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, APP_REG_PATH)
            try:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            finally:
                winreg.CloseKey(key)
            ok = True
        except Exception:
            ok = False
    # همیشه یک نسخهٔ پشتیبان فایلی هم می‌نویسیم تا روی سیستم‌های غیرویندوزی کار کند
    try:
        path = _store_path()
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[name] = value
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        if not ok:
            raise


def _store_get(name: str) -> str | None:
    if _reg_available():
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_REG_PATH) as key:
                value, _ = winreg.QueryValueEx(key, name)
            if value:
                return str(value)
        except Exception:
            pass
    try:
        path = _store_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            value = data.get(name)
            if value:
                return str(value)
    except Exception:
        pass
    return None


def _store_delete(name: str) -> None:
    if _reg_available():
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_REG_PATH) as key:
                winreg.DeleteValue(key, name)
        except Exception:
            pass
    try:
        path = _store_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if name in data:
                del data[name]
                path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# مُهر زمانی امضاشده (کنترل عقب‌گرد ساعت)
# ---------------------------------------------------------------------------
def _seal_timestamp(ts: int) -> str:
    sig = hmac.new(_master_key(), f"last::{ts}".encode(), hashlib.sha256).hexdigest()[:24]
    return f"{ts}.{sig}"


def _unseal_timestamp(blob: str) -> int | None:
    try:
        ts_txt, sig = blob.split(".", 1)
        ts = int(ts_txt)
    except Exception:
        return None
    expect = hmac.new(_master_key(), f"last::{ts}".encode(), hashlib.sha256).hexdigest()[:24]
    if not hmac.compare_digest(expect, sig):
        return None
    return ts


def note_successful_run(now: int | None = None) -> None:
    """بعد از هر اجرای موفق، بزرگ‌ترین زمان دیده‌شده را امضاشده نگه می‌دارد."""
    now = int(now if now is not None else time.time())
    prev = _unseal_timestamp(_store_get("last") or "") or 0
    if now > prev:
        _store_set("last", _seal_timestamp(now))


def check_clock(now: int | None = None) -> bool:
    now = int(now if now is not None else time.time())
    last = _unseal_timestamp(_store_get("last") or "")
    if last is None:
        return True  # هنوز اجرای موفقی ثبت نشده یا مهر دست‌کاری شده → در current_state مدیریت می‌شود
    return now >= last - _CLOCK_TOLERANCE_SECONDS


# ---------------------------------------------------------------------------
# دورهٔ آزمایشی یک‌ماههٔ خودکار (از اولین اجرا، بدون نیاز به لایسنس)
# ---------------------------------------------------------------------------
def _seal_trial_stamp(ts: int) -> str:
    """مهر آغاز آزمایش — امضاشده و بسته به شناسهٔ دستگاه (قابل کپی به سیستم دیگر نیست)."""
    msg = f"trial::{get_device_id_raw()}::{ts}"
    sig = hmac.new(_master_key(), msg.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{ts}.{sig}"


def _unseal_trial_stamp(blob: str) -> int | None:
    try:
        ts_txt, sig = blob.split(".", 1)
        ts = int(ts_txt)
    except Exception:
        return None
    msg = f"trial::{get_device_id_raw()}::{ts}"
    expect = hmac.new(_master_key(), msg.encode(), hashlib.sha256).hexdigest()[:24]
    if not hmac.compare_digest(expect, sig):
        return None
    return ts


def _ensure_trial_stamp(now: int | None = None) -> int | None:
    """
    در اولین اجرا مهر آغاز آزمایش را می‌سازد و برمی‌گرداند.
    اگر مهر موجود اما دست‌کاری‌شده باشد (امضا نامعتبر) None برمی‌گردد ⇒ آزمایش نامعتبر است.
    """
    blob = _store_get("trial")
    if blob:
        return _unseal_trial_stamp(blob)
    now_i = int(now if now is not None else time.time())
    _store_set("trial", _seal_trial_stamp(now_i))
    return now_i


# ---------------------------------------------------------------------------
# ساخت / اعتبارسنجی کلید لایسنس
# ---------------------------------------------------------------------------
def build_license_key(device_id: str, months: int, issued_at: int | None = None) -> str:
    """
    ساخت کلید لایسنس برای یک دستگاه و بازهٔ زمانی. فقط توسط مالک استفاده می‌شود.
    months: 1 یا 3 یا 6
    """
    if months not in (1, 3, 6):
        raise ValueError("مدت لایسنس باید ۱ یا ۳ یا ۶ ماه باشد")
    plan = {1: "M1", 3: "M3", 6: "M6"}[months]
    now = int(issued_at if issued_at is not None else time.time())
    payload = {
        "dev": _normalize_device_id(device_id),
        "plan": plan,
        "iat": now,
        "exp": now + PLAN_DAYS[plan] * 86400,
        "rnd": secrets.token_hex(4),
    }
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_master_key(), payload_bytes, hashlib.sha256).digest()
    token = base64.b32encode(payload_bytes + sig).decode("ascii").rstrip("=")
    grouped = "-".join(token[i : i + 5] for i in range(0, len(token), 5))
    return f"{KEY_PREFIX}-{grouped}"


@dataclass
class LicenseState:
    ok: bool
    code: str  # ok | trial | trial_expired | missing | malformed | signature | device | expired | clock
    reason: str
    plan: str = ""
    plan_title: str = ""
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    days_left: int | None = None
    payload: dict = field(default_factory=dict)

    @property
    def summary(self) -> str:
        if not self.ok:
            return self.reason
        days = f"{self.days_left} روز" if self.days_left is not None else "—"
        exp = self.expires_at.strftime("%Y/%m/%d") if self.expires_at else "—"
        return f"لایسنس {self.plan_title} — تا {exp} ({days} باقی)"

    @property
    def short_label(self) -> str:
        """برچسب کوتاه برای رابط کاربری (بدون نمایش روزهای باقی‌مانده)."""
        labels = {
            "ok": "لایسنس فعال",
            "trial": "نسخهٔ آزمایشی",
            "trial_expired": "پایان دورهٔ آزمایشی",
            "expired": "لایسنس منقضی‌شده",
            "missing": "بدون لایسنس",
        }
        return labels.get(self.code, "لایسنس نامعتبر")


def _fail(code: str, reason: str) -> LicenseState:
    return LicenseState(ok=False, code=code, reason=reason)


def _decode_key(key: str) -> tuple[bytes, bytes] | None:
    text = "".join(ch for ch in key.upper() if ch.isalnum())
    if not text.startswith(KEY_PREFIX):
        return None
    token = text[len(KEY_PREFIX):]
    if not token:
        return None
    pad = "=" * ((8 - len(token) % 8) % 8)
    try:
        blob = base64.b32decode(token + pad, casefold=False)
    except Exception:
        return None
    if len(blob) <= 32:
        return None
    return blob[:-32], blob[-32:]


def verify_license_key(
    key: str,
    device_id: str | None = None,
    now: int | None = None,
    enforce_clock: bool = True,
) -> LicenseState:
    """اعتبارسنجی کامل یک کلید لایسنس برای دستگاه جاری (یا دستگاه داده‌شده)."""
    decoded = _decode_key(key)
    if decoded is None:
        return _fail("malformed", "ساختار کلید لایسنس معتبر نیست")
    payload_bytes, sig = decoded

    expect = hmac.new(_master_key(), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(expect, sig):
        return _fail("signature", "امضای لایسنس نامعتبر است (کلید جعلی یا دست‌کاری‌شده)")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
        dev = str(payload["dev"])
        plan = str(payload["plan"])
        iat = int(payload["iat"])
        exp = int(payload["exp"])
        if plan not in PLAN_DAYS or exp <= iat:
            raise ValueError
    except Exception:
        return _fail("malformed", "محتوای لایسنس خوانا نیست")

    expected_dev = _normalize_device_id(device_id if device_id is not None else get_device_id_raw())
    if dev != expected_dev:
        return _fail("device", "این لایسنس مربوط به دستگاه دیگری است")

    now_i = int(now if now is not None else time.time())
    issued_dt = datetime.fromtimestamp(iat)
    expires_dt = datetime.fromtimestamp(exp)
    days_left = max(0, (exp - now_i) // 86400)

    if now_i >= exp:
        return LicenseState(
            ok=False, code="expired",
            reason="لایسنس منقضی شده است — برای تمدید با پشتیبانی تماس بگیرید",
            plan=plan, plan_title=PLAN_TITLES.get(plan, ""),
            issued_at=issued_dt, expires_at=expires_dt, days_left=0, payload=payload,
        )

    if enforce_clock and not check_clock(now_i):
        return LicenseState(
            ok=False, code="clock",
            reason="ساعت سیستم به‌عقب برگردانده شده است؛ زمان سیستم را اصلاح کنید",
            plan=plan, plan_title=PLAN_TITLES.get(plan, ""),
            issued_at=issued_dt, expires_at=expires_dt, days_left=days_left, payload=payload,
        )

    return LicenseState(
        ok=True, code="ok", reason="لایسنس معتبر است",
        plan=plan, plan_title=PLAN_TITLES.get(plan, ""),
        issued_at=issued_dt, expires_at=expires_dt, days_left=days_left, payload=payload,
    )


# ---------------------------------------------------------------------------
# چرخهٔ فعال‌سازی
# ---------------------------------------------------------------------------
def activate(key: str) -> LicenseState:
    """کلید واردشده توسط کاربر را بررسی و در صورت اعتبار ذخیره می‌کند."""
    state = verify_license_key(key)
    if state.ok:
        _store_set("license", key.strip())
        note_successful_run()
    return state


def current_state(now: int | None = None) -> LicenseState:
    """
    وضعیت فعلی دسترسی برنامه:

    * لایسنس معتبر ثبت‌شده → فعال
    * بدون لایسنس → دورهٔ آزمایشی خودکار یک‌ماهه از اولین اجرا
    * پایان آزمایش (یا خرابی هر حافظهٔ امضاشده) → عدم دسترسی تا فعال‌سازی
    """
    key = _store_get("license")
    now_i = int(now if now is not None else time.time())

    if not key:
        stamp = _ensure_trial_stamp(now_i)
        if stamp is None:
            return _fail("trial_expired",
                         "اطلاعات دورهٔ آزمایشی معتبر نیست؛ برای فعال‌سازی لایسنس تهیه کنید")
        expires = stamp + TRIAL_DAYS * 86400
        days_left = max(0, (expires - now_i) // 86400)
        if now_i >= expires or not check_clock(now_i):
            return LicenseState(
                ok=False, code="trial_expired",
                reason="دورهٔ یک‌ماههٔ آزمایشی پایان یافته است — برای ادامه لایسنس تهیه کنید",
                plan_title="آزمایشی", days_left=0,
                expires_at=datetime.fromtimestamp(expires),
            )
        note_successful_run(now_i)
        return LicenseState(
            ok=True, code="trial",
            reason="نسخهٔ آزمایشی فعال است",
            plan_title="آزمایشی", days_left=days_left,
            expires_at=datetime.fromtimestamp(expires),
        )

    state = verify_license_key(key, now=now_i)
    if state.ok:
        note_successful_run()
    elif state.code == "clock":
        # مهر زمانی خراب/دست‌کاری‌شده → مثلند لایسنس نامعتبر رفتار کن
        state = _fail("clock", state.reason)
    return state


def deactivate() -> None:
    _store_delete("license")


def days_to_expiry() -> int | None:
    state = current_state()
    return state.days_left if state.ok else None
