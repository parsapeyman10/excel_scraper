"""
ابزارهای آماده‌سازی آیکون برای ساخت نسخهٔ اجرایی (exe) — بدون وابستگی به Qt.

هنگام ساخت (app.spec) آیکونِ کاربر — با نام اصلیِ دانلودشده
«web-data-scraping-icon-svg-download-png-3587064.*» یا «app_icon.*» — از پوشهٔ
پروژه پیدا می‌شود و با نام ثابت app_icon.* به دو شکل آماده می‌گردد:

* app_icon.ico  → آیکون خودِ فایل exe در ویندوز (پارامتر icon در app.spec)
* app_icon.png  → فایلی که داخل exe قرار می‌گیرد تا آیکون پنجره و تسک‌بار شود
  (excel scraper.py آن را از ریشهٔ _MEIPASS می‌خواند)

اگر فایل کاربر از قبل .ico باشد، بدون تبدیل از همان استفاده می‌شود.
"""

from __future__ import annotations

import glob
import os
import shutil

# ترتیب ترجیح: اول نام استاندارد، بعد نام اصلیِ فایلِ دانلودشدهٔ کاربر
ICON_STEMS = ("app_icon", "web-data-scraping-icon-svg-download-png-3587064")
ICON_EXTS = (".ico", ".png", ".jpg", ".jpeg", ".webp", ".bmp")
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def find_icon_file(folder: str) -> str | None:
    """اولین فایل آیکونِ موجود در پوشه را برمی‌گرداند (طبق ترتیب ترجیح بالا)."""
    for stem in ICON_STEMS:
        for ext in ICON_EXTS:
            path = os.path.join(folder, stem + ext)
            if os.path.isfile(path):
                return path
    # هر پسوندِ دیگری با همان نام‌ها (مثل .svg که قابل استفاده نیست ولی پیدا شود)
    for stem in ICON_STEMS:
        hits = sorted(glob.glob(os.path.join(folder, stem + ".*")))
        if hits:
            return hits[0]
    return None


def _load_image(src: str):
    from PIL import Image
    img = Image.open(src)
    img.load()
    return img.convert("RGBA")


def png_to_ico(src: str, dst: str, sizes: tuple[int, ...] = ICO_SIZES) -> str:
    """تبدیل یک فایل تصویری به ICO چنداندازهٔ استانداردِ ویندوز."""
    _load_image(src).save(dst, format="ICO", sizes=[(s, s) for s in sizes])
    return dst


def _copy_as_png(src: str, dst: str) -> str:
    if src.lower().endswith(".png"):
        shutil.copyfile(src, dst)
    else:
        _load_image(src).save(dst, format="PNG")
    return dst


def prepare_icons(folder: str, out_dir: str) -> dict:
    """
    آماده‌سازی آیکون‌ها برای PyInstaller.

    خروجی:
        {"exe_icon": مسیر فایل .ico برای خود exe (یا None),
         "runtime_icon": مسیر app_icon.png/ico که داخل بسته قرار می‌گیرد (یا None)}
    """
    src = find_icon_file(folder)
    if not src:
        return {"exe_icon": None, "runtime_icon": None}

    os.makedirs(out_dir, exist_ok=True)
    if src.lower().endswith(".ico"):
        dst = os.path.join(out_dir, "app_icon.ico")
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copyfile(src, dst)
        return {"exe_icon": src, "runtime_icon": dst}

    runtime = _copy_as_png(src, os.path.join(out_dir, "app_icon.png"))
    exe_icon = png_to_ico(src, os.path.join(out_dir, "app_icon.ico"))
    return {"exe_icon": exe_icon, "runtime_icon": runtime}
