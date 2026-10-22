#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
books_system.py — نظام «الكتب» (Books System) كوحدة إضافية لبوت main.py

الاستخدام من main.py (سطران فقط):
    import books_system
    books_system.register(app, tr)          # قبل تسجيل الموجّه العام
    books_system.menu_button(lang)          # زر «الكتب» في القائمة الرئيسية

بنية callback_data (كلها تبدأ بـ BK وأقل من 64 بايت):
  BK|h|<cat>|<page>          قائمة الكتب (cat: a=الأكثر رواجاً، i=☪️، c=✝️، j=✡️)
  BK|s                       طلب كتابة اسم كتاب للبحث
  BK|r|<qh>|<page>           نتائج بحث الكتب (qh = معرّف قصير لنص البحث)
  BK|v|<book>                صفحة الكتاب
  BK|d|<book>|<ed>           تحميل PDF (ed=0 → الإصدار الافتراضي)
  BK|t|<book>|<ed>           طلب كلمة للبحث داخل نص الكتاب/الإصدار
  BK|x|<qh>|<page>           نتائج البحث داخل النص
  BK|e|<book>                قائمة الإصدارات
  BK|E|<book>|<ed>           قائمة الإصدار (PDF / بحث / تصفح)
  BK|g|<book>|<ed>|<gp>      شبكة أرقام الصفحات (تصفح الكتاب)
  BK|p|<book>|<ed>|<n>       عرض صفحة n (نسخ + السابق/التالي)
  BK|z  إلغاء الإدخال   |   BK|c  نسخ (بديل)   |   BK|n  لا شيء

إدارة الحالة (ctx.user_data["bk"]):
  state   : انتظار نص من المستخدم {mode: book|text, book, ed, back, ts}
  queries : نصوص البحث الأخيرة بمعرّف قصير (حتى 20) كي تبقى أزرار الصفحات صالحة
  from    : آخر شاشة قائمة/نتائج (للزر «رجوع» من صفحة الكتاب)

⚠️ طبقة البيانات (قسم 2) تجريبية: db_* و get_pdf_source() دوال Placeholder فوق كتالوج صغير
   في الذاكرة. استبدلها بقاعدة بياناتك أو واجهة API (نفس التواقيع) وكل شيء آخر يعمل كما هو.
"""
import asyncio
import hashlib
import html
import json
import logging
import math
import os
import re
import time

from telegram import CallbackQuery
from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Markup
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (CallbackQueryHandler, ContextTypes, MessageHandler, filters)

try:  # زر النسخ المباشر (PTB 21.8+)
    from telegram import CopyTextButton
except ImportError:
    CopyTextButton = None

log = logging.getLogger("books_system")
HTML = ParseMode.HTML

PAGE_SIZE = 6        # كتب في كل صفحة قائمة
HIT_PAGE_SIZE = 6    # نتائج بحث النص في كل صفحة
GRID_SIZE = 48       # أرقام صفحات في كل شبكة تصفح
GRID_COLS = 6
STATE_TTL = 600      # ثوانٍ: صلاحية انتظار نص المستخدم
REL_ICON = {"i": "☪️", "c": "✝️", "j": "✡️", "a": "🔥"}

# ════════════════════════════════════════════════════════════════
# 1) نصوص الواجهة (المفاتيح المشتركة back/home/copy/no_data/api_error تأتي من main.tr)
# ════════════════════════════════════════════════════════════════
BK_FALLBACK = {"syr": "ar"}
BKUI = {
    "ar": dict(btn="الكتب", welcome="📚 أهلاً بك في قسم الكتب!\nتصفّح أشهر الكتب الدينية، أو اختر الدين، أو ابحث عن كتاب بعينه.",
               pg_prev="الصفحة السابقة", pg_next="الصفحة التالية", search_book="بحث عن كتاب",
               ask_book="🔍 اكتب اسم الكتاب (أو المؤلف) الذي تبحث عنه:", results="نتائج البحث",
               trending="الأكثر رواجاً", dl_pdf="تحميل PDF", search_text="بحث في نص الكتاب",
               editions="الإصدارات", dl_edition="تحميل PDF للإصدار", search_edition="بحث في نص الإصدار",
               browse="تصفّح الكتاب", pick_page="اختر الصفحة", page="صفحة",
               ask_text="🔍 اكتب الكلمة أو العبارة التي تريد البحث عنها داخل الكتاب:", cancel="إلغاء",
               pdf_missing="ملف PDF غير متوفر لهذا الكتاب بعد.", author="المؤلف", pages_n="الصفحات",
               edition_n="الإصدار {n}", hits="نتائج البحث في النص", no_results="لا توجد نتائج.",
               ed_pick="اختر الإصدار"),
    "en": dict(btn="Books", welcome="📚 Welcome to the Books section!\nBrowse popular religious books, filter by religion, or search for a specific title.",
               pg_prev="Previous Page", pg_next="Next Page", search_book="Search Book",
               ask_book="🔍 Type the title (or author) of the book you are looking for:", results="Search results",
               trending="Trending", dl_pdf="Download PDF", search_text="Search text in book",
               editions="Editions", dl_edition="Download edition PDF", search_edition="Search text in edition",
               browse="Browse book", pick_page="Choose a page", page="Page",
               ask_text="🔍 Type the word or phrase to search for inside the book:", cancel="Cancel",
               pdf_missing="No PDF is available for this book yet.", author="Author", pages_n="Pages",
               edition_n="Edition {n}", hits="Text search results", no_results="No results found.",
               ed_pick="Choose an edition"),
    "he": dict(btn="ספרים", welcome="📚 ברוכים הבאים למדור הספרים!\nעיינו בספרי דת פופולריים, סננו לפי דת או חפשו ספר מסוים.",
               pg_prev="העמוד הקודם", pg_next="העמוד הבא", search_book="חיפוש ספר",
               ask_book="🔍 הקלידו את שם הספר (או המחבר) שאתם מחפשים:", results="תוצאות חיפוש",
               trending="פופולריים", dl_pdf="הורדת PDF", search_text="חיפוש טקסט בספר",
               editions="מהדורות", dl_edition="הורדת PDF של המהדורה", search_edition="חיפוש טקסט במהדורה",
               browse="עיון בספר", pick_page="בחרו עמוד", page="עמוד",
               ask_text="🔍 הקלידו מילה או ביטוי לחיפוש בתוך הספר:", cancel="ביטול",
               pdf_missing="קובץ PDF עדיין לא זמין לספר זה.", author="מחבר", pages_n="עמודים",
               edition_n="מהדורה {n}", hits="תוצאות חיפוש בטקסט", no_results="לא נמצאו תוצאות.",
               ed_pick="בחרו מהדורה"),
    "fr": dict(btn="Livres", welcome="📚 Bienvenue dans la section Livres !\nParcourez les livres religieux populaires, filtrez par religion ou recherchez un titre.",
               pg_prev="Page précédente", pg_next="Page suivante", search_book="Rechercher un livre",
               ask_book="🔍 Saisissez le titre (ou l'auteur) du livre :", results="Résultats de la recherche",
               trending="Populaires", dl_pdf="Télécharger le PDF", search_text="Rechercher dans le livre",
               editions="Éditions", dl_edition="Télécharger le PDF de l'édition", search_edition="Rechercher dans l'édition",
               browse="Parcourir le livre", pick_page="Choisissez une page", page="Page",
               ask_text="🔍 Saisissez le mot ou la phrase à chercher dans le livre :", cancel="Annuler",
               pdf_missing="Aucun PDF n'est encore disponible pour ce livre.", author="Auteur", pages_n="Pages",
               edition_n="Édition {n}", hits="Résultats dans le texte", no_results="Aucun résultat.",
               ed_pick="Choisissez une édition"),
    "es": dict(btn="Libros", welcome="📚 ¡Bienvenido a la sección de Libros!\nExplora libros religiosos populares, filtra por religión o busca un título.",
               pg_prev="Página anterior", pg_next="Página siguiente", search_book="Buscar libro",
               ask_book="🔍 Escribe el título (o autor) del libro:", results="Resultados de la búsqueda",
               trending="Populares", dl_pdf="Descargar PDF", search_text="Buscar texto en el libro",
               editions="Ediciones", dl_edition="Descargar PDF de la edición", search_edition="Buscar texto en la edición",
               browse="Explorar el libro", pick_page="Elige una página", page="Página",
               ask_text="🔍 Escribe la palabra o frase a buscar dentro del libro:", cancel="Cancelar",
               pdf_missing="Aún no hay PDF disponible para este libro.", author="Autor", pages_n="Páginas",
               edition_n="Edición {n}", hits="Resultados en el texto", no_results="Sin resultados.",
               ed_pick="Elige una edición"),
    "de": dict(btn="Bücher", welcome="📚 Willkommen im Bereich Bücher!\nStöbere in beliebten religiösen Büchern, filtere nach Religion oder suche einen Titel.",
               pg_prev="Vorherige Seite", pg_next="Nächste Seite", search_book="Buch suchen",
               ask_book="🔍 Gib den Titel (oder Autor) des Buches ein:", results="Suchergebnisse",
               trending="Beliebt", dl_pdf="PDF herunterladen", search_text="Im Buch suchen",
               editions="Ausgaben", dl_edition="PDF der Ausgabe herunterladen", search_edition="In der Ausgabe suchen",
               browse="Buch durchblättern", pick_page="Seite wählen", page="Seite",
               ask_text="🔍 Gib das Wort oder die Wendung ein, die im Buch gesucht werden soll:", cancel="Abbrechen",
               pdf_missing="Für dieses Buch ist noch kein PDF verfügbar.", author="Autor", pages_n="Seiten",
               edition_n="Ausgabe {n}", hits="Treffer im Text", no_results="Keine Ergebnisse.",
               ed_pick="Ausgabe wählen"),
    "it": dict(btn="Libri", welcome="📚 Benvenuto nella sezione Libri!\nSfoglia i libri religiosi più popolari, filtra per religione o cerca un titolo.",
               pg_prev="Pagina precedente", pg_next="Pagina successiva", search_book="Cerca libro",
               ask_book="🔍 Scrivi il titolo (o l'autore) del libro:", results="Risultati della ricerca",
               trending="Popolari", dl_pdf="Scarica PDF", search_text="Cerca nel testo del libro",
               editions="Edizioni", dl_edition="Scarica PDF dell'edizione", search_edition="Cerca nel testo dell'edizione",
               browse="Sfoglia il libro", pick_page="Scegli una pagina", page="Pagina",
               ask_text="🔍 Scrivi la parola o frase da cercare nel libro:", cancel="Annulla",
               pdf_missing="Nessun PDF ancora disponibile per questo libro.", author="Autore", pages_n="Pagine",
               edition_n="Edizione {n}", hits="Risultati nel testo", no_results="Nessun risultato.",
               ed_pick="Scegli un'edizione"),
    "pt": dict(btn="Livros", welcome="📚 Bem-vindo à seção de Livros!\nExplore livros religiosos populares, filtre por religião ou busque um título.",
               pg_prev="Página anterior", pg_next="Próxima página", search_book="Buscar livro",
               ask_book="🔍 Digite o título (ou autor) do livro:", results="Resultados da busca",
               trending="Em alta", dl_pdf="Baixar PDF", search_text="Buscar texto no livro",
               editions="Edições", dl_edition="Baixar PDF da edição", search_edition="Buscar texto na edição",
               browse="Navegar pelo livro", pick_page="Escolha uma página", page="Página",
               ask_text="🔍 Digite a palavra ou frase a buscar dentro do livro:", cancel="Cancelar",
               pdf_missing="Ainda não há PDF disponível para este livro.", author="Autor", pages_n="Páginas",
               edition_n="Edição {n}", hits="Resultados no texto", no_results="Nenhum resultado.",
               ed_pick="Escolha uma edição"),
    "ru": dict(btn="Книги", welcome="📚 Добро пожаловать в раздел «Книги»!\nЛистайте популярные религиозные книги, фильтруйте по религии или найдите нужное название.",
               pg_prev="Предыдущая страница", pg_next="Следующая страница", search_book="Поиск книги",
               ask_book="🔍 Введите название (или автора) книги:", results="Результаты поиска",
               trending="Популярные", dl_pdf="Скачать PDF", search_text="Поиск по тексту книги",
               editions="Издания", dl_edition="Скачать PDF издания", search_edition="Поиск по тексту издания",
               browse="Просмотр книги", pick_page="Выберите страницу", page="Страница",
               ask_text="🔍 Введите слово или фразу для поиска внутри книги:", cancel="Отмена",
               pdf_missing="PDF для этой книги пока недоступен.", author="Автор", pages_n="Страниц",
               edition_n="Издание {n}", hits="Результаты по тексту", no_results="Ничего не найдено.",
               ed_pick="Выберите издание"),
    "tr": dict(btn="Kitaplar", welcome="📚 Kitaplar bölümüne hoş geldiniz!\nPopüler dini kitaplara göz atın, dine göre filtreleyin veya bir başlık arayın.",
               pg_prev="Önceki sayfa", pg_next="Sonraki sayfa", search_book="Kitap ara",
               ask_book="🔍 Aradığınız kitabın adını (veya yazarını) yazın:", results="Arama sonuçları",
               trending="Popüler", dl_pdf="PDF indir", search_text="Kitap içinde ara",
               editions="Baskılar", dl_edition="Baskının PDF'ini indir", search_edition="Baskı içinde ara",
               browse="Kitaba göz at", pick_page="Bir sayfa seçin", page="Sayfa",
               ask_text="🔍 Kitap içinde aranacak kelime veya ifadeyi yazın:", cancel="İptal",
               pdf_missing="Bu kitap için henüz PDF yok.", author="Yazar", pages_n="Sayfa",
               edition_n="Baskı {n}", hits="Metin içi sonuçlar", no_results="Sonuç bulunamadı.",
               ed_pick="Bir baskı seçin"),
    "fa": dict(btn="کتاب‌ها", welcome="📚 به بخش کتاب‌ها خوش آمدید!\nکتاب‌های دینی پرطرفدار را مرور کنید، بر اساس دین فیلتر کنید یا کتابی را جست‌وجو کنید.",
               pg_prev="صفحه قبلی", pg_next="صفحه بعدی", search_book="جست‌وجوی کتاب",
               ask_book="🔍 نام کتاب (یا نویسنده) را بنویسید:", results="نتایج جست‌وجو",
               trending="پرطرفدار", dl_pdf="دانلود PDF", search_text="جست‌وجو در متن کتاب",
               editions="چاپ‌ها", dl_edition="دانلود PDF این چاپ", search_edition="جست‌وجو در متن این چاپ",
               browse="مرور کتاب", pick_page="صفحه را انتخاب کنید", page="صفحه",
               ask_text="🔍 کلمه یا عبارت مورد نظر برای جست‌وجو در کتاب را بنویسید:", cancel="لغو",
               pdf_missing="هنوز فایل PDF برای این کتاب موجود نیست.", author="نویسنده", pages_n="صفحات",
               edition_n="چاپ {n}", hits="نتایج جست‌وجو در متن", no_results="نتیجه‌ای یافت نشد.",
               ed_pick="چاپ را انتخاب کنید"),
    "ur": dict(btn="کتابیں", welcome="📚 کتابوں کے سیکشن میں خوش آمدید!\nمقبول مذہبی کتابیں دیکھیں، مذہب کے لحاظ سے فلٹر کریں یا کوئی کتاب تلاش کریں۔",
               pg_prev="پچھلا صفحہ", pg_next="اگلا صفحہ", search_book="کتاب تلاش کریں",
               ask_book="🔍 کتاب کا نام (یا مصنف) لکھیں:", results="تلاش کے نتائج",
               trending="مقبول", dl_pdf="PDF ڈاؤن لوڈ کریں", search_text="کتاب کے متن میں تلاش",
               editions="ایڈیشن", dl_edition="ایڈیشن کی PDF ڈاؤن لوڈ کریں", search_edition="ایڈیشن کے متن میں تلاش",
               browse="کتاب دیکھیں", pick_page="صفحہ منتخب کریں", page="صفحہ",
               ask_text="🔍 کتاب کے اندر تلاش کے لیے لفظ یا جملہ لکھیں:", cancel="منسوخ",
               pdf_missing="اس کتاب کی PDF ابھی دستیاب نہیں۔", author="مصنف", pages_n="صفحات",
               edition_n="ایڈیشن {n}", hits="متن میں تلاش کے نتائج", no_results="کوئی نتیجہ نہیں ملا۔",
               ed_pick="ایڈیشن منتخب کریں"),
    "hi": dict(btn="पुस्तकें", welcome="📚 पुस्तक अनुभाग में आपका स्वागत है!\nलोकप्रिय धार्मिक पुस्तकें देखें, धर्म के अनुसार फ़िल्टर करें या कोई शीर्षक खोजें।",
               pg_prev="पिछला पृष्ठ", pg_next="अगला पृष्ठ", search_book="पुस्तक खोजें",
               ask_book="🔍 पुस्तक का नाम (या लेखक) लिखें:", results="खोज परिणाम",
               trending="लोकप्रिय", dl_pdf="PDF डाउनलोड करें", search_text="पुस्तक के पाठ में खोजें",
               editions="संस्करण", dl_edition="संस्करण की PDF डाउनलोड करें", search_edition="संस्करण के पाठ में खोजें",
               browse="पुस्तक देखें", pick_page="पृष्ठ चुनें", page="पृष्ठ",
               ask_text="🔍 पुस्तक के भीतर खोजने के लिए शब्द या वाक्यांश लिखें:", cancel="रद्द करें",
               pdf_missing="इस पुस्तक की PDF अभी उपलब्ध नहीं है।", author="लेखक", pages_n="पृष्ठ",
               edition_n="संस्करण {n}", hits="पाठ में खोज परिणाम", no_results="कोई परिणाम नहीं मिला।",
               ed_pick="संस्करण चुनें"),
    "id": dict(btn="Buku", welcome="📚 Selamat datang di bagian Buku!\nJelajahi buku-buku agama populer, saring berdasarkan agama, atau cari judul tertentu.",
               pg_prev="Halaman sebelumnya", pg_next="Halaman berikutnya", search_book="Cari buku",
               ask_book="🔍 Ketik judul (atau penulis) buku yang dicari:", results="Hasil pencarian",
               trending="Populer", dl_pdf="Unduh PDF", search_text="Cari teks dalam buku",
               editions="Edisi", dl_edition="Unduh PDF edisi", search_edition="Cari teks dalam edisi",
               browse="Telusuri buku", pick_page="Pilih halaman", page="Halaman",
               ask_text="🔍 Ketik kata atau frasa yang dicari di dalam buku:", cancel="Batal",
               pdf_missing="PDF untuk buku ini belum tersedia.", author="Penulis", pages_n="Halaman",
               edition_n="Edisi {n}", hits="Hasil di dalam teks", no_results="Tidak ada hasil.",
               ed_pick="Pilih edisi"),
    "zh": dict(btn="书籍", welcome="📚 欢迎来到书籍专区！\n浏览热门宗教书籍，按宗教筛选，或搜索特定书名。",
               pg_prev="上一页", pg_next="下一页", search_book="搜索书籍",
               ask_book="🔍 请输入要查找的书名（或作者）：", results="搜索结果",
               trending="热门", dl_pdf="下载 PDF", search_text="在书中搜索文本",
               editions="版本", dl_edition="下载该版本 PDF", search_edition="在该版本中搜索",
               browse="浏览书籍", pick_page="选择页码", page="页",
               ask_text="🔍 请输入要在书内搜索的词语或短语：", cancel="取消",
               pdf_missing="此书暂无 PDF。", author="作者", pages_n="页数",
               edition_n="第 {n} 版", hits="文本搜索结果", no_results="未找到结果。",
               ed_pick="选择版本"),
    "ja": dict(btn="書籍", welcome="📚 書籍コーナーへようこそ！\n人気の宗教書を見たり、宗教で絞り込んだり、書名で検索できます。",
               pg_prev="前のページ", pg_next="次のページ", search_book="書籍を検索",
               ask_book="🔍 探している書名（または著者名）を入力してください：", results="検索結果",
               trending="人気", dl_pdf="PDFをダウンロード", search_text="本文内を検索",
               editions="版", dl_edition="この版のPDFをダウンロード", search_edition="この版の本文を検索",
               browse="書籍を閲覧", pick_page="ページを選択", page="ページ",
               ask_text="🔍 書籍内で検索する語句を入力してください：", cancel="キャンセル",
               pdf_missing="この書籍のPDFはまだありません。", author="著者", pages_n="ページ数",
               edition_n="第{n}版", hits="本文の検索結果", no_results="結果が見つかりません。",
               ed_pick="版を選択"),
    "ko": dict(btn="도서", welcome="📚 도서 섹션에 오신 것을 환영합니다!\n인기 종교 도서를 둘러보거나 종교별로 필터링하거나 제목을 검색하세요.",
               pg_prev="이전 페이지", pg_next="다음 페이지", search_book="도서 검색",
               ask_book="🔍 찾으시는 도서의 제목(또는 저자)을 입력하세요:", results="검색 결과",
               trending="인기", dl_pdf="PDF 다운로드", search_text="책 본문 검색",
               editions="판본", dl_edition="판본 PDF 다운로드", search_edition="판본 본문 검색",
               browse="책 둘러보기", pick_page="페이지 선택", page="페이지",
               ask_text="🔍 책 안에서 검색할 단어나 문구를 입력하세요:", cancel="취소",
               pdf_missing="이 도서의 PDF는 아직 없습니다.", author="저자", pages_n="페이지",
               edition_n="제{n}판", hits="본문 검색 결과", no_results="결과가 없습니다.",
               ed_pick="판본 선택"),
    "el": dict(btn="Βιβλία", welcome="📚 Καλώς ήρθατε στην ενότητα Βιβλία!\nΕξερευνήστε δημοφιλή θρησκευτικά βιβλία, φιλτράρετε ανά θρησκεία ή αναζητήστε έναν τίτλο.",
               pg_prev="Προηγούμενη σελίδα", pg_next="Επόμενη σελίδα", search_book="Αναζήτηση βιβλίου",
               ask_book="🔍 Πληκτρολογήστε τον τίτλο (ή τον συγγραφέα) του βιβλίου:", results="Αποτελέσματα αναζήτησης",
               trending="Δημοφιλή", dl_pdf="Λήψη PDF", search_text="Αναζήτηση στο κείμενο του βιβλίου",
               editions="Εκδόσεις", dl_edition="Λήψη PDF της έκδοσης", search_edition="Αναζήτηση στο κείμενο της έκδοσης",
               browse="Περιήγηση στο βιβλίο", pick_page="Επιλέξτε σελίδα", page="Σελίδα",
               ask_text="🔍 Πληκτρολογήστε τη λέξη ή τη φράση προς αναζήτηση μέσα στο βιβλίο:", cancel="Ακύρωση",
               pdf_missing="Δεν υπάρχει ακόμη PDF για αυτό το βιβλίο.", author="Συγγραφέας", pages_n="Σελίδες",
               edition_n="Έκδοση {n}", hits="Αποτελέσματα στο κείμενο", no_results="Δεν βρέθηκαν αποτελέσματα.",
               ed_pick="Επιλέξτε έκδοση"),
    "nl": dict(btn="Boeken", welcome="📚 Welkom bij de sectie Boeken!\nBlader door populaire religieuze boeken, filter op religie of zoek een titel.",
               pg_prev="Vorige pagina", pg_next="Volgende pagina", search_book="Boek zoeken",
               ask_book="🔍 Typ de titel (of auteur) van het boek:", results="Zoekresultaten",
               trending="Populair", dl_pdf="PDF downloaden", search_text="Zoeken in boektekst",
               editions="Edities", dl_edition="PDF van de editie downloaden", search_edition="Zoeken in editietekst",
               browse="Boek doorbladeren", pick_page="Kies een pagina", page="Pagina",
               ask_text="🔍 Typ het woord of de zin om in het boek te zoeken:", cancel="Annuleren",
               pdf_missing="Voor dit boek is nog geen PDF beschikbaar.", author="Auteur", pages_n="Pagina's",
               edition_n="Editie {n}", hits="Resultaten in de tekst", no_results="Geen resultaten.",
               ed_pick="Kies een editie"),
}

_external_tr = None
_DEFAULT_SHARED = {"back": "Back", "home": "Home", "copy": "Copy", "no_data": "No data available",
                   "api_error": "⚠️ Something went wrong, please try again."}


def t(lang, key, **kw):
    """نص الواجهة: قاموس هذه الوحدة ثم main.tr للمفاتيح المشتركة."""
    for lg in (lang, BK_FALLBACK.get(lang), "en"):
        s = BKUI.get(lg, {}).get(key) if lg else None
        if s:
            return s.format(**kw) if kw else s
    if _external_tr:
        return _external_tr(lang, key)
    return _DEFAULT_SHARED.get(key, key)


# ════════════════════════════════════════════════════════════════
# 2) طبقة البيانات — Placeholder (استبدل دوال db_* بقاعدة بياناتك/الـ API)
# ════════════════════════════════════════════════════════════════
def _book(bid, rel, titles, authors, trend, pages=30, eds=2):
    return {
        "id": bid, "rel": rel, "title": titles, "author": authors, "trending": trend,
        "pdf_url": None,  # ← ضع رابط PDF أو مسار ملف محلي أو file_id تيليجرام
        "editions": [{"id": str(i + 1), "pages": pages + 10 * i, "pdf_url": None} for i in range(eds)],
    }


# بيانات وصفية تجريبية فقط (عناوين لأعمال معروفة) — لا نصوص حقيقية للكتب هنا
CATALOG = {b["id"]: b for b in [
    _book("i1", "i", {"ar": "رياض الصالحين", "en": "Riyad as-Salihin"}, {"ar": "الإمام النووي", "en": "Imam al-Nawawi"}, 98),
    _book("i2", "i", {"ar": "الأربعون النووية", "en": "Forty Hadith of an-Nawawi"}, {"ar": "الإمام النووي", "en": "Imam al-Nawawi"}, 95),
    _book("i3", "i", {"ar": "صحيح البخاري", "en": "Sahih al-Bukhari"}, {"ar": "الإمام البخاري", "en": "Imam al-Bukhari"}, 97, 60, 3),
    _book("i4", "i", {"ar": "إحياء علوم الدين", "en": "Ihya Ulum al-Din"}, {"ar": "أبو حامد الغزالي", "en": "Abu Hamid al-Ghazali"}, 90),
    _book("i5", "i", {"ar": "الرسالة", "en": "Al-Risala"}, {"ar": "الإمام الشافعي", "en": "Imam al-Shafi'i"}, 80),
    _book("i6", "i", {"ar": "تفسير ابن كثير", "en": "Tafsir Ibn Kathir"}, {"ar": "ابن كثير", "en": "Ibn Kathir"}, 93, 50, 2),
    _book("c1", "c", {"ar": "اعترافات", "en": "Confessions"}, {"ar": "القديس أوغسطين", "en": "Augustine of Hippo"}, 92),
    _book("c2", "c", {"ar": "الاقتداء بالمسيح", "en": "The Imitation of Christ"}, {"ar": "توما الكمبيسي", "en": "Thomas à Kempis"}, 88),
    _book("c3", "c", {"ar": "رحلة الحاج", "en": "The Pilgrim's Progress"}, {"ar": "جون بنيان", "en": "John Bunyan"}, 86),
    _book("c4", "c", {"ar": "الخلاصة اللاهوتية", "en": "Summa Theologica"}, {"ar": "توما الأكويني", "en": "Thomas Aquinas"}, 84, 80, 2),
    _book("c5", "c", {"ar": "مدينة الله", "en": "The City of God"}, {"ar": "القديس أوغسطين", "en": "Augustine of Hippo"}, 83),
    _book("j1", "j", {"ar": "فصول الآباء", "en": "Pirkei Avot", "he": "פרקי אבות"}, {"ar": "المشناه", "en": "Mishnah", "he": "משנה"}, 91),
    _book("j2", "j", {"ar": "دلالة الحائرين", "en": "Guide for the Perplexed", "he": "מורה נבוכים"}, {"ar": "موسى بن ميمون", "en": "Maimonides", "he": "הרמב״ם"}, 89, 40, 2),
    _book("j3", "j", {"ar": "مشناه توراه", "en": "Mishneh Torah", "he": "משנה תורה"}, {"ar": "موسى بن ميمون", "en": "Maimonides", "he": "הרמב״ם"}, 85, 50, 2),
    _book("j4", "j", {"ar": "الكُزري", "en": "Kuzari", "he": "הכוזרי"}, {"ar": "يهودا اللاوي", "en": "Judah Halevi", "he": "יהודה הלוי"}, 82),
    _book("j5", "j", {"ar": "شولحان عاروخ", "en": "Shulchan Aruch", "he": "שולחן ערוך"}, {"ar": "يوسف كارو", "en": "Joseph Karo", "he": "יוסף קארו"}, 81),
]}

_AR_DIAC = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")


def norm(s):
    """تطبيع للبحث: حروف صغيرة + إزالة التشكيل + توحيد الألف والياء والتاء المربوطة."""
    s = _AR_DIAC.sub("", (s or "").lower())
    return s.translate(str.maketrans("أإآىة", "اااية".replace("ية", "يه")))


def loc(d, lang):
    """قيمة مترجمة من قاموس {lang: text} مع بدائل."""
    if not isinstance(d, dict):
        return str(d or "")
    return d.get(lang) or d.get(BK_FALLBACK.get(lang, "")) or d.get("en") or next(iter(d.values()), "")


async def db_list_books(cat, page, size):
    """← استبدلها باستعلام قاعدة بيانات: كتب الدين cat ('a' = كل الأديان) مرتبة بالرواج. تعيد (قائمة, الإجمالي)."""
    books = [b for b in CATALOG.values() if cat == "a" or b["rel"] == cat]
    books.sort(key=lambda b: -b["trending"])
    return books[page * size:(page + 1) * size], len(books)


async def db_search_books(query, page, size):
    """← استبدلها ببحث قاعدة البيانات/الـ API في العناوين والمؤلفين. تعيد (قائمة, الإجمالي)."""
    q = norm(query)
    found = [b for b in CATALOG.values()
             if q in norm(" ".join(b["title"].values())) or q in norm(" ".join(b["author"].values()))]
    found.sort(key=lambda b: -b["trending"])
    return found[page * size:(page + 1) * size], len(found)


async def db_get_book(bid):
    return CATALOG.get(bid)


async def db_get_editions(bid):
    """قائمة إصدارات الكتاب: [{id, pages, pdf_url, name(اختياري: قاموس لغات)}]"""
    b = CATALOG.get(bid)
    return b["editions"] if b else []


async def db_get_page_count(bid, ed):
    for e in await db_get_editions(bid):
        if e["id"] == ed:
            return e["pages"]
    return 0


async def db_get_page(bid, ed, n):
    """← استبدلها بجلب نص الصفحة الحقيقي (قاعدة بيانات / ملفات / API). تعيد نصاً عادياً."""
    b = CATALOG.get(bid)
    title = loc(b["title"], "en") if b else bid
    return (f"[Sample text] {title} — edition {ed}, page {n}.\n\n"
            "This is placeholder content. Replace db_get_page() with your real page source "
            "(database, files or an API) and the browse and text-search features will use it automatically.")


async def db_search_text(bid, ed, query, page, size):
    """بحث نصي داخل الكتاب/الإصدار. تعيد ([(رقم_الصفحة, مقتطف)], الإجمالي).
    هذه نسخة بسيطة تمسح الصفحات؛ للكتب الكبيرة استبدلها بفهرس بحث (SQLite FTS5 / Elasticsearch)."""
    total_pages = await db_get_page_count(bid, ed)
    pat = re.compile(re.escape(query), re.I)
    hits = []
    for n in range(1, total_pages + 1):
        text = await db_get_page(bid, ed, n)
        m = pat.search(text)
        if m:
            hits.append((n, snippet(text, m.start(), m.end())))
        if len(hits) >= 300:
            break
    return hits[page * size:(page + 1) * size], len(hits)


async def get_pdf_source(bid, ed):
    """مصدر ملف PDF: رابط http(s) أو مسار ملف محلي أو file_id. None إن لم يوجد. ← استبدلها."""
    book = CATALOG.get(bid)
    if not book:
        return None
    if ed != "0":
        for e in book["editions"]:
            if e["id"] == ed and e.get("pdf_url"):
                return e["pdf_url"]
    return book.get("pdf_url")


# ════════════════════════════════════════════════════════════════
# 3) دوال مساعدة
# ════════════════════════════════════════════════════════════════
def esc(s):
    return html.escape(str(s or ""))


def snippet(text, a, b, width=28):
    s = re.sub(r"\s+", " ", text[max(0, a - width):b + width]).strip()
    return ("…" if a - width > 0 else "") + s + ("…" if b + width < len(text) else "")


def split_text(s, limit=3300):
    out, s = [], s or ""
    while len(s) > limit:
        cut = max(s.rfind("\n", 0, limit), s.rfind(" ", 0, limit))
        cut = cut if cut > limit // 2 else limit
        out.append(s[:cut].strip())
        s = s[cut:].strip()
    if s:
        out.append(s)
    return out


def grid(btns, cols):
    return [btns[i:i + cols] for i in range(0, len(btns), cols)]


def ud_of(ctx):
    return ctx.user_data.setdefault("bk", {})


def clear_state(user_data):
    bk = user_data.get("bk")
    if bk:
        bk["state"] = None


def reg_query(ctx, payload):
    """يسجّل نص بحث بمعرّف قصير (md5) لاستخدامه داخل callback_data."""
    h = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:6]
    qs = ud_of(ctx).setdefault("queries", {})
    qs[h] = payload
    while len(qs) > 20:
        qs.pop(next(iter(qs)))
    return h


def home_btn(lang):
    return Btn("🏠 " + t(lang, "home"), callback_data="M")


def menu_button(lang):
    """زر «الكتب» للقائمة الرئيسية."""
    return Btn("📖 " + t(lang, "btn"), callback_data="BK|h|a|0")


def book_button(b, lang):
    label = f"{REL_ICON[b['rel']]} {loc(b['title'], lang)} — {loc(b['author'], lang)}"
    return [Btn(label[:60], callback_data=f"BK|v|{b['id']}")]


def pager_row(lang, page, pages, cb):
    row = []
    if page > 0:
        row.append(Btn("⬅️ " + t(lang, "pg_prev"), callback_data=cb(page - 1)))
    if page < pages - 1:
        row.append(Btn(t(lang, "pg_next") + " ➡️", callback_data=cb(page + 1)))
    return row


async def out(target, text, rows, edit=True):
    """يعدّل رسالة الـ callback أو يرسل رسالة جديدة (عند الرد على رسالة المستخدم)."""
    markup = Markup(rows)
    try:
        if isinstance(target, CallbackQuery):
            if edit:
                return await target.edit_message_text(text, reply_markup=markup, parse_mode=HTML,
                                                      disable_web_page_preview=True)
            return await target.message.reply_text(text, reply_markup=markup, parse_mode=HTML,
                                                   disable_web_page_preview=True)
        return await target.reply_text(text, reply_markup=markup, parse_mode=HTML, disable_web_page_preview=True)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


def copy_button(lang, plain):
    label = "📋 " + t(lang, "copy")
    if CopyTextButton and 0 < len(plain) <= 256:
        return Btn(label, copy_text=CopyTextButton(text=plain))
    return Btn(label, callback_data="BK|c")


async def resolve_ed(bid, ed):
    """'0' → الإصدار الافتراضي (الأول)."""
    if ed in ("0", ""):
        eds = await db_get_editions(bid)
        return eds[0]["id"] if eds else "1"
    return ed


def ed_label(lang, e):
    return loc(e["name"], lang) if e.get("name") else t(lang, "edition_n", n=e["id"])


# ════════════════════════════════════════════════════════════════
# 4) الشاشات
# ════════════════════════════════════════════════════════════════
async def show_list(target, ctx, lang, cat, page, edit=True):
    """1) القائمة الرئيسية للكتب: ترحيب + كتب رائجة + تنقل + فلاتر الأديان + بحث."""
    items, total = await db_list_books(cat, page, PAGE_SIZE)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    if page >= pages:
        page = pages - 1
        items, total = await db_list_books(cat, page, PAGE_SIZE)
    ud_of(ctx)["from"] = f"BK|h|{cat}|{page}"

    head = t(lang, "welcome") if cat == "a" else ""
    text = (f"{esc(head)}\n\n" if head else "") + f"{REL_ICON[cat]} <b>{esc(t(lang, 'trending'))}</b> ({page + 1}/{pages})"
    rows = [book_button(b, lang) for b in items]
    nav = pager_row(lang, page, pages, lambda p: f"BK|h|{cat}|{p}")
    if nav:
        rows.append(nav)
    rows.append([Btn(("• " if cat == k else "") + REL_ICON[k], callback_data=f"BK|h|{k}|0") for k in ("i", "c", "j", "a")])
    rows.append([Btn("🔍 " + t(lang, "search_book"), callback_data="BK|s")])
    rows.append([home_btn(lang)])
    await out(target, text, rows, edit)


async def ask_book_query(q, ctx, lang):
    """2) يطلب من المستخدم كتابة اسم كتاب."""
    ud = ud_of(ctx)
    ud["state"] = {"mode": "book", "ts": time.time(), "back": ud.get("from", "BK|h|a|0")}
    await out(q, esc(t(lang, "ask_book")), [[Btn("✖️ " + t(lang, "cancel"), callback_data="BK|z")]])


async def show_book_results(target, ctx, lang, qh, page, edit=True):
    payload = ud_of(ctx).get("queries", {}).get(qh)
    if not payload:
        return await show_list(target, ctx, lang, "a", 0, edit)
    items, total = await db_search_books(payload["q"], page, PAGE_SIZE)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    ud_of(ctx)["from"] = f"BK|r|{qh}|{page}"
    rows = [book_button(b, lang) for b in items]
    if total:
        nav = pager_row(lang, page, pages, lambda p: f"BK|r|{qh}|{p}")
        if nav:
            rows.append(nav)
        text = f"🔍 <b>{esc(t(lang, 'results'))}</b>: «{esc(payload['q'])}» — {total} ({page + 1}/{pages})"
    else:
        text = f"🔍 «{esc(payload['q'])}»\n\n{esc(t(lang, 'no_results'))}"
    rows.append([Btn("🔍 " + t(lang, "search_book"), callback_data="BK|s")])
    rows.append([Btn("🔙 " + t(lang, "back"), callback_data="BK|h|a|0"), home_btn(lang)])
    await out(target, text, rows, edit)


async def show_book(q, ctx, lang, bid):
    """3) تفاصيل الكتاب + أزرار: تحميل PDF / بحث في النص / الإصدارات."""
    b = await db_get_book(bid)
    if not b:
        return await out(q, esc(t(lang, "no_data")), [[home_btn(lang)]])
    eds = await db_get_editions(bid)
    pages = eds[0]["pages"] if eds else 0
    text = (f"{REL_ICON[b['rel']]} <b>{esc(loc(b['title'], lang))}</b>\n"
            f"✍️ {esc(t(lang, 'author'))}: {esc(loc(b['author'], lang))}\n"
            f"📑 {esc(t(lang, 'pages_n'))}: {pages} · 📚 {esc(t(lang, 'editions'))}: {len(eds)}")
    rows = [[Btn("📥 " + t(lang, "dl_pdf"), callback_data=f"BK|d|{bid}|0")],
            [Btn("🔍 " + t(lang, "search_text"), callback_data=f"BK|t|{bid}|0")],
            [Btn("📚 " + t(lang, "editions"), callback_data=f"BK|e|{bid}")],
            [Btn("🔙 " + t(lang, "back"), callback_data=ud_of(ctx).get("from", "BK|h|a|0")), home_btn(lang)]]
    await out(q, text, rows)


async def show_editions(q, ctx, lang, bid):
    """قائمة الإصدارات (الطبعة الأولى، الثانية...)."""
    b = await db_get_book(bid)
    eds = await db_get_editions(bid)
    if not b or not eds:
        return await out(q, esc(t(lang, "no_data")), [[Btn("🔙 " + t(lang, "back"), callback_data=f"BK|v|{bid}")]])
    rows = [[Btn(f"📘 {ed_label(lang, e)} — {e['pages']} {t(lang, 'pages_n')}"[:60],
                 callback_data=f"BK|E|{bid}|{e['id']}")] for e in eds]
    rows.append([Btn("🔙 " + t(lang, "back"), callback_data=f"BK|v|{bid}"), home_btn(lang)])
    await out(q, f"📚 <b>{esc(loc(b['title'], lang))}</b>\n{esc(t(lang, 'ed_pick'))}", rows)


async def show_edition(q, ctx, lang, bid, ed):
    """4) قائمة الإصدار: تحميل PDF / بحث / تصفح."""
    b = await db_get_book(bid)
    eds = {e["id"]: e for e in await db_get_editions(bid)}
    if not b or ed not in eds:
        return await out(q, esc(t(lang, "no_data")), [[home_btn(lang)]])
    e = eds[ed]
    text = (f"📘 <b>{esc(loc(b['title'], lang))}</b>\n{esc(ed_label(lang, e))} · "
            f"{e['pages']} {esc(t(lang, 'pages_n'))}")
    rows = [[Btn("📥 " + t(lang, "dl_edition"), callback_data=f"BK|d|{bid}|{ed}")],
            [Btn("🔍 " + t(lang, "search_edition"), callback_data=f"BK|t|{bid}|{ed}")],
            [Btn("📖 " + t(lang, "browse"), callback_data=f"BK|g|{bid}|{ed}|0")],
            [Btn("🔙 " + t(lang, "back"), callback_data=f"BK|e|{bid}"), home_btn(lang)]]
    await out(q, text, rows)


async def ask_text_query(q, ctx, lang, bid, ed):
    """يطلب كلمة/عبارة للبحث داخل نص الكتاب أو الإصدار."""
    back = f"BK|E|{bid}|{ed}" if ed != "0" else f"BK|v|{bid}"
    ud_of(ctx)["state"] = {"mode": "text", "book": bid, "ed": ed, "ts": time.time(), "back": back}
    await out(q, esc(t(lang, "ask_text")), [[Btn("✖️ " + t(lang, "cancel"), callback_data="BK|z")]])


async def show_text_results(target, ctx, lang, qh, page, edit=True):
    p = ud_of(ctx).get("queries", {}).get(qh)
    if not p:
        return await show_list(target, ctx, lang, "a", 0, edit)
    bid, ed = p["book"], await resolve_ed(p["book"], p["ed"])
    hits, total = await db_search_text(bid, ed, p["q"], page, HIT_PAGE_SIZE)
    pages = max(1, math.ceil(total / HIT_PAGE_SIZE))
    rows = [[Btn(f"📄 {t(lang, 'page')} {n}: {snip}"[:60], callback_data=f"BK|p|{bid}|{ed}|{n}")] for n, snip in hits]
    if total:
        nav = pager_row(lang, page, pages, lambda x: f"BK|x|{qh}|{x}")
        if nav:
            rows.append(nav)
        text = f"🔍 <b>{esc(t(lang, 'hits'))}</b>: «{esc(p['q'])}» — {total} ({page + 1}/{pages})"
    else:
        text = f"🔍 «{esc(p['q'])}»\n\n{esc(t(lang, 'no_results'))}"
    rows.append([Btn("🔙 " + t(lang, "back"), callback_data=p.get("back", f"BK|v|{bid}")), home_btn(lang)])
    await out(target, text, rows, edit)


async def show_grid(q, ctx, lang, bid, ed, gp):
    """5) تصفح الكتاب: شبكة أرقام الصفحات (مع نطاقات وتنقل بين الشبكات)."""
    ed = await resolve_ed(bid, ed)
    b = await db_get_book(bid)
    total = await db_get_page_count(bid, ed)
    if not b or not total:
        return await out(q, esc(t(lang, "no_data")), [[home_btn(lang)]])
    gpages = math.ceil(total / GRID_SIZE)
    gp = max(0, min(gp, gpages - 1))
    first, last = gp * GRID_SIZE + 1, min(total, (gp + 1) * GRID_SIZE)
    rows = grid([Btn(str(n), callback_data=f"BK|p|{bid}|{ed}|{n}") for n in range(first, last + 1)], GRID_COLS)
    if gpages > 1:
        nav = []
        if gp > 0:
            nav.append(Btn("◀️", callback_data=f"BK|g|{bid}|{ed}|{gp - 1}"))
        nav.append(Btn(f"{first}–{last}", callback_data="BK|n"))
        if gp < gpages - 1:
            nav.append(Btn("▶️", callback_data=f"BK|g|{bid}|{ed}|{gp + 1}"))
        rows.append(nav)
    rows.append([Btn("🔙 " + t(lang, "back"), callback_data=f"BK|E|{bid}|{ed}"), home_btn(lang)])
    await out(q, f"📖 <b>{esc(loc(b['title'], lang))}</b>\n{esc(t(lang, 'pick_page'))} ({total})", rows)


async def show_page(q, ctx, lang, bid, ed, n):
    """نص الصفحة + [📋 نسخ] + [◀️ السابقة | التالية ▶️]."""
    ed = await resolve_ed(bid, ed)
    b = await db_get_book(bid)
    eds = {e["id"]: e for e in await db_get_editions(bid)}
    total = await db_get_page_count(bid, ed)
    if not b or not total:
        return await out(q, esc(t(lang, "no_data")), [[home_btn(lang)]])
    n = max(1, min(n, total))
    body = (await db_get_page(bid, ed, n)) or t(lang, "no_data")
    header = (f"📖 <b>{esc(loc(b['title'], lang))}</b> · {esc(ed_label(lang, eds[ed]))}\n"
              f"{esc(t(lang, 'page'))} {n}/{total}")
    nav = []
    if n > 1:
        nav.append(Btn("◀️ " + t(lang, "pg_prev"), callback_data=f"BK|p|{bid}|{ed}|{n - 1}"))
    if n < total:
        nav.append(Btn(t(lang, "pg_next") + " ▶️", callback_data=f"BK|p|{bid}|{ed}|{n + 1}"))
    rows = [[copy_button(lang, body)]]
    if nav:
        rows.append(nav)
    rows.append([Btn("🔙 " + t(lang, "back"), callback_data=f"BK|g|{bid}|{ed}|{(n - 1) // GRID_SIZE}"), home_btn(lang)])

    text = f"{header}\n\n{esc(body)}"
    if len(text) <= 4000:
        return await out(q, text, rows)
    pieces = split_text(body)  # صفحة طويلة: عدة رسائل، والأزرار في آخرها
    for i, piece in enumerate(pieces):
        msg = (f"{header}\n\n" if i == 0 else "") + esc(piece)
        await q.message.reply_text(msg, parse_mode=HTML, reply_markup=Markup(rows) if i == len(pieces) - 1 else None)
        await asyncio.sleep(0.3)


async def send_pdf(q, ctx, lang, bid, ed):
    """📥 يرسل ملف PDF مباشرة (رابط/ملف محلي/file_id)، وإلا يرسل الرابط."""
    await q.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    b = await db_get_book(bid)
    src = await get_pdf_source(bid, ed)
    if not b or not src:
        return await q.message.reply_text(t(lang, "pdf_missing"))
    caption = f"📥 {loc(b['title'], lang)}"
    try:
        if os.path.isfile(src):
            with open(src, "rb") as f:
                await q.message.reply_document(document=f, caption=caption, filename=os.path.basename(src))
        else:  # رابط http(s) أو file_id
            await q.message.reply_document(document=src, caption=caption)
    except TelegramError as e:
        log.warning("send_pdf failed for %s: %s", bid, e)
        if src.startswith(("http://", "https://")):
            await q.message.reply_text(f"{caption}\n{src}")  # الملف كبير/مرفوض → أرسل الرابط
        else:
            await q.message.reply_text(t(lang, "pdf_missing"))


# ════════════════════════════════════════════════════════════════
# 5) الموجّه ومعالج النص
# ════════════════════════════════════════════════════════════════
async def dispatch(q, ctx, lang, p):
    act, a = p[0], p[1:]
    if act == "h":
        return await show_list(q, ctx, lang, a[0], int(a[1]))
    if act == "s":
        return await ask_book_query(q, ctx, lang)
    if act == "r":
        return await show_book_results(q, ctx, lang, a[0], int(a[1]))
    if act == "v":
        return await show_book(q, ctx, lang, a[0])
    if act == "d":
        return await send_pdf(q, ctx, lang, a[0], a[1])
    if act == "t":
        return await ask_text_query(q, ctx, lang, a[0], a[1])
    if act == "x":
        return await show_text_results(q, ctx, lang, a[0], int(a[1]))
    if act == "e":
        return await show_editions(q, ctx, lang, a[0])
    if act == "E":
        return await show_edition(q, ctx, lang, a[0], a[1])
    if act == "g":
        return await show_grid(q, ctx, lang, a[0], a[1], int(a[2]))
    if act == "p":
        return await show_page(q, ctx, lang, a[0], a[1], int(a[2]))
    if act == "z":  # إلغاء الإدخال والعودة
        st = ud_of(ctx).get("state") or {}
        ud_of(ctx)["state"] = None
        return await dispatch(q, ctx, lang, (st.get("back") or "BK|h|a|0").split("|")[1:])
    if act == "c":  # بديل النسخ: النص داخل كتلة code (لمسة واحدة تنسخه)
        body = (q.message.text or "").split("\n\n", 1)[-1]
        return await q.message.reply_text(f"<pre>{esc(body[:3800])}</pre>", parse_mode=HTML)


async def bk_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    lang = ctx.user_data.get("lang") or "en"
    parts = q.data.split("|")[1:]
    await q.answer()
    if not parts:
        return
    if parts[0] not in ("s", "t", "n"):
        clear_state(ctx.user_data)  # أي تنقل آخر يلغي انتظار النص
    if parts[0] == "n":
        return
    try:
        await q.message.chat.send_action(ChatAction.TYPING)
        await dispatch(q, ctx, lang, parts)
    except Exception:  # noqa: BLE001
        log.exception("books callback failed: %s", q.data)
        try:
            await q.message.reply_text(t(lang, "api_error"))
        except TelegramError:
            pass


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """يلتقط ردّ المستخدم عند انتظار اسم كتاب أو كلمة بحث؛ ويتجاهل أي رسالة أخرى."""
    ud = ctx.user_data.get("bk") or {}
    st = ud.get("state")
    if not st or time.time() - st.get("ts", 0) > STATE_TTL:
        ud["state"] = None
        return
    lang = ctx.user_data.get("lang") or "en"
    query = (update.message.text or "").strip()[:100]
    if len(query) < 2:
        return
    ud["state"] = None
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        if st["mode"] == "book":
            qh = reg_query(ctx, {"q": query})
            await show_book_results(update.message, ctx, lang, qh, 0, edit=False)
        else:
            qh = reg_query(ctx, {"q": query, "book": st["book"], "ed": st["ed"], "back": st["back"]})
            await show_text_results(update.message, ctx, lang, qh, 0, edit=False)
    except Exception:  # noqa: BLE001
        log.exception("books text search failed")
        await update.message.reply_text(t(lang, "api_error"))


def register(app, translate=None):
    """يسجّل معالجات النظام. استدعِها قبل إضافة الموجّه العام في main.py."""
    global _external_tr
    _external_tr = translate
    app.add_handler(CallbackQueryHandler(bk_router, pattern=r"^BK\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
