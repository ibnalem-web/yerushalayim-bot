#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت تيليجرام: مكتبة وأرشيف الكتب السماوية  (main.py — الإصدار 3)
python-telegram-bot >= 20 (يُفضّل 21.8+ لزر النسخ المباشر) + httpx (يُثبَّت تلقائياً مع المكتبة)

كل النصوص تُجلب حيّة من واجهات API (لا توجد نصوص محلية):
  القرآن   : https://api.alquran.cloud/v1  (+ احتياطي https://api.quran.com/api/v4)
  التوراة  : https://www.sefaria.org/api   (النص العبري + التفاسير: راشي، ابن عزرا، رمبان...)
  الإنجيل والعهدان القديم والجديد (الأسفار/الإصحاحات/الآيات): https://api.getbible.net/v2
  تفاسير الكتاب المقدس: https://bible.helloao.org/api  (إن توفّرت)

التشغيل:  pip install "python-telegram-bot>=21.8"   ثم ضع التوكن في آخر الملف و:  python main.py

بنية callback_data (أقل من 64 بايت):
  L|<lang> | M | M|n | B | S|<menu> | C | K|<book>|<nr>|<chapter> | SOON | NOOP
  P|<book>|<mode>|<page>|v1|v2|...   مسار الاختيارات (سورة/سفر > إصحاح > آية > مفسّر > قارئ)
  book: q=القرآن، ot=العهد القديم، nt=العهد الجديد، tr=التوراة
"""
import asyncio
import html
import logging
import re
import time

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
# اسم اللغة بالإنجليزية (يُستخدم لمطابقة الترجمات في الواجهات الخارجية)
LANG_NAME = {
    "ar": "arabic", "he": "hebrew", "en": "english", "syr": "syriac", "fr": "french", "es": "spanish",
    "de": "german", "it": "italian", "pt": "portuguese", "ru": "russian", "tr": "turkish",
    "fa": "persian", "ur": "urdu", "hi": "hindi", "id": "indonesian", "zh": "chinese",
    "ja": "japanese", "ko": "korean", "el": "greek", "nl": "dutch",
}
LANG_ALIASES = {"fa": ("persian", "farsi"), "id": ("indonesian", "bahasa"), "zh": ("chinese", "mandarin"),
                "he": ("hebrew",), "el": ("greek",), "syr": ("syriac", "aramaic")}
NAME_LANG = {v: k for k, v in LANG_NAME.items()}
# سلسلة البدائل عند غياب ترجمة بلغة المستخدم (تظهر معها رسالة تنبيه)
FALLBACK_CHAIN = {"syr": ["syr", "ar", "en"]}


def lang_chain(lang):
    chain = FALLBACK_CHAIN.get(lang, [lang, "en"])
    return list(dict.fromkeys(chain))


# ترجمات القرآن المفضّلة (alquran.cloud) — إن لم تُوجد يُؤخذ أول إصدار متاح للغة
PREFERRED_TRANSLATION = {
    "en": "en.sahih", "fr": "fr.hamidullah", "es": "es.cortes", "de": "de.aburida", "ru": "ru.kuliev",
    "tr": "tr.diyanet", "ur": "ur.jalandhry", "id": "id.indonesian", "zh": "zh.jian",
    "ja": "ja.japanese", "ko": "ko.korean", "it": "it.piccardo", "nl": "nl.keyzer",
    "pt": "pt.elhayek", "hi": "hi.hindi", "fa": "fa.makarem",
}
# ترجمات الكتاب المقدس المفضّلة (getBible) — إن لم تُوجد يُؤخذ المتاح للغة
PREFERRED_BIBLE = {
    "ar": "arabicsv", "en": "kjv", "fr": "ls1910", "es": "valera", "de": "luther1912",
    "it": "giovanni", "pt": "almeida", "ru": "synodal", "nl": "statenvertaling",
}

# ════════════════════════════════════════════════════════════════
# 2) نصوص الواجهة لكل اللغات (الناقص يرجع للإنجليزية؛ السريانية تعرض الواجهة العربية)
# ════════════════════════════════════════════════════════════════
PICK_LANG = "🌐 اختر لغتك / Choose your language"
UI_FALLBACK = {"syr": "ar"}
UI = {
    "ar": dict(main="القائمة الرئيسية", soon="قريباً", books="الكتب السماوية", quran="القرآن الكريم",
               gospel="الإنجيل", torah="التوراة", surahs="السور", verses="الآيات", tafsir="التفسير",
               recitations="التلاوات", ot="العهد القديم", nt="العهد الجديد", books_list="الأسفار",
               chapters="الإصحاحات", pick_surah="اختر السورة", pick_book="اختر السفر",
               pick_chapter="اختر الإصحاح", pick_verse="اختر رقم الآية", pick_author="اختر المفسّر",
               pick_reciter="اختر القارئ", back="رجوع", home="الرئيسية", copy="نسخ",
               prev="الآية السابقة", next="الآية التالية", source="المصدر",
               no_data="لا توجد بيانات متاحة لهذا الطلب", audio_fail="تعذّر إرسال الملف الصوتي، رابطه:",
               api_error="⚠️ تعذّر الاتصال بالخادم، حاول مرة أخرى بعد قليل.",
               fallback="(لا توجد ترجمة بلغتك؛ عُرضت لغة بديلة)", more="متابعة"),
    "en": dict(main="Main menu", soon="Coming soon", books="Heavenly Books", quran="The Holy Quran",
               gospel="The Gospel", torah="The Torah", surahs="Surahs", verses="Verses",
               tafsir="Tafsir / Commentary", recitations="Recitations", ot="Old Testament",
               nt="New Testament", books_list="Books", chapters="Chapters", pick_surah="Choose a surah",
               pick_book="Choose a book", pick_chapter="Choose a chapter", pick_verse="Choose a verse",
               pick_author="Choose a commentator", pick_reciter="Choose a reciter", back="Back",
               home="Home", copy="Copy", prev="Previous", next="Next", source="Source",
               no_data="No data available for this request", audio_fail="Could not send the audio, link:",
               api_error="⚠️ Could not reach the server, please try again shortly.",
               fallback="(no translation in your language; another language is shown)", more="Continue"),
    "he": dict(main="התפריט הראשי", soon="בקרוב", books="הספרים הקדושים", quran="הקוראן",
               gospel="הבשורה", torah="התורה", surahs="סורות", verses="פסוקים", tafsir="פרשנות",
               recitations="דקלום", ot="הברית הישנה", nt="הברית החדשה", books_list="ספרים",
               chapters="פרקים", pick_surah="בחר סורה", pick_book="בחר ספר", pick_chapter="בחר פרק",
               pick_verse="בחר פסוק", pick_author="בחר מפרש", pick_reciter="בחר קורא", back="חזרה",
               home="ראשי", copy="העתק", prev="הקודם", next="הבא", source="מקור",
               no_data="אין נתונים זמינים לבקשה זו", audio_fail="לא ניתן לשלוח את הקובץ, קישור:",
               api_error="⚠️ לא ניתן להתחבר לשרת, נסה שוב בעוד מעט.",
               fallback="(אין תרגום בשפתך; מוצגת שפה חלופית)", more="המשך"),
    "fr": dict(main="Menu principal", soon="Bientôt", books="Livres sacrés", quran="Le Saint Coran",
               gospel="L'Évangile", torah="La Torah", surahs="Sourates", verses="Versets",
               tafsir="Tafsir / Commentaire", recitations="Récitations", ot="Ancien Testament",
               nt="Nouveau Testament", books_list="Livres", chapters="Chapitres",
               pick_surah="Choisissez une sourate", pick_book="Choisissez un livre",
               pick_chapter="Choisissez un chapitre", pick_verse="Choisissez un verset",
               pick_author="Choisissez un commentateur", pick_reciter="Choisissez un récitateur",
               back="Retour", home="Accueil", copy="Copier", prev="Précédent", next="Suivant",
               source="Source", no_data="Aucune donnée disponible pour cette demande",
               audio_fail="Impossible d'envoyer l'audio, lien :",
               api_error="⚠️ Serveur injoignable, réessayez dans un instant.",
               fallback="(pas de traduction dans votre langue ; une autre langue est affichée)", more="Suite"),
    "es": dict(main="Menú principal", soon="Próximamente", books="Libros sagrados", quran="El Sagrado Corán",
               gospel="El Evangelio", torah="La Torá", surahs="Suras", verses="Versículos",
               tafsir="Tafsir / Comentario", recitations="Recitaciones", ot="Antiguo Testamento",
               nt="Nuevo Testamento", books_list="Libros", chapters="Capítulos",
               pick_surah="Elige una sura", pick_book="Elige un libro", pick_chapter="Elige un capítulo",
               pick_verse="Elige un versículo", pick_author="Elige un comentarista",
               pick_reciter="Elige un recitador", back="Atrás", home="Inicio", copy="Copiar",
               prev="Anterior", next="Siguiente", source="Fuente",
               no_data="No hay datos disponibles para esta solicitud",
               audio_fail="No se pudo enviar el audio, enlace:",
               api_error="⚠️ No se pudo conectar con el servidor, inténtalo de nuevo en un momento.",
               fallback="(no hay traducción en tu idioma; se muestra otro idioma)", more="Continuar"),
    "de": dict(main="Hauptmenü", soon="Demnächst", books="Heilige Bücher", quran="Der Heilige Koran",
               gospel="Das Evangelium", torah="Die Tora", surahs="Suren", verses="Verse",
               tafsir="Tafsir / Kommentar", recitations="Rezitationen", ot="Altes Testament",
               nt="Neues Testament", books_list="Bücher", chapters="Kapitel", pick_surah="Sure wählen",
               pick_book="Buch wählen", pick_chapter="Kapitel wählen", pick_verse="Vers wählen",
               pick_author="Kommentator wählen", pick_reciter="Rezitator wählen", back="Zurück",
               home="Start", copy="Kopieren", prev="Vorheriger", next="Nächster", source="Quelle",
               no_data="Keine Daten für diese Anfrage verfügbar",
               audio_fail="Audio konnte nicht gesendet werden, Link:",
               api_error="⚠️ Server nicht erreichbar, bitte gleich erneut versuchen.",
               fallback="(keine Übersetzung in Ihrer Sprache; andere Sprache angezeigt)", more="Fortsetzen"),
    "it": dict(main="Menu principale", soon="Prossimamente", books="Libri sacri", quran="Il Sacro Corano",
               gospel="Il Vangelo", torah="La Torah", surahs="Sure", verses="Versetti",
               tafsir="Tafsir / Commento", recitations="Recitazioni", ot="Antico Testamento",
               nt="Nuovo Testamento", books_list="Libri", chapters="Capitoli", pick_surah="Scegli una sura",
               pick_book="Scegli un libro", pick_chapter="Scegli un capitolo", pick_verse="Scegli un versetto",
               pick_author="Scegli un commentatore", pick_reciter="Scegli un recitatore", back="Indietro",
               home="Home", copy="Copia", prev="Precedente", next="Successivo", source="Fonte",
               no_data="Nessun dato disponibile per questa richiesta",
               audio_fail="Impossibile inviare l'audio, link:",
               api_error="⚠️ Server non raggiungibile, riprova tra poco.",
               fallback="(nessuna traduzione nella tua lingua; mostrata un'altra lingua)", more="Continua"),
    "pt": dict(main="Menu principal", soon="Em breve", books="Livros sagrados", quran="O Sagrado Alcorão",
               gospel="O Evangelho", torah="A Torá", surahs="Suras", verses="Versículos",
               tafsir="Tafsir / Comentário", recitations="Recitações", ot="Antigo Testamento",
               nt="Novo Testamento", books_list="Livros", chapters="Capítulos", pick_surah="Escolha uma sura",
               pick_book="Escolha um livro", pick_chapter="Escolha um capítulo",
               pick_verse="Escolha um versículo", pick_author="Escolha um comentarista",
               pick_reciter="Escolha um recitador", back="Voltar", home="Início", copy="Copiar",
               prev="Anterior", next="Próximo", source="Fonte",
               no_data="Não há dados disponíveis para este pedido",
               audio_fail="Não foi possível enviar o áudio, link:",
               api_error="⚠️ Não foi possível conectar ao servidor, tente novamente em instantes.",
               fallback="(sem tradução no seu idioma; exibindo outro idioma)", more="Continuar"),
    "ru": dict(main="Главное меню", soon="Скоро", books="Священные книги", quran="Священный Коран",
               gospel="Евангелие", torah="Тора", surahs="Суры", verses="Аяты", tafsir="Тафсир / Комментарий",
               recitations="Чтение (тиляват)", ot="Ветхий Завет", nt="Новый Завет", books_list="Книги",
               chapters="Главы", pick_surah="Выберите суру", pick_book="Выберите книгу",
               pick_chapter="Выберите главу", pick_verse="Выберите стих", pick_author="Выберите комментатора",
               pick_reciter="Выберите чтеца", back="Назад", home="Главная", copy="Копировать",
               prev="Предыдущий", next="Следующий", source="Источник",
               no_data="Нет данных по этому запросу", audio_fail="Не удалось отправить аудио, ссылка:",
               api_error="⚠️ Сервер недоступен, повторите попытку позже.",
               fallback="(нет перевода на ваш язык; показан другой язык)", more="Продолжить"),
    "tr": dict(main="Ana menü", soon="Yakında", books="Kutsal Kitaplar", quran="Kur'an-ı Kerim",
               gospel="İncil", torah="Tevrat", surahs="Sureler", verses="Ayetler", tafsir="Tefsir / Yorum",
               recitations="Tilavetler", ot="Eski Ahit", nt="Yeni Ahit", books_list="Kitaplar",
               chapters="Bölümler", pick_surah="Sure seçin", pick_book="Kitap seçin",
               pick_chapter="Bölüm seçin", pick_verse="Ayet seçin", pick_author="Müfessir seçin",
               pick_reciter="Kâri seçin", back="Geri", home="Ana sayfa", copy="Kopyala", prev="Önceki",
               next="Sonraki", source="Kaynak", no_data="Bu istek için veri yok",
               audio_fail="Ses gönderilemedi, bağlantı:",
               api_error="⚠️ Sunucuya ulaşılamadı, biraz sonra tekrar deneyin.",
               fallback="(dilinizde çeviri yok; başka bir dil gösteriliyor)", more="Devam"),
    "fa": dict(main="منوی اصلی", soon="به‌زودی", books="کتاب‌های آسمانی", quran="قرآن کریم",
               gospel="انجیل", torah="تورات", surahs="سوره‌ها", verses="آیات", tafsir="تفسیر",
               recitations="تلاوت‌ها", ot="عهد عتیق", nt="عهد جدید", books_list="کتاب‌ها", chapters="باب‌ها",
               pick_surah="سوره را انتخاب کنید", pick_book="کتاب را انتخاب کنید",
               pick_chapter="باب را انتخاب کنید", pick_verse="آیه را انتخاب کنید",
               pick_author="مفسر را انتخاب کنید", pick_reciter="قاری را انتخاب کنید", back="بازگشت",
               home="خانه", copy="کپی", prev="قبلی", next="بعدی", source="منبع",
               no_data="برای این درخواست داده‌ای موجود نیست", audio_fail="ارسال فایل صوتی ممکن نشد، لینک:",
               api_error="⚠️ اتصال به سرور ممکن نشد، کمی بعد دوباره تلاش کنید.",
               fallback="(ترجمه‌ای به زبان شما موجود نیست؛ زبان دیگری نمایش داده شد)", more="ادامه"),
    "ur": dict(main="مرکزی فہرست", soon="جلد آ رہا ہے", books="آسمانی کتابیں", quran="قرآنِ کریم",
               gospel="انجیل", torah="تورات", surahs="سورتیں", verses="آیات", tafsir="تفسیر",
               recitations="تلاوتیں", ot="عہدنامہ قدیم", nt="عہدنامہ جدید", books_list="کتابیں",
               chapters="ابواب", pick_surah="سورت منتخب کریں", pick_book="کتاب منتخب کریں",
               pick_chapter="باب منتخب کریں", pick_verse="آیت منتخب کریں", pick_author="مفسر منتخب کریں",
               pick_reciter="قاری منتخب کریں", back="واپس", home="ہوم", copy="کاپی", prev="پچھلی",
               next="اگلی", source="ماخذ", no_data="اس درخواست کے لیے ڈیٹا دستیاب نہیں",
               audio_fail="آڈیو بھیجنا ممکن نہ ہوا، لنک:",
               api_error="⚠️ سرور سے رابطہ نہ ہو سکا، تھوڑی دیر بعد دوبارہ کوشش کریں۔",
               fallback="(آپ کی زبان میں ترجمہ دستیاب نہیں؛ دوسری زبان دکھائی گئی)", more="جاری رکھیں"),
    "hi": dict(main="मुख्य मेनू", soon="जल्द आ रहा है", books="पवित्र ग्रंथ", quran="पवित्र क़ुरआन",
               gospel="इंजील", torah="तौरात", surahs="सूरतें", verses="आयतें", tafsir="तफ़्सीर / टीका",
               recitations="तिलावत", ot="पुराना नियम", nt="नया नियम", books_list="पुस्तकें",
               chapters="अध्याय", pick_surah="सूरत चुनें", pick_book="पुस्तक चुनें",
               pick_chapter="अध्याय चुनें", pick_verse="आयत/पद चुनें", pick_author="टीकाकार चुनें",
               pick_reciter="क़ारी चुनें", back="वापस", home="होम", copy="कॉपी", prev="पिछला",
               next="अगला", source="स्रोत", no_data="इस अनुरोध के लिए डेटा उपलब्ध नहीं",
               audio_fail="ऑडियो भेजा नहीं जा सका, लिंक:",
               api_error="⚠️ सर्वर से संपर्क नहीं हो सका, कुछ देर बाद पुनः प्रयास करें।",
               fallback="(आपकी भाषा में अनुवाद उपलब्ध नहीं; दूसरी भाषा दिखाई गई)", more="आगे"),
    "id": dict(main="Menu utama", soon="Segera hadir", books="Kitab Suci", quran="Al-Qur'an",
               gospel="Injil", torah="Taurat", surahs="Surah", verses="Ayat", tafsir="Tafsir / Tafsiran",
               recitations="Tilawah", ot="Perjanjian Lama", nt="Perjanjian Baru", books_list="Kitab",
               chapters="Pasal", pick_surah="Pilih surah", pick_book="Pilih kitab", pick_chapter="Pilih pasal",
               pick_verse="Pilih ayat", pick_author="Pilih mufasir", pick_reciter="Pilih qari",
               back="Kembali", home="Beranda", copy="Salin", prev="Sebelumnya", next="Berikutnya",
               source="Sumber", no_data="Data tidak tersedia untuk permintaan ini",
               audio_fail="Audio gagal dikirim, tautan:",
               api_error="⚠️ Tidak dapat terhubung ke server, coba lagi sebentar lagi.",
               fallback="(tidak ada terjemahan dalam bahasa Anda; bahasa lain ditampilkan)", more="Lanjut"),
    "zh": dict(main="主菜单", soon="即将推出", books="天启经典", quran="古兰经", gospel="福音书",
               torah="托拉（摩西五经）", surahs="苏拉（章）", verses="节", tafsir="注释", recitations="诵读",
               ot="旧约", nt="新约", books_list="书卷", chapters="章", pick_surah="选择苏拉",
               pick_book="选择书卷", pick_chapter="选择章", pick_verse="选择节", pick_author="选择注释者",
               pick_reciter="选择诵读者", back="返回", home="主页", copy="复制", prev="上一节",
               next="下一节", source="来源", no_data="此请求暂无可用数据", audio_fail="无法发送音频，链接：",
               api_error="⚠️ 无法连接服务器，请稍后再试。",
               fallback="（暂无您所用语言的译本，已显示其他语言）", more="继续"),
    "ja": dict(main="メインメニュー", soon="近日公開", books="啓典", quran="クルアーン", gospel="福音書",
               torah="トーラー", surahs="スーラ", verses="節", tafsir="タフスィール（注解）", recitations="朗誦",
               ot="旧約聖書", nt="新約聖書", books_list="書", chapters="章", pick_surah="スーラを選択",
               pick_book="書を選択", pick_chapter="章を選択", pick_verse="節を選択", pick_author="注解者を選択",
               pick_reciter="朗誦者を選択", back="戻る", home="ホーム", copy="コピー", prev="前へ",
               next="次へ", source="出典", no_data="この要求に該当するデータがありません",
               audio_fail="音声を送信できませんでした。リンク:",
               api_error="⚠️ サーバーに接続できません。しばらくしてからもう一度お試しください。",
               fallback="（お使いの言語の翻訳がないため、別の言語を表示しています）", more="続き"),
    "ko": dict(main="메인 메뉴", soon="곧 제공", books="성서", quran="꾸란", gospel="복음서", torah="토라",
               surahs="수라", verses="구절", tafsir="타프시르(주석)", recitations="낭송", ot="구약성경",
               nt="신약성경", books_list="책", chapters="장", pick_surah="수라 선택", pick_book="책 선택",
               pick_chapter="장 선택", pick_verse="구절 선택", pick_author="주석가 선택",
               pick_reciter="낭송자 선택", back="뒤로", home="홈", copy="복사", prev="이전", next="다음",
               source="출처", no_data="이 요청에 대한 데이터가 없습니다", audio_fail="오디오를 보낼 수 없습니다. 링크:",
               api_error="⚠️ 서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요.",
               fallback="(해당 언어 번역이 없어 다른 언어로 표시됩니다)", more="계속"),
    "el": dict(main="Κύριο μενού", soon="Σύντομα", books="Ιερά βιβλία", quran="Το Ιερό Κοράνι",
               gospel="Το Ευαγγέλιο", torah="Η Τορά", surahs="Σούρες", verses="Εδάφια",
               tafsir="Ταφσίρ / Σχολιασμός", recitations="Απαγγελίες", ot="Παλαιά Διαθήκη",
               nt="Καινή Διαθήκη", books_list="Βιβλία", chapters="Κεφάλαια", pick_surah="Επιλέξτε σούρα",
               pick_book="Επιλέξτε βιβλίο", pick_chapter="Επιλέξτε κεφάλαιο", pick_verse="Επιλέξτε εδάφιο",
               pick_author="Επιλέξτε σχολιαστή", pick_reciter="Επιλέξτε απαγγέλλοντα", back="Πίσω",
               home="Αρχική", copy="Αντιγραφή", prev="Προηγούμενο", next="Επόμενο", source="Πηγή",
               no_data="Δεν υπάρχουν δεδομένα για αυτό το αίτημα",
               audio_fail="Δεν ήταν δυνατή η αποστολή ήχου, σύνδεσμος:",
               api_error="⚠️ Αδυναμία σύνδεσης με τον διακομιστή, δοκιμάστε ξανά σε λίγο.",
               fallback="(δεν υπάρχει μετάφραση στη γλώσσα σας· εμφανίζεται άλλη γλώσσα)", more="Συνέχεια"),
    "nl": dict(main="Hoofdmenu", soon="Binnenkort", books="Heilige boeken", quran="De Heilige Koran",
               gospel="Het Evangelie", torah="De Tora", surahs="Soera's", verses="Verzen",
               tafsir="Tafsir / Commentaar", recitations="Recitaties", ot="Oude Testament",
               nt="Nieuwe Testament", books_list="Boeken", chapters="Hoofdstukken", pick_surah="Kies een soera",
               pick_book="Kies een boek", pick_chapter="Kies een hoofdstuk", pick_verse="Kies een vers",
               pick_author="Kies een commentator", pick_reciter="Kies een reciteur", back="Terug",
               home="Start", copy="Kopiëren", prev="Vorige", next="Volgende", source="Bron",
               no_data="Geen gegevens beschikbaar voor dit verzoek",
               audio_fail="Audio kon niet worden verzonden, link:",
               api_error="⚠️ Server niet bereikbaar, probeer het zo opnieuw.",
               fallback="(geen vertaling in uw taal; een andere taal wordt getoond)", more="Doorgaan"),
}


def tr(lang, key):
    for lg in (lang, UI_FALLBACK.get(lang), "en"):
        if lg and UI.get(lg, {}).get(key):
            return UI[lg][key]
    return key


# ════════════════════════════════════════════════════════════════
# 3) طبقة الاتصال بالـ API (كاش + إعادة محاولة)
# ════════════════════════════════════════════════════════════════
CLOUD = "https://api.alquran.cloud/v1"
QCOM = "https://api.quran.com/api/v4"
SEFARIA = "https://www.sefaria.org/api"
GETBIBLE = "https://api.getbible.net/v2"
HELLOAO = "https://bible.helloao.org/api"
AR_EDITION = "quran-uthmani"
AR_SOURCE = "alquran.cloud — quran-uthmani"

# تلاوة السورة كاملة (ملف واحد): معرّف إصدار alquran.cloud → (الاسم, قالب الرابط). تحقق من الروابط وأضف قرّاء.
SURAH_AUDIO = {
    "ar.alafasy": ("مشاري العفاسي", "https://server8.mp3quran.net/afs/{s:03d}.mp3"),
    "ar.husary": ("محمود خليل الحصري", "https://server13.mp3quran.net/husr/{s:03d}.mp3"),
}

HTTP: "httpx.AsyncClient | None" = None


class ApiError(Exception):
    pass


class NoData(ApiError):
    """الطلب سليم لكن لا توجد بيانات (404 / نتيجة فارغة)."""


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
            if r.status_code == 404:
                raise NoData(url)
            r.raise_for_status()
            data = r.json()
            CACHE.set(key, data)
            return data
        except NoData:
            raise
        except httpx.HTTPStatusError as e:
            last = e
            if e.response.status_code < 500 and e.response.status_code != 429:
                break
        except Exception as e:  # noqa: BLE001
            last = e
        await asyncio.sleep(0.8 * (attempt + 1))
    raise ApiError(f"{url}: {last}")


_TAAMIM = re.compile(r"[\u0591-\u05AF]")  # نغمات التلاوة العبرية (نُبقي التشكيل)


def clean_html(s):
    s = re.sub(r'<i class="footnote">.*?</i>', "", s or "", flags=re.S)
    s = re.sub(r"<sup[^>]*>.*?</sup>", "", s, flags=re.S)
    s = re.sub(r"<\s*br\s*/?>|</p>|</div>|</h\d>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()


def clean_he(s):
    s = _TAAMIM.sub("", clean_html(s))
    return re.sub(r"\s+", " ", re.sub(r"\s*\{[פס]\}", "", s)).strip()


def flat(x):
    """يسطّح القوائم المتداخلة إلى قائمة نصوص."""
    if isinstance(x, str):
        return [x]
    if isinstance(x, list):
        return [s for i in x for s in flat(i)]
    if isinstance(x, dict):
        return flat(x.get("text") if "text" in x else x.get("content"))
    return []


# ════════════════════════════════════════════════════════════════
# 4) القرآن (alquran.cloud + quran.com)
# ════════════════════════════════════════════════════════════════
async def surah_list():
    return (await api_get(f"{CLOUD}/surah"))["data"]


def surah_label(s, lang):
    return s["name"] if lang == "ar" else s["englishName"]


async def global_ayah(n, v):
    surahs = await surah_list()
    return sum(s["numberOfAyahs"] for s in surahs[:n - 1]) + v


_DIAC = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_BASMALA = ["بسم", "الله", "الرحمن", "الرحيم"]
BASMALA_TEXT = "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ"


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


async def _find_quran_translation(lg):
    try:
        d = await api_get(f"{CLOUD}/edition", {"format": "text", "type": "translation", "language": lg})
        eds = d.get("data") or []
        if eds:
            pref = PREFERRED_TRANSLATION.get(lg)
            ed = next((e for e in eds if e["identifier"] == pref), eds[0])
            return {"kind": "c", "id": ed["identifier"], "label": ed.get("englishName") or ed["name"],
                    "provider": "alquran.cloud", "lang": lg}
    except ApiError:
        pass
    try:  # احتياطي: api.quran.com
        d = await api_get(f"{QCOM}/resources/translations")
        c = [t for t in d.get("translations", []) if (t.get("language_name") or "").lower() == LANG_NAME.get(lg)]
        if c:
            return {"kind": "q", "id": str(c[0]["id"]), "label": c[0].get("author_name") or c[0]["name"],
                    "provider": "quran.com", "lang": lg}
    except ApiError:
        pass
    return None


async def quran_translation_info(lang):
    """إصدار ترجمة القرآن للغة المستخدم (None للعربية)، مع علامة fallback عند استخدام لغة بديلة."""
    if lang == "ar":
        return None
    for lg in lang_chain(lang):
        if lg == "ar":  # لا حاجة لترجمة عربية: النص الأصلي عربي
            return None
        info = await _find_quran_translation(lg)
        if info:
            return {**info, "fallback": lg != lang}
    return None


async def quran_translation_verses(n, info):
    if info["kind"] == "c":
        d = await api_get(f"{CLOUD}/surah/{n}/{info['id']}")
        return [clean_html(a["text"]) for a in d["data"]["ayahs"]]
    d = await api_get(f"{QCOM}/quran/translations/{info['id']}", {"chapter_number": n})
    return [clean_html(t["text"]) for t in d["translations"]]


async def get_surah(n, lang):
    ar = await arabic_verses(n)
    info = await quran_translation_info(lang)
    trn = None
    if info:
        try:
            trn = (await quran_translation_verses(n, info) + [""] * len(ar))[:len(ar)]
        except ApiError:
            trn = None
    return ar, trn, info


def quran_sources(info, trn):
    labels = [AR_SOURCE]
    if info and trn:
        labels.append(f"{info['label']} — {info['provider']}")
    return labels


async def quran_tafsir_list(lang):
    hit = CACHE.get(("q-tafsirs", lang))
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
        CACHE.set(("q-tafsirs", lang), items)
    return items


async def quran_tafsir_text(author, n, v):
    kind, _, ident = author.partition(":")
    if kind == "c":
        d = await api_get(f"{CLOUD}/ayah/{await global_ayah(n, v)}/{ident}")
        return clean_html(d["data"]["text"])
    d = await api_get(f"{QCOM}/tafsirs/{ident}/by_ayah/{n}:{v}")
    return clean_html(d["tafsir"]["text"])


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
# 5) الكتاب المقدس والتوراة: جدول الأسفار (ثابت) + واجهات Sefaria / getBible / HelloAO
#    (nr, عربي, إنجليزي, عبري, عدد الإصحاحات, اسم Sefaria, رمز USFM)
# ════════════════════════════════════════════════════════════════
_ROWS = [
    (1, "التكوين", "Genesis", "בראשית", 50, "Genesis", "GEN"),
    (2, "الخروج", "Exodus", "שמות", 40, "Exodus", "EXO"),
    (3, "اللاويين", "Leviticus", "ויקרא", 27, "Leviticus", "LEV"),
    (4, "العدد", "Numbers", "במדבר", 36, "Numbers", "NUM"),
    (5, "التثنية", "Deuteronomy", "דברים", 34, "Deuteronomy", "DEU"),
    (6, "يشوع", "Joshua", "יהושע", 24, "Joshua", "JOS"),
    (7, "القضاة", "Judges", "שופטים", 21, "Judges", "JDG"),
    (8, "راعوث", "Ruth", "רות", 4, "Ruth", "RUT"),
    (9, "صموئيل الأول", "1 Samuel", "שמואל א", 31, "I Samuel", "1SA"),
    (10, "صموئيل الثاني", "2 Samuel", "שמואל ב", 24, "II Samuel", "2SA"),
    (11, "الملوك الأول", "1 Kings", "מלכים א", 22, "I Kings", "1KI"),
    (12, "الملوك الثاني", "2 Kings", "מלכים ב", 25, "II Kings", "2KI"),
    (13, "أخبار الأيام الأول", "1 Chronicles", "דברי הימים א", 29, "I Chronicles", "1CH"),
    (14, "أخبار الأيام الثاني", "2 Chronicles", "דברי הימים ב", 36, "II Chronicles", "2CH"),
    (15, "عزرا", "Ezra", "עזרא", 10, "Ezra", "EZR"),
    (16, "نحميا", "Nehemiah", "נחמיה", 13, "Nehemiah", "NEH"),
    (17, "أستير", "Esther", "אסתר", 10, "Esther", "EST"),
    (18, "أيوب", "Job", "איוב", 42, "Job", "JOB"),
    (19, "المزامير", "Psalms", "תהילים", 150, "Psalms", "PSA"),
    (20, "الأمثال", "Proverbs", "משלי", 31, "Proverbs", "PRO"),
    (21, "الجامعة", "Ecclesiastes", "קהלת", 12, "Ecclesiastes", "ECC"),
    (22, "نشيد الأنشاد", "Song of Solomon", "שיר השירים", 8, "Song of Songs", "SNG"),
    (23, "إشعياء", "Isaiah", "ישעיהו", 66, "Isaiah", "ISA"),
    (24, "إرميا", "Jeremiah", "ירמיהו", 52, "Jeremiah", "JER"),
    (25, "مراثي إرميا", "Lamentations", "איכה", 5, "Lamentations", "LAM"),
    (26, "حزقيال", "Ezekiel", "יחזקאל", 48, "Ezekiel", "EZK"),
    (27, "دانيال", "Daniel", "דניאל", 12, "Daniel", "DAN"),
    (28, "هوشع", "Hosea", "הושע", 14, "Hosea", "HOS"),
    (29, "يوئيل", "Joel", "יואל", 3, "Joel", "JOL"),
    (30, "عاموس", "Amos", "עמוס", 9, "Amos", "AMO"),
    (31, "عوبديا", "Obadiah", "עובדיה", 1, "Obadiah", "OBA"),
    (32, "يونان", "Jonah", "יונה", 4, "Jonah", "JON"),
    (33, "ميخا", "Micah", "מיכה", 7, "Micah", "MIC"),
    (34, "ناحوم", "Nahum", "נחום", 3, "Nahum", "NAM"),
    (35, "حبقوق", "Habakkuk", "חבקוק", 3, "Habakkuk", "HAB"),
    (36, "صفنيا", "Zephaniah", "צפניה", 3, "Zephaniah", "ZEP"),
    (37, "حجي", "Haggai", "חגי", 2, "Haggai", "HAG"),
    (38, "زكريا", "Zechariah", "זכריה", 14, "Zechariah", "ZEC"),
    (39, "ملاخي", "Malachi", "מלאכי", 4, "Malachi", "MAL"),
    (40, "متى", "Matthew", "", 28, "", "MAT"),
    (41, "مرقس", "Mark", "", 16, "", "MRK"),
    (42, "لوقا", "Luke", "", 24, "", "LUK"),
    (43, "يوحنا", "John", "", 21, "", "JHN"),
    (44, "أعمال الرسل", "Acts", "", 28, "", "ACT"),
    (45, "رومية", "Romans", "", 16, "", "ROM"),
    (46, "كورنثوس الأولى", "1 Corinthians", "", 16, "", "1CO"),
    (47, "كورنثوس الثانية", "2 Corinthians", "", 13, "", "2CO"),
    (48, "غلاطية", "Galatians", "", 6, "", "GAL"),
    (49, "أفسس", "Ephesians", "", 6, "", "EPH"),
    (50, "فيلبي", "Philippians", "", 4, "", "PHP"),
    (51, "كولوسي", "Colossians", "", 4, "", "COL"),
    (52, "تسالونيكي الأولى", "1 Thessalonians", "", 5, "", "1TH"),
    (53, "تسالونيكي الثانية", "2 Thessalonians", "", 3, "", "2TH"),
    (54, "تيموثاوس الأولى", "1 Timothy", "", 6, "", "1TI"),
    (55, "تيموثاوس الثانية", "2 Timothy", "", 4, "", "2TI"),
    (56, "تيطس", "Titus", "", 3, "", "TIT"),
    (57, "فليمون", "Philemon", "", 1, "", "PHM"),
    (58, "العبرانيين", "Hebrews", "", 13, "", "HEB"),
    (59, "يعقوب", "James", "", 5, "", "JAS"),
    (60, "بطرس الأولى", "1 Peter", "", 5, "", "1PE"),
    (61, "بطرس الثانية", "2 Peter", "", 3, "", "2PE"),
    (62, "يوحنا الأولى", "1 John", "", 5, "", "1JN"),
    (63, "يوحنا الثانية", "2 John", "", 1, "", "2JN"),
    (64, "يوحنا الثالثة", "3 John", "", 1, "", "3JN"),
    (65, "يهوذا", "Jude", "", 1, "", "JUD"),
    (66, "رؤيا يوحنا", "Revelation", "", 22, "", "REV"),
]
BOOKS = {r[0]: dict(nr=r[0], ar=r[1], en=r[2], he=r[3], ch=r[4], sef=r[5], usfm=r[6]) for r in _ROWS}
SECTION_NRS = {"tr": list(range(1, 6)), "ot": list(range(1, 40)), "nt": list(range(40, 67))}

# تفاسير التوراة من Sefaria: id → (أسماء بلغات, قالب عنوان Sefaria)
TORAH_COMMENTARIES = {
    "rashi": ({"ar": "راشي", "en": "Rashi", "he": "רש״י"}, "Rashi on {b}"),
    "ibnezra": ({"ar": "ابن عزرا", "en": "Ibn Ezra", "he": "אבן עזרא"}, "Ibn Ezra on {b}"),
    "ramban": ({"ar": "رمبان", "en": "Ramban", "he": "רמב״ן"}, "Ramban on {b}"),
    "sforno": ({"ar": "سفورنو", "en": "Sforno", "he": "ספורנו"}, "Sforno on {b}"),
    "rashbam": ({"ar": "رشبام", "en": "Rashbam", "he": "רשב״ם"}, "Rashbam on {b}"),
}


def book_name(nr, lang):
    b = BOOKS[nr]
    if lang == "ar":
        return b["ar"]
    if lang == "he" and b["he"]:
        return b["he"]
    return b["en"]


# ── getBible: ترجمات الكتاب المقدس بلغات متعددة ───────────────────
async def bible_translations():
    d = await api_get(f"{GETBIBLE}/translations.json")
    items = list(d.values()) if isinstance(d, dict) else list(d)
    return [t for t in items if isinstance(t, dict) and t.get("abbreviation")]


def _matches_lang(t, lg):
    code = (t.get("lang") or "").lower().replace("_", "-").split("-")[0]
    name = (t.get("language") or "").lower()
    names = LANG_ALIASES.get(lg, (LANG_NAME.get(lg, "~"),))
    return code == lg or any(name.startswith(n) for n in names)


async def bible_candidates(lang):
    """ترجمات مرشّحة بالترتيب: لغة المستخدم أولاً ثم سلسلة البدائل."""
    trs = await bible_translations()
    out = []
    for lg in lang_chain(lang):
        matches = [t for t in trs if _matches_lang(t, lg)]
        pref = PREFERRED_BIBLE.get(lg)
        matches.sort(key=lambda t: (t["abbreviation"] != pref, t["abbreviation"]))
        for t in matches[:3]:
            out.append({"abbr": t["abbreviation"], "name": t.get("translation") or t["abbreviation"], "lang": lg})
    return out


async def bible_chapter(abbr, nr, ch):
    d = await api_get(f"{GETBIBLE}/{abbr}/{nr}/{ch}.json")
    verses = [(str(v["verse"]), clean_html(v["text"])) for v in d.get("verses", []) if v.get("text")]
    if not verses:
        raise NoData(f"{abbr} {nr}:{ch}")
    return verses


async def bible_chapter_user(nr, ch, lang):
    last = None
    for c in await bible_candidates(lang):
        try:
            vs = await bible_chapter(c["abbr"], nr, ch)
            return {"verses": [(n, t, None) for n, t in vs], "sources": [f"{c['name']} — getBible"],
                    "fallback": c["lang"] != lang}
        except ApiError as e:
            last = e
    raise last or NoData("no translation")


# ── Sefaria: التوراة بالعبرية + ترجمة ──────────────────────────────
async def sefaria_texts(ref, **extra):
    params = {"context": 0, "commentary": 0, "pad": 0, "stripItags": 1, **extra}
    d = await api_get(f"{SEFARIA}/texts/{ref}", params)
    if isinstance(d, dict) and d.get("error"):
        raise NoData(d["error"])
    return d


async def torah_chapter(nr, ch, lang):
    d = await sefaria_texts(f"{BOOKS[nr]['sef']}.{ch}")
    he = [clean_he(s) for s in flat(d.get("he"))]
    if not he:
        raise NoData(f"Torah {nr}:{ch}")
    en = [clean_html(s) for s in flat(d.get("text"))]
    sources = [f"Sefaria — {d.get('heVersionTitle') or 'Hebrew'}"]
    trans, fallback = None, False
    if lang != "he":
        for c in await bible_candidates(lang):
            if c["lang"] == "en":
                break  # الإنجليزية تأتي من Sefaria نفسها (ترقيم متطابق مع العبري)
            try:
                bv = await bible_chapter(c["abbr"], nr, ch)
            except ApiError:
                continue
            if len(bv) == len(he):  # نقبل الترجمة فقط إذا تطابق ترقيم الآيات مع العبري
                trans, fallback = [t for _, t in bv], c["lang"] != lang
                sources.append(f"{c['name']} — getBible")
                break
        if trans is None and en:
            trans, fallback = en, lang != "en"
            sources.append(f"Sefaria — {d.get('versionTitle') or 'English'}")
    verses = [(str(i + 1), h, trans[i] if trans and i < len(trans) and trans[i] else None)
              for i, h in enumerate(he)]
    return {"verses": verses, "sources": sources, "fallback": fallback}


async def get_chapter(book, nr, ch, lang):
    if book == "tr":
        return await torah_chapter(nr, ch, lang)
    return await bible_chapter_user(nr, ch, lang)


# ── التفاسير ───────────────────────────────────────────────────────
async def helloao_commentaries():
    d = await api_get(f"{HELLOAO}/available_commentaries.json")
    return d.get("commentaries", []) if isinstance(d, dict) else []


async def commentary_list(book, lang):
    if book == "tr":
        return [(cid, pick_name(v[0], lang)) for cid, v in TORAH_COMMENTARIES.items()]
    try:
        return [(c["id"], c.get("englishName") or c.get("name") or c["id"]) for c in await helloao_commentaries()]
    except ApiError:
        return []


async def commentary_text(book, author, nr, ch, v, lang):
    """(نص التفسير, وسم المصدر) — يرفع NoData عند عدم وجود تفسير لهذه الآية."""
    if book == "tr":
        names, tpl = TORAH_COMMENTARIES[author]
        title = tpl.format(b=BOOKS[nr]["sef"])
        d = await sefaria_texts(f"{title.replace(' ', '_')}.{ch}.{v}")
        he = [clean_he(s) for s in flat(d.get("he")) if s.strip()]
        en = [clean_html(s) for s in flat(d.get("text")) if s.strip()]
        use_en = lang != "he" and bool(en)
        parts = en if use_en else he
        if not parts:
            raise NoData(title)
        version = d.get("versionTitle") if use_en else d.get("heVersionTitle")
        label = f"Sefaria — {title}" + (f" ({version})" if version else "")
        return "\n\n".join(f"• {p}" for p in parts), label
    d = await api_get(f"{HELLOAO}/c/{author}/{BOOKS[nr]['usfm']}/{ch}.json")
    out = []
    for item in (d.get("chapter") or {}).get("content", []):
        if isinstance(item, dict) and item.get("type") == "verse" and str(item.get("number")) == str(v):
            out += [clean_html(s) for s in flat(item.get("content")) if s.strip()]
    if not out:
        raise NoData(f"{author} {nr}:{ch}:{v}")
    name = dict(await commentary_list(book, lang)).get(author, author)
    return "\n\n".join(out), f"{name} — bible.helloao.org (English)"


# ════════════════════════════════════════════════════════════════
# 6) القوائم والمسارات
# ════════════════════════════════════════════════════════════════
BOOK_KEY = {"q": "quran", "ot": "ot", "nt": "nt", "tr": "torah"}
_BIBLE_MODES = (("b", "books_list"), ("c", "chapters"), ("v", "verses"), ("t", "tafsir"))
MENUS = {
    "q": ("quran", "B", [("P|q|s|0", "surahs"), ("P|q|v|0", "verses"),
                         ("P|q|t|0", "tafsir"), ("S|qr", "recitations")]),
    "qr": ("recitations", "S|q", [("P|q|rs|0", "surahs"), ("P|q|rv|0", "verses")]),
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
BOOK_PAGE_CHARS = 28000  # عند إرسال سفر كامل: نرسل ~28 ألف حرف ثم زر "متابعة"


# ════════════════════════════════════════════════════════════════
# 7) دوال مساعدة
# ════════════════════════════════════════════════════════════════
def esc(s):
    return html.escape(str(s or ""))


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


def home_btn(lang, new=True):
    return Btn("🏠 " + tr(lang, "home"), callback_data="M|n" if new else "M")


def src_line(lang, labels, fallback=False):
    """سطر المصدر (يُضاف في نهاية كل رسالة)."""
    labels = list(dict.fromkeys(x for x in labels if x))
    if not labels:
        return ""
    s = f"\n\n<i>📚 {esc(tr(lang, 'source'))}: {esc(' · '.join(labels))}</i>"
    if fallback:
        s += f"\n<i>🌐 {esc(tr(lang, 'fallback'))}</i>"
    return s


def chunk(lines, limit=3300):
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
    out = []
    s = s or ""
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


async def send_parts(q, lang, lines, footer="", header="", last_rows=None):
    """يرسل قائمة أسطر على رسائل متتابعة؛ المصدر في نهاية كل رسالة، وأزرار إضافية في آخرها."""
    parts = chunk(lines)
    for i, part in enumerate(parts):
        text = (header if i == 0 else "") + part + footer
        rows = [[copy_btn(lang)]]
        if i == len(parts) - 1 and last_rows:
            rows += last_rows
        await q.message.reply_text(text, reply_markup=Markup(rows), parse_mode=HTML)
        await asyncio.sleep(0.4)


def verse_nav(lang, book, mode, vals, vi, ids, cur, plain):
    i = ids.index(cur)

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
    return [nav, [Btn("🔙 " + tr(lang, "back"), callback_data=pcb(book, mode, 0, vals[:-1])), home_btn(lang)]]


async def present(q, lang, ref, main, trans, footer, nav_rows):
    """يعرض آية/تفسيراً: يعدّل نفس الرسالة إن كان قصيراً، وإلا يقسّمه على رسائل (التنقل في الأخيرة)."""
    body = esc(main) + (f"\n<i>{esc(trans)}</i>" if trans else "")
    text = f"📖 <b>{esc(ref)}</b>\n\n{body}{footer}"
    if len(text) <= 4000:
        return await show(q, text, nav_rows)
    segs = [(p, False) for p in split_text(main)] + [(p, True) for p in split_text(trans)]
    for i, (piece, ital) in enumerate(segs):
        last = i == len(segs) - 1
        body = f"<i>{esc(piece)}</i>" if ital else esc(piece)
        msg = (f"📖 <b>{esc(ref)}</b>\n\n" if i == 0 else "") + body + footer
        await q.message.reply_text(msg, reply_markup=Markup(nav_rows if last else [[copy_btn(lang)]]),
                                   parse_mode=HTML)
        await asyncio.sleep(0.4)


async def options(book, step, sel, lang, mode=""):
    """قائمة (id, label) للخطوة الحالية."""
    if book == "q":
        if step == "work":
            return [(str(s["number"]), f"{s['number']}. {surah_label(s, lang)}") for s in await surah_list()]
        if step == "verse":
            count = (await surah_list())[int(sel["work"]) - 1]["numberOfAyahs"]
            return [(str(i), str(i)) for i in range(1, count + 1)]
        if step == "author":
            return [(i, label) for i, label, _ in await quran_tafsir_list(lang)]
        if step == "reciter":
            if mode == "rs":
                return [(k, v[0]) for k, v in SURAH_AUDIO.items()]
            return await verse_reciters(lang)
        return []
    if step == "work":
        return [(str(nr), f"{i}. {book_name(nr, lang)}") for i, nr in enumerate(SECTION_NRS[book], 1)]
    if step == "chapter":
        return [(str(i), str(i)) for i in range(1, BOOKS[int(sel["work"])]["ch"] + 1)]
    if step == "verse":
        chap = await get_chapter(book, int(sel["work"]), int(sel["chapter"]), lang)
        return [(n, n) for n, _, _ in chap["verses"]]
    if step == "author":
        return await commentary_list(book, lang)
    return []


async def crumb(book, steps, vals, lang, mode):
    parts = [tr(lang, BOOK_KEY[book])]
    for i, v in enumerate(vals):
        sel = dict(zip(steps, vals[:i]))
        parts.append(dict(await options(book, steps[i], sel, lang, mode)).get(v, v))
    return " › ".join(parts)


# ════════════════════════════════════════════════════════════════
# 8) الأوامر والقوائم
# ════════════════════════════════════════════════════════════════
def lang_rows():
    return grid([Btn(f"{flag} {name}", callback_data=f"L|{code}") for code, flag, name in LANGUAGES], 2)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(PICK_LANG, reply_markup=Markup(lang_rows()))


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
    if args[0] == "qr":  # عنوان الزرين: "التلاوات — السور / الآيات"
        rows = [[Btn(f"📖 {tr(lang, 'recitations')} — {tr(lang, key)}", callback_data=cb)] for cb, key in items]
    rows.append([Btn("🔙 " + tr(lang, "back"), callback_data=back), home_btn(lang, new=False)])
    await show(q, f"<b>{esc(tr(lang, title))}</b>", rows)


# ════════════════════════════════════════════════════════════════
# 9) محرّك المسارات المتشعبة
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
    rows.append([Btn("🔙 " + tr(lang, "back"), callback_data=back), home_btn(lang, new=False)])

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
    nr = int(sel["work"])
    if mode == "b":
        return await send_book(q, lang, book, nr, 1)
    if mode == "c":
        return await send_chapter(q, lang, book, nr, int(sel["chapter"]))
    return await show_bible_verse(q, lang, book, mode, steps, vals)


# ════════════════════════════════════════════════════════════════
# 10) عرض القرآن
# ════════════════════════════════════════════════════════════════
async def send_surah(q, lang, n):
    s = (await surah_list())[n - 1]
    ar, trn, info = await get_surah(n, lang)
    title = s["name"] if lang == "ar" else f"{s['name']} — {s['englishName']}"
    lines = [BASMALA_TEXT] if n not in (1, 9) else []
    for i, t in enumerate(ar, 1):
        line = f"{esc(t)} ﴿{ar_num(i)}﴾"
        if trn and trn[i - 1]:
            line += f"\n<i>{esc(trn[i - 1])}</i>"
        lines.append(line)
    footer = src_line(lang, quran_sources(info, trn), bool(info and trn and info.get("fallback")))
    await send_parts(q, lang, lines, footer, header=f"<b>{esc(title)}</b>\n\n", last_rows=[[home_btn(lang)]])


async def show_quran_verse(q, lang, mode, steps, vals):
    sel = dict(zip(steps, vals))
    n, v = int(sel["work"]), int(sel["verse"])
    s = (await surah_list())[n - 1]
    ref = f"{surah_label(s, lang)} : {v}"
    trans, fallback = None, False

    if mode == "t":
        labels = dict((i, (lb, ln)) for i, lb, ln in await quran_tafsir_list(lang))
        label = labels.get(sel["author"], (sel["author"], ""))[0]
        provider = "alquran.cloud" if sel["author"].startswith("c:") else "quran.com"
        try:
            main = await quran_tafsir_text(sel["author"], n, v)
        except NoData:
            main = ""
        main = main or tr(lang, "no_data")
        plain = main
        footer = src_line(lang, [f"{label} — {provider}"])
    else:
        ar, trn, info = await get_surah(n, lang)
        main = f"{ar[v - 1]} ﴿{ar_num(v)}﴾"
        trans = trn[v - 1] if trn and trn[v - 1] else None
        plain = ar[v - 1] + (f"\n{trans}" if trans else "")
        fallback = bool(info and trans and info.get("fallback"))
        footer = src_line(lang, quran_sources(info, trn if trans else None), fallback)

    count = s["numberOfAyahs"]
    ids = [str(i) for i in range(1, count + 1)]
    nav = verse_nav(lang, "q", mode, vals, steps.index("verse"), ids, str(v), plain)
    await present(q, lang, ref, main, trans, footer, nav)


async def send_quran_audio(q, lang, mode, steps, vals):
    sel = dict(zip(steps, vals))
    n, reciter = int(sel["work"]), sel["reciter"]
    performer = dict(await options("q", "reciter", sel, lang, mode)).get(reciter, reciter)
    if mode == "rs":
        url, prov = SURAH_AUDIO[reciter][1].format(s=n), "mp3quran.net"
    else:
        url, prov = await verse_audio_url(reciter, n, int(sel["verse"])), "alquran.cloud"
    caption = f"{await crumb('q', steps, vals, lang, mode)}\n{tr(lang, 'source')}: {performer} — {prov}"
    try:  # الرابط المباشر يعمل حتى ~20MB؛ للملفات الأكبر ارفعها وخزّن file_id
        await q.message.reply_audio(audio=url, caption=caption[:1000], performer=performer)
    except Exception as e:  # noqa: BLE001
        logging.warning("audio failed: %s", e)
        await q.message.reply_text(f"{tr(lang, 'audio_fail')}\n{url}\n\n{caption}")


# ════════════════════════════════════════════════════════════════
# 11) عرض التوراة والإنجيل (العهدان القديم والجديد)
# ════════════════════════════════════════════════════════════════
def verse_line(n, main, trans):
    return f"<b>{esc(n)}</b> {esc(main)}" + (f"\n<i>{esc(trans)}</i>" if trans else "")


async def send_chapter(q, lang, book, nr, ch):
    chap = await get_chapter(book, nr, ch, lang)
    lines = [verse_line(n, m, t) for n, m, t in chap["verses"]]
    footer = src_line(lang, chap["sources"], chap["fallback"])
    await send_parts(q, lang, lines, footer, header=f"<b>{esc(book_name(nr, lang))} {ch}</b>\n\n",
                     last_rows=[[home_btn(lang)]])


async def send_book(q, lang, book, nr, start):
    """يرسل السفر كاملاً على دفعات؛ عند الطول يظهر زر «متابعة» للإصحاح التالي."""
    total, title = BOOKS[nr]["ch"], book_name(nr, lang)
    lines, labels, fallback, size, ch = [], [], False, 0, start
    while ch <= total and (size < BOOK_PAGE_CHARS or ch == start):
        chap = await get_chapter(book, nr, ch, lang)
        lines.append(f"<b>— {esc(title)} {ch} —</b>")
        for n, m, t in chap["verses"]:
            line = verse_line(n, m, t)
            lines.append(line)
            size += len(line)
        labels += chap["sources"]
        fallback = fallback or chap["fallback"]
        ch += 1
    rows = []
    if ch <= total:
        rows.append([Btn(f"▶️ {tr(lang, 'more')} ({ch}/{total})", callback_data=f"K|{book}|{nr}|{ch}")])
    rows.append([home_btn(lang)])
    await send_parts(q, lang, lines, src_line(lang, labels, fallback), last_rows=rows)


async def h_continue(q, ctx, lang, args):
    book, nr, start = args[0], int(args[1]), int(args[2])
    try:  # إزالة زر المتابعة من الرسالة السابقة لمنع التكرار
        await q.edit_message_reply_markup(Markup([[copy_btn(lang)]]))
    except Exception:  # noqa: BLE001
        pass
    await q.message.chat.send_action(ChatAction.TYPING)
    await send_book(q, lang, book, nr, start)


async def show_bible_verse(q, lang, book, mode, steps, vals):
    sel = dict(zip(steps, vals))
    nr, ch, v = int(sel["work"]), int(sel["chapter"]), sel["verse"]
    chap = await get_chapter(book, nr, ch, lang)
    verses = {n: (m, t) for n, m, t in chap["verses"]}
    ids = [n for n, _, _ in chap["verses"]]
    ref = f"{book_name(nr, lang)} {ch}:{v}"
    trans, fallback = None, chap["fallback"]
    if mode == "t":
        try:
            main, label = await commentary_text(book, sel["author"], nr, ch, int(v), lang)
        except NoData:
            main, label = tr(lang, "no_data"), ""
        plain = main
        footer = src_line(lang, [label])
        trans = None
    else:
        main, trans = verses[v]
        plain = main + (f"\n{trans}" if trans else "")
        footer = src_line(lang, chap["sources"], fallback)
    nav = verse_nav(lang, book, mode, vals, steps.index("verse"), ids, v, plain)
    await present(q, lang, ref, main, trans, footer, nav)


# ════════════════════════════════════════════════════════════════
# 12) الموجّه الموحّد وتشغيل البوت
# ════════════════════════════════════════════════════════════════
async def h_copy(q, ctx, lang, args):
    await q.message.reply_text(f"<pre>{esc((q.message.text or '')[:3500])}</pre>", parse_mode=HTML)


async def h_soon(q, ctx, lang, args):
    await q.answer("🔒 " + tr(lang, "soon"))


async def h_noop(q, ctx, lang, args):
    pass


ROUTES = {"L": h_lang, "M": h_main, "B": h_books, "S": h_section, "P": h_path, "K": h_continue,
          "C": h_copy, "SOON": h_soon, "NOOP": h_noop}


async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    route, *args = q.data.split("|")
    lang = ctx.user_data.get("lang")
    if route != "SOON":
        await q.answer()
    if route != "L" and not lang:
        return await q.message.reply_text(PICK_LANG, reply_markup=Markup(lang_rows()))
    handler = ROUTES.get(route)
    if not handler:
        return
    try:
        await handler(q, ctx, lang, args)
    except NoData as e:
        logging.info("no data on %s: %s", q.data, e)
        await q.message.reply_text(tr(lang, "no_data"))
    except ApiError as e:
        logging.warning("API error on %s: %s", q.data, e)
        await q.message.reply_text(tr(lang, "api_error"))
    except Exception:  # noqa: BLE001
        logging.exception("callback failed: %s", q.data)


async def on_start(app):
    global HTTP
    HTTP = httpx.AsyncClient(timeout=httpx.Timeout(25.0), follow_redirects=True,
                             headers={"User-Agent": "HeavenlyBooksBot/3.0"})
    try:  # تسخين الكاش
        await surah_list()
    except ApiError as e:
        logging.warning("warm-up failed: %s", e)


async def on_stop(app):
    if HTTP:
        await HTTP.aclose()


def main():
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
