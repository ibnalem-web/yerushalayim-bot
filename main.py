#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت تيليجرام: مكتبة وأرشيف الكتب السماوية  (main.py)
python-telegram-bot >= 20 (يُفضّل 21.8+ لزر النسخ المباشر) + httpx (يُثبَّت تلقائياً مع المكتبة)

القرآن (السور، الآيات، الترجمات، التفاسير، التلاوات) يُجلب مباشرة من:
  - https://api.alquran.cloud/v1   (المصدر الأساسي)
  - https://api.quran.com/api/v4   (احتياطي للترجمات التي لا تتوفر في alquran.cloud، ولتفاسير إضافية)
الإنجيل والتوراة ما زالا من القاموس المحلي LIB (عيّنات + ملفات data/*.json اختيارية).

التشغيل:  pip install "python-telegram-bot>=21.8"   ثم ضع التوكن في آخر الملف و:  python main.py

بنية callback_data (أقل من 64 بايت):
  L|<lang> | M | M|n | B | S|<menu> | C | SOON | NOOP
  P|<book>|<mode>|<page>|v1|v2|...   مسار الاختيارات (سورة > آية > مفسّر > قارئ)
"""
import asyncio
import html
import json
import logging
import re
import time
from pathlib import Path

import httpx
from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Markup
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, PicklePersistence)

try:  # زر النسخ المباشر (Bot API 7.11+ / PTB 21.8+)
    from telegram import CopyTextButton
except ImportError:
    CopyTextButton = None

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
HTML = ParseMode.HTML

# ════════════════════════════════════════════════════════════════
# 1) اللغات العشرون
# ════════════════════════════════════════════════════════════════
LANGUAGES = [
    ("ar", "🇸🇦", "العربية"), ("he", "🇮🇱", "עברית"), ("en", "🇬🇧", "English"),
    ("syr", "🇸🇾", "ܣܘܪܝܝܐ"), ("fr", "🇫🇷", "Français"), ("es", "🇪🇸", "Español"),
    ("de", "🇩🇪", "Deutsch"), ("it", "🇮🇹", "Italiano"), ("pt", "🇵🇹", "Português"),
    ("ru", "🇷🇺", "Русский"), ("tr", "🇹🇷", "Türkçe"), ("fa", "🇮🇷", "فارسی"),
    ("ur", "🇵🇰", "اردو"), ("hi", "🇮🇳", "हिन्दी"), ("id", "🇮🇩", "Bahasa Indonesia"),
    ("zh", "🇨🇳", "中文"), ("ja", "🇯🇵", "日本語"), ("ko", "🇰🇷", "한국어"),
    ("el", "🇬🇷", "Ελληνικά"), ("nl", "🇳🇱", "Nederlands"),
]
# اسم اللغة بالإنجليزية كما يستخدمه api.quran.com
LANG_NAME = {
    "ar": "arabic", "he": "hebrew", "en": "english", "syr": "syriac", "fr": "french", "es": "spanish",
    "de": "german", "it": "italian", "pt": "portuguese", "ru": "russian", "tr": "turkish",
    "fa": "persian", "ur": "urdu", "hi": "hindi", "id": "indonesian", "zh": "chinese",
    "ja": "japanese", "ko": "korean", "el": "greek", "nl": "dutch",
}
NAME_LANG = {v: k for k, v in LANG_NAME.items()}
# ترجمات مفضّلة لكل لغة (إن لم تُوجد يُؤخذ أول إصدار متاح من الـ API)
PREFERRED_TRANSLATION = {
    "en": "en.sahih", "fr": "fr.hamidullah", "es": "es.cortes", "de": "de.aburida", "ru": "ru.kuliev",
    "tr": "tr.diyanet", "ur": "ur.jalandhry", "id": "id.indonesian", "zh": "zh.jian",
    "ja": "ja.japanese", "ko": "ko.korean", "it": "it.piccardo", "nl": "nl.keyzer",
    "pt": "pt.elhayek", "hi": "hi.hindi", "fa": "fa.makarem",
}

# ════════════════════════════════════════════════════════════════
# 2) نصوص الواجهة (الناقص يرجع للإنجليزية)
# ════════════════════════════════════════════════════════════════
UI = {
    "ar": dict(
        pick_lang="🌐 اختر لغتك / Choose your language", main="القائمة الرئيسية", soon="قريباً",
        books="الكتب السماوية", quran="القرآن الكريم", gospel="الإنجيل", torah="التوراة",
        surahs="السور", verses="الآيات", tafsir="التفسير", recitations="التلاوات",
        recite_surahs="تلاوة السور", recite_verses="تلاوة الآيات",
        ot="العهد القديم", nt="العهد الجديد", books_list="الأسفار", chapters="الإصحاحات",
        pick_surah="اختر السورة", pick_book="اختر السفر", pick_chapter="اختر الإصحاح",
        pick_verse="اختر رقم الآية", pick_author="اختر المفسّر", pick_reciter="اختر القارئ",
        back="رجوع", home="الرئيسية", copy="نسخ", prev="الآية السابقة", next="الآية التالية",
        source="المصدر", no_data="لا توجد بيانات متاحة بعد", audio_fail="تعذّر إرسال الملف الصوتي، رابطه:",
        api_error="⚠️ تعذّر الاتصال بالخادم، حاول مرة أخرى بعد قليل.",
        fallback="(لا توجد ترجمة بلغتك، عُرضت الإنجليزية)"),
    "en": dict(
        pick_lang="🌐 اختر لغتك / Choose your language", main="Main menu", soon="Coming soon",
        books="Heavenly Books", quran="The Holy Quran", gospel="The Gospel", torah="The Torah",
        surahs="Surahs", verses="Verses", tafsir="Tafsir / Commentary", recitations="Recitations",
        recite_surahs="Recite surahs", recite_verses="Recite verses",
        ot="Old Testament", nt="New Testament", books_list="Books", chapters="Chapters",
        pick_surah="Choose a surah", pick_book="Choose a book", pick_chapter="Choose a chapter",
        pick_verse="Choose a verse", pick_author="Choose a commentator", pick_reciter="Choose a reciter",
        back="Back", home="Home", copy="Copy", prev="Previous", next="Next",
        source="Source", no_data="No data available yet", audio_fail="Could not send the audio, link:",
        api_error="⚠️ Could not reach the server, please try again shortly.",
        fallback="(no translation in your language, English shown)"),
    "he": dict(
        pick_lang="🌐 اختر لغتك / Choose your language", main="התפריט הראשי", soon="בקרוב",
        books="הספרים הקדושים", quran="הקוראן", gospel="הבשורה", torah="התורה",
        surahs="סורות", verses="פסוקים", tafsir="פרשנות", recitations="דקלום",
        recite_surahs="דקלום סורות", recite_verses="דקלום פסוקים",
        ot="הברית הישנה", nt="הברית החדשה", books_list="ספרים", chapters="פרקים",
        pick_surah="בחר סורה", pick_book="בחר ספר", pick_chapter="בחר פרק",
        pick_verse="בחר פסוק", pick_author="בחר מפרש", pick_reciter="בחר קורא",
        back="חזרה", home="ראשי", copy="העתק", prev="הקודם", next="הבא",
        source="מקור", no_data="אין נתונים זמינים עדיין", audio_fail="לא ניתן לשלוח את הקובץ, קישור:",
        api_error="⚠️ לא ניתן להתחבר לשרת, נסה שוב בעוד מעט.",
        fallback="(אין תרגום בשפתך, מוצג באנגלית)"),
}


def tr(lang, key):
    return UI.get(lang, {}).get(key) or UI["en"][key]


# ════════════════════════════════════════════════════════════════
# 3) طبقة الاتصال بالـ API (كاش + إعادة محاولة)
# ════════════════════════════════════════════════════════════════
CLOUD = "https://api.alquran.cloud/v1"
QCOM = "https://api.quran.com/api/v4"
AR_EDITION = "quran-uthmani"  # النص العربي بالتشكيل (عثماني)

# تلاوة السورة كاملة (ملف واحد): معرّف إصدار alquran.cloud → (الاسم, قالب الرابط). تحقق من الروابط وأضف قرّاء.
SURAH_AUDIO = {
    "ar.alafasy": ("مشاري العفاسي", "https://server8.mp3quran.net/afs/{s:03d}.mp3"),
    "ar.husary": ("محمود خليل الحصري", "https://server13.mp3quran.net/husr/{s:03d}.mp3"),
}

HTTP: "httpx.AsyncClient | None" = None


class ApiError(Exception):
    pass


class TTLCache:
    def __init__(self, ttl=6 * 3600, maxsize=300):
        self.ttl, self.maxsize, self.d = ttl, maxsize, {}

    def get(self, k):
        v = self.d.get(k)
        if v and time.time() - v[0] < self.ttl:
            return v[1]
        self.d.pop(k, None)
        return None

    def set(self, k, val):
        if len(self.d) >= self.maxsize:
            self.d.pop(min(self.d, key=lambda x: self.d[x][0]), None)
        self.d[k] = (time.time(), val)


CACHE = TTLCache()


async def api_get(url, params=None):
    key = (url, tuple(sorted((params or {}).items())))
    hit = CACHE.get(key)
    if hit is not None:
        return hit
    last = None
    for attempt in range(3):
        try:
            r = await HTTP.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            CACHE.set(key, data)
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            await asyncio.sleep(0.8 * (attempt + 1))
    raise ApiError(f"{url}: {last}")


def clean_html(s):
    s = re.sub(r"<sup[^>]*>.*?</sup>", "", s or "", flags=re.S)  # حواشي الترجمات
    s = re.sub(r"<\s*br\s*/?>|</p>|</div>|</h\d>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()


# ── السور ───────────────────────────────────────────────────────
async def surah_list():
    return (await api_get(f"{CLOUD}/surah"))["data"]  # 114 عنصراً: number, name, englishName, numberOfAyahs


def surah_label(s, lang):
    return s["name"] if lang == "ar" else s["englishName"]


async def global_ayah(n, v):
    surahs = await surah_list()
    return sum(s["numberOfAyahs"] for s in surahs[:n - 1]) + v


# ── النص العربي (مع إزالة البسملة المدمجة في الآية الأولى) ──────────
_DIAC = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_BASMALA = ["بسم", "الله", "الرحمن", "الرحيم"]


def _norm(w):
    return _DIAC.sub("", w).replace("ٱ", "ا")


def strip_basmala(n, i, text):
    if i == 1 and n not in (1, 9):
        words = text.split()
        if len(words) > 4 and [_norm(w) for w in words[:4]] == _BASMALA:
            return " ".join(words[4:])
    return text


async def arabic_verses(n):
    d = await api_get(f"{CLOUD}/surah/{n}/{AR_EDITION}")
    return [strip_basmala(n, a["numberInSurah"], a["text"]) for a in d["data"]["ayahs"]]


# ── الترجمات ────────────────────────────────────────────────────
async def _find_translation(lg):
    try:
        d = await api_get(f"{CLOUD}/edition", {"format": "text", "type": "translation", "language": lg})
        eds = d.get("data") or []
        if eds:
            pref = PREFERRED_TRANSLATION.get(lg)
            ed = next((e for e in eds if e["identifier"] == pref), eds[0])
            return {"kind": "c", "id": ed["identifier"], "label": ed.get("englishName") or ed["name"]}
    except ApiError:
        pass
    try:  # احتياطي: api.quran.com
        d = await api_get(f"{QCOM}/resources/translations")
        c = [t for t in d.get("translations", []) if (t.get("language_name") or "").lower() == LANG_NAME.get(lg)]
        if c:
            return {"kind": "q", "id": str(c[0]["id"]), "label": c[0].get("author_name") or c[0]["name"]}
    except ApiError:
        pass
    return None


async def translation_info(lang):
    """إصدار الترجمة للغة المستخدم (None للعربية). إن لم توجد → الإنجليزية مع علامة fallback."""
    if lang == "ar":
        return None
    for lg in (lang, "en"):
        info = await _find_translation(lg)
        if info:
            return {**info, "fallback": lg != lang}
    return None


async def translation_verses(n, info):
    if info["kind"] == "c":
        d = await api_get(f"{CLOUD}/surah/{n}/{info['id']}")
        return [clean_html(a["text"]) for a in d["data"]["ayahs"]]
    d = await api_get(f"{QCOM}/quran/translations/{info['id']}", {"chapter_number": n})
    return [clean_html(t["text"]) for t in d["translations"]]


async def get_surah(n, lang):
    """(آيات عربية, ترجمات أو None, معلومات الترجمة)"""
    ar = await arabic_verses(n)
    info = await translation_info(lang)
    trn = None
    if info:
        try:
            trn = await translation_verses(n, info)
            trn = (trn + [""] * len(ar))[:len(ar)]
        except ApiError:
            trn = None
    return ar, trn, info


def translation_footer(lang, info, trn):
    if not (info and trn):
        return ""
    note = f" {tr(lang, 'fallback')}" if info.get("fallback") else ""
    return f"\n\n<i>🌐 {esc(info['label'])}{esc(note)}</i>"


# ── التفاسير ────────────────────────────────────────────────────
async def tafsir_list(lang):
    """[(id, label, lang_code)] — id بالشكل c:<edition> أو q:<id>."""
    hit = CACHE.get(("tafsirs", lang))
    if hit is not None:
        return hit
    items = []
    try:
        d = await api_get(f"{CLOUD}/edition", {"type": "tafsir"})
        for e in d.get("data", []):
            label = e["name"] if (lang == "ar" and e["language"] == "ar") else (e.get("englishName") or e["name"])
            items.append(("c:" + e["identifier"], label, e["language"]))
    except ApiError:
        pass
    try:
        d = await api_get(f"{QCOM}/resources/tafsirs")
        for t in d.get("tafsirs", []):
            lg = NAME_LANG.get((t.get("language_name") or "").lower(), (t.get("language_name") or "?").lower())
            label = f"{t.get('name')} — {t['author_name']}" if t.get("author_name") else t.get("name", "?")
            items.append(("q:" + str(t["id"]), label[:60], lg))
    except ApiError:
        pass
    rank = lambda lg: 0 if lg == lang else 1 if lg == "ar" else 2 if lg == "en" else 3  # noqa: E731
    items.sort(key=lambda x: (rank(x[2]), x[1]))
    if items:
        CACHE.set(("tafsirs", lang), items)
    return items


async def tafsir_text(author, n, v):
    kind, _, ident = author.partition(":")
    if kind == "c":
        d = await api_get(f"{CLOUD}/ayah/{await global_ayah(n, v)}/{ident}")
        return clean_html(d["data"]["text"])
    d = await api_get(f"{QCOM}/tafsirs/{ident}/by_ayah/{n}:{v}")
    return clean_html(d["tafsir"]["text"])


# ── التلاوات ────────────────────────────────────────────────────
async def verse_reciters(lang):
    try:
        d = await api_get(f"{CLOUD}/edition", {"format": "audio", "language": "ar", "type": "versebyverse"})
        return [(e["identifier"], e["name"] if lang == "ar" else (e.get("englishName") or e["name"]))
                for e in d.get("data", [])]
    except ApiError:
        return [(k, v[0]) for k, v in SURAH_AUDIO.items()]


async def verse_audio_url(edition, n, v):
    g = await global_ayah(n, v)
    d = await api_get(f"{CLOUD}/ayah/{g}/{edition}")
    return d["data"].get("audio") or f"https://cdn.islamic.network/quran/audio/128/{edition}/{g}.mp3"


# ════════════════════════════════════════════════════════════════
# 4) الإنجيل والتوراة (محلي) — أضف نصوصك هنا أو في data/ot.json ... إلخ
#    LIB[book]["works"][work][ "text"][chapter][verse]، tafsir[author] = {name, source, data}
# ════════════════════════════════════════════════════════════════
LIB = {
    "ot": {"base_lang": "en", "works": {"1": {"name": {"ar": "التكوين", "en": "Genesis", "he": "בראשית"}, "text": {"1": {
        "1": "In the beginning God created the heaven and the earth.",
        "2": "And the earth was without form, and void; and darkness was upon the face of the deep. "
             "And the Spirit of God moved upon the face of the waters.",
        "3": "And God said, Let there be light: and there was light."}}}}, "translations": {}, "tafsir": {}},
    "nt": {"base_lang": "en", "works": {"4": {"name": {"ar": "يوحنا", "en": "John", "he": "יוחנן"}, "text": {"1": {
        "1": "In the beginning was the Word, and the Word was with God, and the Word was God.",
        "2": "The same was in the beginning with God.",
        "3": "All things were made by him; and without him was not any thing made that was made."}}}},
        "translations": {}, "tafsir": {}},
    "tr": {"base_lang": "he", "works": {"1": {"name": {"ar": "التكوين", "en": "Genesis", "he": "בראשית"}, "text": {"1": {
        "1": "בְּרֵאשִׁית בָּרָא אֱלֹהִים אֵת הַשָּׁמַיִם וְאֵת הָאָרֶץ",
        "2": "וְהָאָרֶץ הָיְתָה תֹהוּ וָבֹהוּ וְחֹשֶׁךְ עַל־פְּנֵי תְהוֹם וְרוּחַ אֱלֹהִים מְרַחֶפֶת עַל־פְּנֵי הַמָּיִם",
        "3": "וַיֹּאמֶר אֱלֹהִים יְהִי אוֹר וַיְהִי־אוֹר"}}}}, "translations": {}, "tafsir": {}},
}


def deep_update(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v


def load_external_data(folder="data"):
    for book in LIB:
        f = Path(folder) / f"{book}.json"
        if f.exists():
            deep_update(LIB[book], json.loads(f.read_text("utf-8")))


# ════════════════════════════════════════════════════════════════
# 5) القوائم والمسارات
# ════════════════════════════════════════════════════════════════
BOOK_KEY = {"q": "quran", "ot": "ot", "nt": "nt", "tr": "torah"}
_BIBLE_MODES = (("b", "books_list"), ("c", "chapters"), ("v", "verses"), ("t", "tafsir"))
MENUS = {
    "q": ("quran", "B", [("P|q|s|0", "surahs"), ("P|q|v|0", "verses"),
                         ("P|q|t|0", "tafsir"), ("S|qr", "recitations")]),
    "qr": ("recitations", "S|q", [("P|q|rs|0", "recite_surahs"), ("P|q|rv|0", "recite_verses")]),
    "inj": ("gospel", "B", [("S|ot", "ot"), ("S|nt", "nt")]),
    "ot": ("ot", "S|inj", [(f"P|ot|{m}|0", k) for m, k in _BIBLE_MODES]),
    "nt": ("nt", "S|inj", [(f"P|nt|{m}|0", k) for m, k in _BIBLE_MODES]),
    "tr": ("torah", "B", [(f"P|tr|{m}|0", k) for m, k in _BIBLE_MODES]),
}
_BIBLE_FLOW = {"b": ["work"], "c": ["work", "chapter"], "v": ["work", "chapter", "verse"],
               "t": ["author", "work", "chapter", "verse"]}
FLOWS = {
    "q": {"s": ["work"], "v": ["work", "verse"], "t": ["author", "work", "verse"],
          "rs": ["work", "reciter"], "rv": ["work", "verse", "reciter"]},
    "ot": _BIBLE_FLOW, "nt": _BIBLE_FLOW, "tr": _BIBLE_FLOW,
}
PAGING = {"work": (20, 2), "author": (10, 1), "reciter": (10, 1), "chapter": (48, 6), "verse": (48, 6)}


# ════════════════════════════════════════════════════════════════
# 6) دوال مساعدة
# ════════════════════════════════════════════════════════════════
def esc(s):
    return html.escape(str(s or ""))


def nkey(x):
    return (0, int(x)) if str(x).isdigit() else (1, str(x))


def sorted_ids(d):
    return sorted(d, key=nkey)


def dig(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
        if d is None:
            return None
    return d


def pick_name(names, lang):
    if isinstance(names, str):
        return names
    return names.get(lang) or names.get("en") or names.get("ar") or next(iter(names.values()), "?")


def ar_num(n):
    return str(n).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


def grid(btns, cols):
    return [btns[i:i + cols] for i in range(0, len(btns), cols)]


def pcb(book, mode, page, vals):
    return "|".join(["P", book, mode, str(page), *vals])


def parent_menu(book, mode):
    return "S|qr" if mode in ("rs", "rv") else f"S|{book}"


def copy_btn(lang, plain=""):
    label = "📋 " + tr(lang, "copy")
    if CopyTextButton and 0 < len(plain) <= 256:
        return Btn(label, copy_text=CopyTextButton(text=plain))
    return Btn(label, callback_data="C")


def chunk(lines, limit=3500):
    out, cur = [], ""
    for ln in lines:
        if cur and len(cur) + len(ln) + 2 > limit:
            out.append(cur)
            cur = ""
        cur += ("\n\n" if cur else "") + ln
    if cur:
        out.append(cur)
    return out


def split_text(s, limit=3300):
    """يقسّم نصاً طويلاً عند أقرب سطر/مسافة."""
    out = []
    while len(s) > limit:
        cut = max(s.rfind("\n", 0, limit), s.rfind(" ", 0, limit))
        cut = cut if cut > limit // 2 else limit
        out.append(s[:cut].strip())
        s = s[cut:].strip()
    if s:
        out.append(s)
    return out


async def show(q, text, rows, new=False):
    markup = Markup(rows)
    if new:
        await q.message.reply_text(text, reply_markup=markup, parse_mode=HTML)
    else:
        await q.edit_message_text(text, reply_markup=markup, parse_mode=HTML)


async def options(book, step, sel, lang, mode=""):
    """قائمة (id, label) للخطوة الحالية."""
    if book == "q":
        if step == "work":
            return [(str(s["number"]), f"{s['number']}. {surah_label(s, lang)}") for s in await surah_list()]
        if step == "verse":
            count = (await surah_list())[int(sel["work"]) - 1]["numberOfAyahs"]
            return [(str(i), str(i)) for i in range(1, count + 1)]
        if step == "author":
            return [(i, label) for i, label, _ in await tafsir_list(lang)]
        if step == "reciter":
            if mode == "rs":
                return [(k, v[0]) for k, v in SURAH_AUDIO.items()]
            return await verse_reciters(lang)
        return []
    b = LIB[book]
    if step == "author":
        return [(k, pick_name(a["name"], lang)) for k, a in b["tafsir"].items()]
    if step == "work":
        return [(k, f"{k}. {pick_name(b['works'][k]['name'], lang)}") for k in sorted_ids(b["works"])]
    if step == "chapter":
        return [(k, k) for k in sorted_ids(dig(b, "works", sel.get("work"), "text") or {})]
    if step == "verse":
        return [(k, k) for k in sorted_ids(dig(b, "works", sel.get("work"), "text", sel.get("chapter", "1")) or {})]
    return []


async def crumb(book, steps, vals, lang, mode):
    parts = [tr(lang, BOOK_KEY[book])]
    for i, v in enumerate(vals):
        sel = dict(zip(steps, vals[:i]))
        parts.append(dict(await options(book, steps[i], sel, lang, mode)).get(v, v))
    return " › ".join(parts)


# ════════════════════════════════════════════════════════════════
# 7) الأوامر والقوائم
# ════════════════════════════════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = grid([Btn(f"{flag} {name}", callback_data=f"L|{code}") for code, flag, name in LANGUAGES], 2)
    await update.effective_message.reply_text(tr("en", "pick_lang"), reply_markup=Markup(rows))


async def h_lang(q, ctx, lang, args):
    ctx.user_data["lang"] = args[0]
    await h_main(q, ctx, args[0], [])


async def h_main(q, ctx, lang, args):
    rows = [[Btn("📚 " + tr(lang, "books"), callback_data="B")]]
    rows += grid([Btn("🔒 " + tr(lang, "soon"), callback_data="SOON") for _ in range(9)], 3)
    await show(q, f"✨ <b>{esc(tr(lang, 'main'))}</b>", rows, new=args[:1] == ["n"])


async def h_books(q, ctx, lang, args):
    rows = [[Btn("🕌 " + tr(lang, "quran"), callback_data="S|q")],
            [Btn("✝️ " + tr(lang, "gospel"), callback_data="S|inj")],
            [Btn("✡️ " + tr(lang, "torah"), callback_data="S|tr")],
            [Btn("🔙 " + tr(lang, "back"), callback_data="M")]]
    await show(q, f"📚 <b>{esc(tr(lang, 'books'))}</b>", rows)


async def h_section(q, ctx, lang, args):
    title, back, items = MENUS[args[0]]
    rows = [[Btn("📖 " + tr(lang, key), callback_data=cb)] for cb, key in items]
    rows.append([Btn("🔙 " + tr(lang, "back"), callback_data=back), Btn("🏠 " + tr(lang, "home"), callback_data="M")])
    await show(q, f"<b>{esc(tr(lang, title))}</b>", rows)


# ════════════════════════════════════════════════════════════════
# 8) محرّك المسارات المتشعبة
# ════════════════════════════════════════════════════════════════
async def h_path(q, ctx, lang, args):
    book, mode, page, *vals = args
    steps = FLOWS[book][mode]
    await q.message.chat.send_action(ChatAction.TYPING)
    if len(vals) == len(steps):
        return await deliver(q, lang, book, mode, steps, vals)

    step = steps[len(vals)]
    items = await options(book, step, dict(zip(steps, vals)), lang, mode)
    size, cols = PAGING[step]
    pages = max(1, -(-len(items) // size))
    page = max(0, min(int(page), pages - 1))

    rows = grid([Btn(label, callback_data=pcb(book, mode, 0, [*vals, i]))
                 for i, label in items[page * size:(page + 1) * size]], cols)
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(Btn("◀️", callback_data=pcb(book, mode, page - 1, vals)))
        nav.append(Btn(f"{page + 1}/{pages}", callback_data="NOOP"))
        if page < pages - 1:
            nav.append(Btn("▶️", callback_data=pcb(book, mode, page + 1, vals)))
        rows.append(nav)
    back = pcb(book, mode, 0, vals[:-1]) if vals else parent_menu(book, mode)
    rows.append([Btn("🔙 " + tr(lang, "back"), callback_data=back), Btn("🏠 " + tr(lang, "home"), callback_data="M")])

    key = {"author": "pick_author", "reciter": "pick_reciter", "chapter": "pick_chapter",
           "verse": "pick_verse", "work": "pick_surah" if book == "q" else "pick_book"}[step]
    text = f"<i>{esc(await crumb(book, steps, vals, lang, mode))}</i>\n\n<b>{esc(tr(lang, key))}</b>"
    if not items:
        text += f"\n\n{esc(tr(lang, 'no_data'))}"
    await show(q, text, rows)


async def deliver(q, lang, book, mode, steps, vals):
    sel = dict(zip(steps, vals))
    if book == "q":
        if mode == "s":
            return await send_surah(q, lang, int(sel["work"]))
        if mode in ("v", "t"):
            return await show_quran_verse(q, lang, mode, steps, vals)
        return await send_quran_audio(q, lang, mode, steps, vals)
    if mode in ("b", "c"):
        wid = sel["work"]
        chapters = [sel["chapter"]] if mode == "c" else sorted_ids(LIB[book]["works"][wid]["text"])
        await send_local_work(q, lang, book, wid, chapters)
    else:
        await show_local_verse(q, lang, book, mode, steps, vals)


# ════════════════════════════════════════════════════════════════
# 9) القرآن (من الـ API)
# ════════════════════════════════════════════════════════════════
async def send_surah(q, lang, n):
    s = (await surah_list())[n - 1]
    ar, trn, info = await get_surah(n, lang)
    title = s["name"] if lang == "ar" else f"{s['name']} — {s['englishName']}"
    lines = []
    if n not in (1, 9):
        lines.append("بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ")
    for i, t in enumerate(ar, 1):
        line = f"{esc(t)} ﴿{ar_num(i)}﴾"
        if trn and trn[i - 1]:
            line += f"\n<i>{esc(trn[i - 1])}</i>"
        lines.append(line)
    parts = chunk(lines)
    parts[-1] += translation_footer(lang, info, trn)
    for i, part in enumerate(parts):
        text = (f"<b>{esc(title)}</b>\n\n" if i == 0 else "") + part
        rows = [[copy_btn(lang)]]
        if i == len(parts) - 1:
            rows.append([Btn("🏠 " + tr(lang, "home"), callback_data="M|n")])
        await q.message.reply_text(text, reply_markup=Markup(rows), parse_mode=HTML)
        await asyncio.sleep(0.4)


async def show_quran_verse(q, lang, mode, steps, vals):
    sel = dict(zip(steps, vals))
    n, v = int(sel["work"]), int(sel["verse"])
    s = (await surah_list())[n - 1]
    count = s["numberOfAyahs"]
    ref = f"{surah_label(s, lang)} : {v}"

    if mode == "t":
        txt = await tafsir_text(sel["author"], n, v)
        label = dict((i, lb) for i, lb, _ in await tafsir_list(lang)).get(sel["author"], "")
        footer = f"\n\n<i>{esc(tr(lang, 'source'))}: {esc(label)}</i>"
        plain = f"{txt}\n— {label}" if txt else ""
        raw = txt or tr(lang, "no_data")
    else:
        ar, trn, info = await get_surah(n, lang)
        raw = f"{ar[v - 1]} ﴿{ar_num(v)}﴾"
        plain = ar[v - 1]
        if trn and trn[v - 1]:
            raw_tr = trn[v - 1]
            plain += f"\n{raw_tr}"
        else:
            raw_tr = ""
        footer = translation_footer(lang, info, trn)

    vi = steps.index("verse")

    def go(j):
        nv = list(vals)
        nv[vi] = str(j)
        return pcb("q", mode, 0, nv)

    nav = []
    if v > 1:
        nav.append(Btn("‹ " + tr(lang, "prev"), callback_data=go(v - 1)))
    nav.append(copy_btn(lang, plain))
    if v < count:
        nav.append(Btn(tr(lang, "next") + " ›", callback_data=go(v + 1)))
    nav_rows = [nav, [Btn("🔙 " + tr(lang, "back"), callback_data=pcb("q", mode, 0, vals[:-1])),
                      Btn("🏠 " + tr(lang, "home"), callback_data="M|n")]]

    def compose(piece):
        body = esc(piece)
        if mode != "t" and raw_tr:
            body += f"\n<i>{esc(raw_tr)}</i>"
        return body

    pieces = split_text(raw)
    if mode != "t" or (len(pieces) == 1 and len(pieces[0]) + len(footer) + len(ref) < 3800):
        text = f"📖 <b>{esc(ref)}</b>\n\n{compose(pieces[0])}{footer}"
        return await show(q, text, nav_rows)
    # تفسير طويل: عدة رسائل، وشريط التنقل في آخرها
    for i, piece in enumerate(pieces):
        last = i == len(pieces) - 1
        text = (f"📖 <b>{esc(ref)}</b>\n\n" if i == 0 else "") + esc(piece) + (footer if last else "")
        await q.message.reply_text(text, reply_markup=Markup(nav_rows if last else [[copy_btn(lang)]]),
                                   parse_mode=HTML)
        await asyncio.sleep(0.4)


async def send_quran_audio(q, lang, mode, steps, vals):
    sel = dict(zip(steps, vals))
    n = int(sel["work"])
    reciter = sel["reciter"]
    performer = dict(await options("q", "reciter", sel, lang, mode)).get(reciter, reciter)
    if mode == "rs":
        url = SURAH_AUDIO[reciter][1].format(s=n)
    else:
        url = await verse_audio_url(reciter, n, int(sel["verse"]))
    try:  # الرابط المباشر يعمل حتى ~20MB؛ للملفات الأكبر ارفعها وخزّن file_id
        await q.message.reply_audio(audio=url, caption=await crumb("q", steps, vals, lang, mode),
                                    performer=performer)
    except Exception as e:  # noqa: BLE001
        logging.warning("audio failed: %s", e)
        await q.message.reply_text(f"{tr(lang, 'audio_fail')}\n{url}")


# ════════════════════════════════════════════════════════════════
# 10) الإنجيل والتوراة (محلي)
# ════════════════════════════════════════════════════════════════
def local_verse_block(book, wid, ch, v, lang):
    b = LIB[book]
    base = dig(b, "works", wid, "text", ch, v) or ""
    trn = dig(b, "translations", lang, wid, ch, v) if lang != b["base_lang"] else None
    line = f"<b>{v}</b> {esc(base)}" + (f"\n<i>{esc(trn)}</i>" if trn else "")
    return line, base + (f"\n{trn}" if trn else "")


async def send_local_work(q, lang, book, wid, chapters):
    w = LIB[book]["works"][wid]
    title = pick_name(w["name"], lang)
    lines = []
    for ch in chapters:
        lines.append(f"<b>— {esc(title)} {ch} —</b>")
        lines += [local_verse_block(book, wid, ch, v, lang)[0] for v in sorted_ids(w["text"][ch])]
    parts = chunk(lines)
    for i, part in enumerate(parts):
        rows = [[copy_btn(lang)]]
        if i == len(parts) - 1:
            rows.append([Btn("🏠 " + tr(lang, "home"), callback_data="M|n")])
        await q.message.reply_text(part, reply_markup=Markup(rows), parse_mode=HTML)
        await asyncio.sleep(0.4)


async def show_local_verse(q, lang, book, mode, steps, vals):
    sel = dict(zip(steps, vals))
    b = LIB[book]
    wid, ch, v = sel["work"], sel.get("chapter", "1"), sel["verse"]
    ref = f"{pick_name(b['works'][wid]['name'], lang)} {ch}:{v}"
    if mode == "t":
        a = b["tafsir"][sel["author"]]
        txt = dig(a, "data", wid, ch, v)
        author = pick_name(a["name"], lang)
        body = esc(txt) if txt else f"<i>{esc(tr(lang, 'no_data'))}</i>"
        body += f"\n\n<i>{esc(tr(lang, 'source'))}: {esc(author)} — {esc(a.get('source', ''))}</i>"
        plain = f"{txt}\n— {author}، {a.get('source', '')}" if txt else ""
    else:
        body, plain = local_verse_block(book, wid, ch, v, lang)
    vi = steps.index("verse")
    ids = sorted_ids(dig(b, "works", wid, "text", ch) or {})
    i = ids.index(v)

    def go(j):
        nv = list(vals)
        nv[vi] = ids[j]
        return pcb(book, mode, 0, nv)

    nav = []
    if i > 0:
        nav.append(Btn("‹ " + tr(lang, "prev"), callback_data=go(i - 1)))
    nav.append(copy_btn(lang, plain))
    if i < len(ids) - 1:
        nav.append(Btn(tr(lang, "next") + " ›", callback_data=go(i + 1)))
    rows = [nav, [Btn("🔙 " + tr(lang, "back"), callback_data=pcb(book, mode, 0, vals[:-1])),
                  Btn("🏠 " + tr(lang, "home"), callback_data="M|n")]]
    await show(q, f"📖 <b>{esc(ref)}</b>\n\n{body}", rows)


# ════════════════════════════════════════════════════════════════
# 11) الموجّه الموحّد وتشغيل البوت
# ════════════════════════════════════════════════════════════════
async def h_copy(q, ctx, lang, args):
    await q.message.reply_text(f"<pre>{esc((q.message.text or '')[:3500])}</pre>", parse_mode=HTML)


async def h_soon(q, ctx, lang, args):
    await q.answer("🔒 " + tr(lang, "soon"))


async def h_noop(q, ctx, lang, args):
    pass


ROUTES = {"L": h_lang, "M": h_main, "B": h_books, "S": h_section, "P": h_path,
          "C": h_copy, "SOON": h_soon, "NOOP": h_noop}


async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    route, *args = q.data.split("|")
    lang = ctx.user_data.get("lang")
    if route != "SOON":
        await q.answer()
    if route != "L" and not lang:
        rows = grid([Btn(f"{f} {n}", callback_data=f"L|{c}") for c, f, n in LANGUAGES], 2)
        return await q.message.reply_text(tr("en", "pick_lang"), reply_markup=Markup(rows))
    handler = ROUTES.get(route)
    if not handler:
        return
    try:
        await handler(q, ctx, lang, args)
    except ApiError as e:
        logging.warning("API error on %s: %s", q.data, e)
        await q.message.reply_text(tr(lang, "api_error"))
    except Exception:  # noqa: BLE001
        logging.exception("callback failed: %s", q.data)


async def on_start(app):
    global HTTP
    HTTP = httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True,
                             headers={"User-Agent": "HeavenlyBooksBot/1.0"})
    try:  # تسخين الكاش
        await surah_list()
    except ApiError as e:
        logging.warning("warm-up failed: %s", e)


async def on_stop(app):
    if HTTP:
        await HTTP.aclose()


def main():
    load_external_data()
    app = (Application.builder().token(BOT_TOKEN)
           .persistence(PicklePersistence(filepath="bot_persistence.pkl"))
           .concurrent_updates(True)
           .post_init(on_start).post_shutdown(on_stop).build())
    app.add_handler(CommandHandler(["start", "language"], start))
    app.add_handler(CallbackQueryHandler(router))
    app.run_polling()


# ════════════════════════════════════════════════════════════════
# ⬇️⬇️⬇️  ضع توكن البوت هنا (من @BotFather)  ⬇️⬇️⬇️
BOT_TOKEN = "8557537768:AAEAVEsf6VbTa3TrphqPUwf16QOVcOolnE8"
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
