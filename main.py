#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت تيليجرام: مكتبة وأرشيف الكتب السماوية
python-telegram-bot >= 20  (يُفضّل 21.8+ لدعم زر النسخ المباشر CopyTextButton)

التثبيت:   pip install "python-telegram-bot>=21.8"
التشغيل:   ضع التوكن في آخر الملف (BOT_TOKEN) ثم:  python books_bot.py

بنية callback_data (أقل من 64 بايت):
  L|<lang>                       اختيار لغة
  M | M|n                        القائمة الرئيسية (تعديل | رسالة جديدة)
  B                              قائمة الكتب (قرآن / إنجيل / توراة)
  S|<menu>                       قوائم فرعية (q, qr, inj, ot, nt, tr)
  P|<book>|<mode>|<page>|v1|v2   مسار الاختيارات المتشعب (سورة > آية > ...)
  C                              نسخ احتياطي (يرسل النص داخل كتلة code)
"""
import asyncio
import html
import json
import logging
from pathlib import Path

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Markup
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, PicklePersistence)

try:  # زر النسخ المباشر (Bot API 7.11+ / PTB 21.8+)
    from telegram import CopyTextButton
except ImportError:  # نسخة أقدم: نستخدم البديل
    CopyTextButton = None

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
HTML = ParseMode.HTML

# ════════════════════════════════════════════════════════════════
# 1) اللغات العشرون (الاسم بلغته + العلم)
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

# ════════════════════════════════════════════════════════════════
# 2) نصوص الواجهة (أضف لغة جديدة بنسخ قاموس "en" وترجمته؛ الناقص يرجع للإنجليزية)
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
        source="المصدر", no_data="لا توجد بيانات متاحة بعد", audio_fail="تعذّر إرسال الملف الصوتي، رابطه:"),
    "en": dict(
        pick_lang="🌐 اختر لغتك / Choose your language", main="Main menu", soon="Coming soon",
        books="Heavenly Books", quran="The Holy Quran", gospel="The Gospel", torah="The Torah",
        surahs="Surahs", verses="Verses", tafsir="Tafsir / Commentary", recitations="Recitations",
        recite_surahs="Recite surahs", recite_verses="Recite verses",
        ot="Old Testament", nt="New Testament", books_list="Books", chapters="Chapters",
        pick_surah="Choose a surah", pick_book="Choose a book", pick_chapter="Choose a chapter",
        pick_verse="Choose a verse", pick_author="Choose a commentator", pick_reciter="Choose a reciter",
        back="Back", home="Home", copy="Copy", prev="Previous", next="Next",
        source="Source", no_data="No data available yet", audio_fail="Could not send the audio, link:"),
    "he": dict(
        pick_lang="🌐 اختر لغتك / Choose your language", main="התפריט הראשי", soon="בקרוב",
        books="הספרים הקדושים", quran="הקוראן", gospel="הבשורה", torah="התורה",
        surahs="סורות", verses="פסוקים", tafsir="פרשנות", recitations="דקלום",
        recite_surahs="דקלום סורות", recite_verses="דקלום פסוקים",
        ot="הברית הישנה", nt="הברית החדשה", books_list="ספרים", chapters="פרקים",
        pick_surah="בחר סורה", pick_book="בחר ספר", pick_chapter="בחר פרק",
        pick_verse="בחר פסוק", pick_author="בחר מפרש", pick_reciter="בחר קורא",
        back="חזרה", home="ראשי", copy="העתק", prev="הקודם", next="הבא",
        source="מקור", no_data="אין נתונים זמינים עדיין", audio_fail="לא ניתן לשלוח את הקובץ, קישור:"),
}


def tr(lang, key):
    return UI.get(lang, {}).get(key) or UI["en"][key]


# ════════════════════════════════════════════════════════════════
# 3) قاعدة البيانات (عيّنات صغيرة — غذِّها لاحقاً هنا أو عبر ملفات JSON في مجلد data/)
#
#   LIB[book]["works"][work_id]["text"][chapter_id][verse_id] = "النص"
#   - القرآن: الفصل دائماً "1" (السورة = work)
#   - النصوص بلغتها الأصلية base_lang، والترجمات في translations[lang][work][chapter][verse]
#   - التفاسير: tafsir[author_id] = {name, source, data[work][chapter][verse]}
#   كل المعرّفات نصوص ("1","2",...). الكتب: q=القرآن، ot/nt=العهدان، tr=التوراة
#   لتحميل ملف خارجي: data/q.json أو data/ot.json ... بنفس البنية (يُدمج تلقائياً)
# ════════════════════════════════════════════════════════════════
LIB = {
    "q": {
        "base_lang": "ar",
        "works": {
            "1": {"name": {"ar": "الفاتحة", "en": "Al-Fatiha", "he": "אל-פאתחה"}, "text": {"1": {
                "1": "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ",
                "2": "الْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ",
                "3": "الرَّحْمَٰنِ الرَّحِيمِ",
                "4": "مَالِكِ يَوْمِ الدِّينِ",
                "5": "إِيَّاكَ نَعْبُدُ وَإِيَّاكَ نَسْتَعِينُ",
                "6": "اهْدِنَا الصِّرَاطَ الْمُسْتَقِيمَ",
                "7": "صِرَاطَ الَّذِينَ أَنْعَمْتَ عَلَيْهِمْ غَيْرِ الْمَغْضُوبِ عَلَيْهِمْ وَلَا الضَّالِّينَ"}}},
            "112": {"name": {"ar": "الإخلاص", "en": "Al-Ikhlas", "he": "אל-אח'לאץ'"}, "text": {"1": {
                "1": "قُلْ هُوَ اللَّهُ أَحَدٌ",
                "2": "اللَّهُ الصَّمَدُ",
                "3": "لَمْ يَلِدْ وَلَمْ يُولَدْ",
                "4": "وَلَمْ يَكُن لَّهُ كُفُوًا أَحَدٌ"}}},
        },
        # مثال: "translations": {"en": {"1": {"1": {"1": "In the name of ..."}}}}
        "translations": {},
        "tafsir": {
            "sample": {"name": {"ar": "تفسير تجريبي", "en": "Sample tafsir"}, "source": "—",
                       "data": {"1": {"1": {"1": "نص تجريبي: استبدله بنص التفسير الحقيقي ومصدره."}}}},
        },
    },
    "ot": {
        "base_lang": "en",  # غيّرها إلى "ar" عند تحميل ترجمة عربية كنص أساسي
        "works": {"1": {"name": {"ar": "التكوين", "en": "Genesis", "he": "בראשית"}, "text": {"1": {
            "1": "In the beginning God created the heaven and the earth.",
            "2": "And the earth was without form, and void; and darkness was upon the face of the deep. "
                 "And the Spirit of God moved upon the face of the waters.",
            "3": "And God said, Let there be light: and there was light."}}}},
        "translations": {}, "tafsir": {},
    },
    "nt": {
        "base_lang": "en",
        "works": {"4": {"name": {"ar": "يوحنا", "en": "John", "he": "יוחנן"}, "text": {"1": {
            "1": "In the beginning was the Word, and the Word was with God, and the Word was God.",
            "2": "The same was in the beginning with God.",
            "3": "All things were made by him; and without him was not any thing made that was made."}}}},
        "translations": {}, "tafsir": {},
    },
    "tr": {
        "base_lang": "he",
        "works": {"1": {"name": {"ar": "التكوين", "en": "Genesis", "he": "בראשית"}, "text": {"1": {
            "1": "בְּרֵאשִׁית בָּרָא אֱלֹהִים אֵת הַשָּׁמַיִם וְאֵת הָאָרֶץ",
            "2": "וְהָאָרֶץ הָיְתָה תֹהוּ וָבֹהוּ וְחֹשֶׁךְ עַל־פְּנֵי תְהוֹם וְרוּחַ אֱלֹהִים מְרַחֶפֶת עַל־פְּנֵי הַמָּיִם",
            "3": "וַיֹּאמֶר אֱלֹהִים יְהִי אוֹר וַיְהִי־אוֹר"}}}},
        "translations": {}, "tafsir": {},
    },
}

# القرّاء: قوالب روابط (تحقق من صلاحية الروابط، أو استبدلها بـ file_id/ملفاتك الخاصة)
RECITERS = {
    "afs": {"name": {"ar": "مشاري العفاسي", "en": "Mishary Alafasy"},
            "surah_url": "https://server8.mp3quran.net/afs/{s:03d}.mp3",
            "verse_url": "https://everyayah.com/data/Alafasy_128kbps/{s:03d}{v:03d}.mp3"},
    "hus": {"name": {"ar": "محمود خليل الحصري", "en": "Mahmoud Khalil Al-Husary"},
            "surah_url": "https://server13.mp3quran.net/husr/{s:03d}.mp3",
            "verse_url": "https://everyayah.com/data/Husary_128kbps/{s:03d}{v:03d}.mp3"},
}


def deep_update(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v


def load_external_data(folder="data"):
    """يدمج data/<book>.json داخل LIB وdata/reciters.json داخل RECITERS إن وُجدت."""
    for book in LIB:
        f = Path(folder) / f"{book}.json"
        if f.exists():
            deep_update(LIB[book], json.loads(f.read_text("utf-8")))
    f = Path(folder) / "reciters.json"
    if f.exists():
        deep_update(RECITERS, json.loads(f.read_text("utf-8")))


# ════════════════════════════════════════════════════════════════
# 4) تعريف القوائم والمسارات (للتوسع: عدّل هذه الجداول فقط)
# ════════════════════════════════════════════════════════════════
BOOK_KEY = {"q": "quran", "ot": "ot", "nt": "nt", "tr": "torah"}

MENUS = {  # مفتاح القائمة: (عنوان, رجوع, [(callback, مفتاح النص)])
    "q": ("quran", "B", [("P|q|s|0", "surahs"), ("P|q|v|0", "verses"),
                         ("P|q|t|0", "tafsir"), ("S|qr", "recitations")]),
    "qr": ("recitations", "S|q", [("P|q|rs|0", "recite_surahs"), ("P|q|rv|0", "recite_verses")]),
    "inj": ("gospel", "B", [("S|ot", "ot"), ("S|nt", "nt")]),
    "ot": ("ot", "S|inj", [(f"P|ot|{m}|0", k) for m, k in
                           (("b", "books_list"), ("c", "chapters"), ("v", "verses"), ("t", "tafsir"))]),
    "nt": ("nt", "S|inj", [(f"P|nt|{m}|0", k) for m, k in
                           (("b", "books_list"), ("c", "chapters"), ("v", "verses"), ("t", "tafsir"))]),
    "tr": ("torah", "B", [(f"P|tr|{m}|0", k) for m, k in
                          (("b", "books_list"), ("c", "chapters"), ("v", "verses"), ("t", "tafsir"))]),
}

_BIBLE_FLOW = {"b": ["work"], "c": ["work", "chapter"], "v": ["work", "chapter", "verse"],
               "t": ["author", "work", "chapter", "verse"]}
FLOWS = {  # خطوات الاختيار لكل وضع
    "q": {"s": ["work"], "v": ["work", "verse"], "t": ["author", "work", "verse"],
          "rs": ["work", "reciter"], "rv": ["work", "verse", "reciter"]},
    "ot": _BIBLE_FLOW, "nt": _BIBLE_FLOW, "tr": _BIBLE_FLOW,
}

PAGING = {"work": (20, 2), "author": (10, 1), "reciter": (10, 1), "chapter": (48, 6), "verse": (48, 6)}


# ════════════════════════════════════════════════════════════════
# 5) دوال مساعدة
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
    """زر النسخ: مباشر (copy_text) إن أمكن، وإلا يرسل النص داخل كتلة code للنسخ بلمسة."""
    label = "📋 " + tr(lang, "copy")
    if CopyTextButton and 0 < len(plain) <= 256:
        return Btn(label, copy_text=CopyTextButton(text=plain))
    return Btn(label, callback_data="C")


def verse_block(book, wid, ch, v, lang):
    """يعيد (نص HTML، نص عادي) للآية: الأصل + الترجمة إن وجدت."""
    b = LIB[book]
    base = dig(b, "works", wid, "text", ch, v) or ""
    trn = dig(b, "translations", lang, wid, ch, v) if lang != b["base_lang"] else None
    line = f"{esc(base)} ﴿{ar_num(v)}﴾" if book == "q" else f"<b>{v}</b> {esc(base)}"
    if trn:
        line += f"\n<i>{esc(trn)}</i>"
    return line, base + (f"\n{trn}" if trn else "")


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


def options(book, step, sel, lang):
    """قائمة (id, label) للخطوة الحالية بحسب الاختيارات السابقة."""
    b = LIB[book]
    if step == "author":
        return [(k, pick_name(a["name"], lang)) for k, a in b["tafsir"].items()]
    if step == "reciter":
        return [(k, pick_name(r["name"], lang)) for k, r in RECITERS.items()]
    if step == "work":
        return [(k, f"{k}. {pick_name(b['works'][k]['name'], lang)}") for k in sorted_ids(b["works"])]
    if step == "chapter":
        return [(k, k) for k in sorted_ids(dig(b, "works", sel.get("work"), "text") or {})]
    if step == "verse":
        ch = sel.get("chapter", "1")
        return [(k, k) for k in sorted_ids(dig(b, "works", sel.get("work"), "text", ch) or {})]
    return []


def crumb(book, steps, vals, lang):
    parts = [tr(lang, BOOK_KEY[book])]
    for i, v in enumerate(vals):
        sel = dict(zip(steps, vals[:i]))
        parts.append(dict(options(book, steps[i], sel, lang)).get(v, v))
    return " › ".join(parts)


async def show(q, text, rows, new=False):
    markup = Markup(rows)
    if new:
        await q.message.reply_text(text, reply_markup=markup, parse_mode=HTML)
    else:
        await q.edit_message_text(text, reply_markup=markup, parse_mode=HTML)


# ════════════════════════════════════════════════════════════════
# 6) الأوامر والقوائم
# ════════════════════════════════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = grid([Btn(f"{flag} {name}", callback_data=f"L|{code}") for code, flag, name in LANGUAGES], 2)
    await update.effective_message.reply_text(tr("en", "pick_lang"), reply_markup=Markup(rows))


async def h_lang(q, ctx, lang, args):
    ctx.user_data["lang"] = args[0]  # حفظ لغة المستخدم (مستمرة عبر PicklePersistence)
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
# 7) محرّك المسارات المتشعبة (سورة/سفر > إصحاح > آية > مفسّر > قارئ)
# ════════════════════════════════════════════════════════════════
async def h_path(q, ctx, lang, args):
    book, mode, page, *vals = args
    steps = FLOWS[book][mode]
    if len(vals) == len(steps):
        return await deliver(q, lang, book, mode, steps, vals)

    step = steps[len(vals)]
    sel = dict(zip(steps, vals))
    items = options(book, step, sel, lang)
    size, cols = PAGING[step]
    page = max(0, min(int(page), max(0, (len(items) - 1) // size)))
    pages = max(1, -(-len(items) // size))

    btns = [Btn(label, callback_data=pcb(book, mode, 0, [*vals, i])) for i, label in items[page * size:(page + 1) * size]]
    rows = grid(btns, cols)
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
    text = f"<i>{esc(crumb(book, steps, vals, lang))}</i>\n\n<b>{esc(tr(lang, key))}</b>"
    if not items:
        text += f"\n\n{esc(tr(lang, 'no_data'))}"
    await show(q, text, rows)


async def deliver(q, lang, book, mode, steps, vals):
    sel = dict(zip(steps, vals))
    if mode in ("s", "b", "c"):
        wid = sel["work"]
        text_tree = LIB[book]["works"][wid]["text"]
        chapters = [sel["chapter"]] if mode == "c" else sorted_ids(text_tree)
        await send_work(q, lang, book, wid, chapters)
    elif mode in ("v", "t"):
        await show_verse(q, lang, book, mode, steps, vals)
    else:  # rs / rv
        await send_recitation(q, lang, book, mode, steps, vals)


async def send_work(q, lang, book, wid, chapters):
    """يرسل سورة/سفر/إصحاح كاملاً (مقسّماً على رسائل عند الطول)."""
    w = LIB[book]["works"][wid]
    title = pick_name(w["name"], lang)
    lines = []
    for ch in chapters:
        if book != "q":
            lines.append(f"<b>— {esc(title)} {ch} —</b>")
        lines += [verse_block(book, wid, ch, v, lang)[0] for v in sorted_ids(w["text"][ch])]
    parts = chunk(lines)
    for i, part in enumerate(parts):
        text = (f"<b>{esc(title)}</b>\n\n" if i == 0 and book == "q" else "") + part
        rows = [[copy_btn(lang)]]
        if i == len(parts) - 1:
            rows.append([Btn("🏠 " + tr(lang, "home"), callback_data="M|n")])
        await q.message.reply_text(text, reply_markup=Markup(rows), parse_mode=HTML)
        await asyncio.sleep(0.4)  # تجنّب حدّ الإرسال


async def show_verse(q, lang, book, mode, steps, vals):
    """آية أو تفسير آية + شريط تنقل [‹ السابقة | نسخ | التالية ›] يعدّل نفس الرسالة."""
    sel = dict(zip(steps, vals))
    b = LIB[book]
    wid, ch, v = sel["work"], sel.get("chapter", "1"), sel["verse"]
    name = pick_name(b["works"][wid]["name"], lang)
    ref = f"{name} : {v}" if book == "q" else f"{name} {ch}:{v}"

    if mode == "t":
        a = b["tafsir"][sel["author"]]
        txt = dig(a, "data", wid, ch, v)
        author = pick_name(a["name"], lang)
        body = esc(txt) if txt else f"<i>{esc(tr(lang, 'no_data'))}</i>"
        body += f"\n\n<i>{esc(tr(lang, 'source'))}: {esc(author)} — {esc(a.get('source', ''))}</i>"
        plain = f"{txt}\n— {author}، {a.get('source', '')}" if txt else ""
    else:
        body, plain = verse_block(book, wid, ch, v, lang)

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


async def send_recitation(q, lang, book, mode, steps, vals):
    sel = dict(zip(steps, vals))
    rec = RECITERS[sel["reciter"]]
    tpl = rec["surah_url"] if mode == "rs" else rec["verse_url"]
    url = tpl.format(s=int(sel["work"]), v=int(sel.get("verse", 0)))
    try:  # تيليجرام يقبل روابط حتى ~20MB؛ للملفات الأكبر ارفعها واحفظ file_id
        await q.message.reply_audio(audio=url, caption=crumb(book, steps, vals, lang),
                                    performer=pick_name(rec["name"], lang))
    except Exception as e:  # noqa: BLE001
        logging.warning("audio failed: %s", e)
        await q.message.reply_text(f"{tr(lang, 'audio_fail')}\n{url}")


async def h_copy(q, ctx, lang, args):
    """بديل النسخ: النص داخل كتلة code (لمسة واحدة تنسخه)."""
    await q.message.reply_text(f"<pre>{esc((q.message.text or '')[:3500])}</pre>", parse_mode=HTML)


async def h_soon(q, ctx, lang, args):
    await q.answer("🔒 " + tr(lang, "soon"))


async def h_noop(q, ctx, lang, args):
    pass


# ════════════════════════════════════════════════════════════════
# 8) الموجّه الموحّد لكل الأزرار
# ════════════════════════════════════════════════════════════════
ROUTES = {"L": h_lang, "M": h_main, "B": h_books, "S": h_section, "P": h_path,
          "C": h_copy, "SOON": h_soon, "NOOP": h_noop}


async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    route, *args = q.data.split("|")
    lang = ctx.user_data.get("lang")
    if route != "SOON":
        await q.answer()
    if route != "L" and not lang:  # لا لغة محفوظة → اطلب اختيارها
        rows = grid([Btn(f"{f} {n}", callback_data=f"L|{c}") for c, f, n in LANGUAGES], 2)
        return await q.message.reply_text(tr("en", "pick_lang"), reply_markup=Markup(rows))
    handler = ROUTES.get(route)
    if handler:
        try:
            await handler(q, ctx, lang, args)
        except Exception:  # noqa: BLE001
            logging.exception("callback failed: %s", q.data)


def main():
    load_external_data()
    persistence = PicklePersistence(filepath="bot_persistence.pkl")
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()
    app.add_handler(CommandHandler(["start", "language"], start))
    app.add_handler(CallbackQueryHandler(router))
    app.run_polling()


# ════════════════════════════════════════════════════════════════
# ⬇️⬇️⬇️  ضع توكن البوت هنا (من @BotFather)  ⬇️⬇️⬇️
BOT_TOKEN = "8557537768:AAEAVEsf6VbTa3TrphqPUwf16QOVcOolnE8"
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
