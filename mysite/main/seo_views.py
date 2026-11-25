"""
Модуль динамической генерации robots.txt, sitemap.xml и sitemap.html для пользователей
и поисковых систем (Яндекс, Google, Mail.ru).
Поддерживает стандарты протокола Sitemap 0.9 и расширение Google/Yandex Image Sitemap.
"""
import os
from pathlib import Path
from django.conf import settings as django_settings
from django.http import HttpResponse, FileResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.utils import timezone
from django.urls import reverse
from django.db.models import Prefetch
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom

from .models import SiteSettings, Page
from shop.models import Category, Product
from articles.models import Article
from news.models import News


def favicon_view(request):
    """
    Отдает иконку сайта (favicon.ico).
    Если администратором загружен персональный favicon в SiteSettings, перенаправляет на него,
    иначе отдает файл favicon.ico напрямую со статусом 200 OK.
    """
    settings = SiteSettings.get_solo()
    if settings.favicon:
        try:
            return HttpResponseRedirect(settings.favicon.url)
        except Exception:
            pass

    static_ico = Path(django_settings.BASE_DIR) / "static" / "images" / "favicon.ico"
    if static_ico.exists():
        return FileResponse(open(static_ico, "rb"), content_type="image/x-icon")
    return HttpResponse(status=204)


def robots_txt_view(request):
    """
    Генерирует и отдает файл robots.txt.
    Берет правила из настроек сайта в панели администратора (SiteSettings).
    """
    settings = SiteSettings.get_solo()
    content = settings.get_robots_txt()
    return HttpResponse(content, content_type="text/plain; charset=utf-8")


def sitemap_html_view(request):
    """
    Пользовательская HTML-карта сайта (HTML Sitemap) для удобной навигации посетителей
    и быстрой индексации поисковыми роботами.
    Отображает структурированные ссылки на все разделы, категории, товары каталога,
    новости, статьи, документы компании и служебные каналы экспорта (XML, RSS).
    """
    settings = SiteSettings.get_solo()
    base_url = (settings.site_base_url or f"{request.scheme}://{request.get_host()}").rstrip('/')

    # Категории с предварительно загруженными активными товарами
    active_products_prefetch = Prefetch(
        'products',
        queryset=Product.objects.filter(is_active=True).order_by('order', 'id'),
        to_attr='active_products'
    )
    categories = list(
        Category.objects.filter(is_active=True)
        .prefetch_related(active_products_prefetch)
        .order_by('order', 'name')
    )
    total_products = sum(len(cat.active_products) for cat in categories)

    # Опубликованные новости
    news_list = list(News.objects.filter(is_published=True).order_by('-published_at', '-id'))

    # Опубликованные статьи
    articles_list = list(Article.objects.filter(is_published=True).order_by('order', '-created_at', '-id'))

    # Информационные и регламентные страницы
    pages_list = list(Page.objects.filter(is_published=True, sitemap_include=True).order_by('order', 'id'))

    canonical_url = f"{base_url}/sitemap/"

    context = {
        'page_title': f"Карта сайта — Навигация по каталогу и разделам | {settings.brand_short_name or 'Сибсыр'}",
        'page_description': (
            f"Полная структурированная карта сайта сыроварни «{settings.brand_short_name or 'Сибсыр'}». "
            f"Удобный каталог всех категорий и сыров, новостей, рецептов, статей и документов компании в Омске."
        ),
        'page_keywords': "карта сайта сибсыр, каталог сыров навигация, все страницы сайта, статьи о сыре, новости сыроварни",
        'canonical_url': canonical_url,
        'site_settings': settings,
        'brand_name': settings.brand_name,
        'brand_short_name': settings.brand_short_name,
        'site_base_url': base_url,
        'categories': categories,
        'total_products': total_products,
        'news_list': news_list,
        'articles_list': articles_list,
        'pages_list': pages_list,
    }
    return render(request, 'main/sitemap.html', context)


def sitemap_xml_view(request):
    """
    Динамически генерирует актуальный sitemap.xml со всеми активными страницами сайта:
    - Главная, Каталог, Категории, О компании, Доставка, Отзывы, Контакты, Статьи, Новости, Карта сайта
    - Все активные товары каталога с фото (Google Images Sitemap)
    - Все активные категории
    - Все опубликованные статьи блога с датами и фото
    - Все опубликованные новости сыроварни с датами и фото
    - Все динамические страницы Page
    """
    settings = SiteSettings.get_solo()
    base_url = (settings.site_base_url or f"{request.scheme}://{request.get_host()}").rstrip('/')
    now_str = timezone.now().strftime("%Y-%m-%d")

    # Корневой элемент urlset с пространствами имен
    urlset = ET.Element(
        "urlset",
        {
            "xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9",
            "xmlns:image": "http://www.google.com/schemas/sitemap-image/1.1",
        }
    )

    def add_url(loc, lastmod=None, changefreq="weekly", priority="0.8", images=None):
        url_elem = ET.SubElement(urlset, "url")
        loc_elem = ET.SubElement(url_elem, "loc")
        loc_elem.text = f"{base_url}{loc}"

        if lastmod:
            lastmod_elem = ET.SubElement(url_elem, "lastmod")
            lastmod_elem.text = str(lastmod)

        if changefreq:
            changefreq_elem = ET.SubElement(url_elem, "changefreq")
            changefreq_elem.text = changefreq

        if priority:
            priority_elem = ET.SubElement(url_elem, "priority")
            priority_elem.text = str(priority)

        if images:
            for img in images:
                if not img or not img.get("loc"):
                    continue
                img_elem = ET.SubElement(url_elem, "image:image")
                img_loc = ET.SubElement(img_elem, "image:loc")
                full_img_url = img["loc"] if img["loc"].startswith("http") else f"{base_url}{img['loc']}"
                img_loc.text = full_img_url
                if img.get("title"):
                    img_title = ET.SubElement(img_elem, "image:title")
                    img_title.text = str(img["title"])
                if img.get("caption"):
                    img_caption = ET.SubElement(img_elem, "image:caption")
                    img_caption.text = str(img["caption"])

    # 1. Основные статические разделы сайта
    static_pages = [
        ("/", now_str, "daily", "1.0"),
        ("/catalog/", now_str, "daily", "0.9"),
        ("/categories/", now_str, "weekly", "0.9"),
        ("/articles/", now_str, "daily", "0.8"),
        ("/news/", now_str, "daily", "0.9"),
        ("/sitemap/", now_str, "weekly", "0.8"),
        ("/about/", now_str, "monthly", "0.7"),
        ("/delivery/", now_str, "monthly", "0.7"),
        ("/reviews/", now_str, "daily", "0.8"),
        ("/faq/", now_str, "weekly", "0.8"),
        ("/contacts/", now_str, "monthly", "0.7"),
    ]

    for loc, lastmod, freq, prio in static_pages:
        add_url(loc, lastmod=lastmod, changefreq=freq, priority=prio)

    # 2. Категории каталога
    categories = Category.objects.filter(is_active=True).order_by("order", "name")
    for cat in categories:
        cat_url = f"/catalog/?cat={cat.slug}"
        cat_images = []
        if cat.image:
            cat_images.append({
                "loc": cat.image.url,
                "title": f"Категория {cat.name} — ТМ «Сибсыр»",
                "caption": cat.meta_description or f"Каталог {cat.name} от сыродельного завода Сибсыр в Омске",
            })
        add_url(cat_url, lastmod=now_str, changefreq="weekly", priority="0.8", images=cat_images)

    # 3. Активные товары
    products = Product.objects.filter(is_active=True).select_related("category").order_by("order", "id")
    for prod in products:
        prod_url = prod.get_absolute_url()
        prod_images = []
        img_url = prod.image_url
        if img_url:
            prod_images.append({
                "loc": img_url,
                "title": f"{prod.title} — ТМ «Сибсыр»",
                "caption": prod.get_meta_description(),
            })
        add_url(prod_url, lastmod=now_str, changefreq="weekly", priority="0.9", images=prod_images)

    # 4. Опубликованные статьи базы знаний и блога
    articles = Article.objects.filter(is_published=True).order_by("order", "-id")
    for art in articles:
        art_url = art.get_absolute_url()
        art_date = art.created_at.strftime("%Y-%m-%d") if art.created_at else now_str
        art_images = []
        if art.image:
            art_images.append({
                "loc": art.image.url,
                "title": art.title,
                "caption": art.get_meta_description(),
            })
        add_url(art_url, lastmod=art_date, changefreq="monthly", priority="0.7", images=art_images)

    # 5. Опубликованные новости сыроварни
    news_items = News.objects.filter(is_published=True).order_by("-published_at", "-id")
    for nw in news_items:
        nw_url = nw.get_absolute_url()
        nw_date = nw.updated_at.strftime("%Y-%m-%d") if nw.updated_at else (
            nw.published_at.strftime("%Y-%m-%d") if nw.published_at else now_str
        )
        nw_images = []
        if nw.image:
            nw_images.append({
                "loc": nw.image.url,
                "title": nw.title,
                "caption": nw.snippet or nw.title,
            })
        add_url(nw_url, lastmod=nw_date, changefreq="weekly", priority="0.8", images=nw_images)

    # 6. Динамические страницы контента и промо-разделы
    pages = Page.objects.filter(is_published=True, sitemap_include=True).order_by("order", "id")
    for pg in pages:
        if "noindex" in pg.meta_robots_index:
            continue
        pg_url = pg.get_absolute_url()
        pg_date = pg.updated_at.strftime("%Y-%m-%d") if pg.updated_at else now_str
        pg_images = []
        if pg.featured_image:
            pg_images.append({
                "loc": pg.featured_image.url,
                "title": pg.title,
                "caption": pg.get_meta_description(),
            })
        elif pg.og_image:
            pg_images.append({
                "loc": pg.og_image.url,
                "title": pg.title,
                "caption": pg.get_meta_description(),
            })
        add_url(
            pg_url,
            lastmod=pg_date,
            changefreq=pg.sitemap_changefreq or "weekly",
            priority=pg.sitemap_priority or "0.8",
            images=pg_images
        )

    # Формируем читаемый XML с заголовком
    rough_string = ET.tostring(urlset, encoding="utf-8")
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="  ", encoding="utf-8")

    response = HttpResponse(pretty_xml, content_type="application/xml; charset=utf-8")
    # Добавляем заголовок Last-Modified для поисковых ботов
    response["Last-Modified"] = timezone.now().strftime("%a, %d %b %Y %H:%M:%S GMT")
    return response


def indexnow_key_view(request, key):
    """
    Отдает файл ключа IndexNow (/<key>.txt) со значением ключа в формате text/plain.
    Требуется протоколом IndexNow для верификации владения доменом поисковыми системами Яндекс и Bing.
    """
    settings = SiteSettings.get_solo()
    valid_key = (settings.indexnow_key or "e8b15d07a12c4b8b93cb4a15b81a5c67").strip()
    if key.lower() == valid_key.lower():
        return HttpResponse(valid_key, content_type="text/plain; charset=utf-8")
    if re.match(r"^[0-9a-fA-F]{16,64}$", key):
        return HttpResponse(key, content_type="text/plain; charset=utf-8")
    return HttpResponse("Not Found", status=404)


def _read_verification_file(filename):
    """Ищет и читает реальный файл верификации в BASE_DIR или корне проекта."""
    candidates = [
        Path(django_settings.BASE_DIR) / filename,
        Path(django_settings.BASE_DIR).parent / filename,
    ]
    for file_path in candidates:
        if file_path.is_file():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return None


def yandex_verification_view(request, filename="yandex_2481be1b37f5b18c.html"):
    """
    Отдает реальный файл подтверждения прав Яндекс.Вебмастер (yandex_<код>.html).
    Для несуществующих файлов возвращает 404.
    """
    if not filename:
        filename = "yandex_2481be1b37f5b18c.html"

    if re.match(r"^yandex_[a-zA-Z0-9]+\.html$", filename):
        content = _read_verification_file(filename)
        if content is not None:
            return HttpResponse(content, content_type="text/html; charset=UTF-8")

    return HttpResponse("Not Found", status=404)


def google_verification_view(request, filename="google70ba8bfb8c55d9f9.html"):
    """
    Отдает реальный файл подтверждения прав Google Search Console (google<код>.html).
    Для несуществующих файлов возвращает 404 (иначе Google считает сайт взломанным).
    """
    if not filename:
        filename = "google70ba8bfb8c55d9f9.html"

    if re.match(r"^google[a-zA-Z0-9]+\.html$", filename):
        content = _read_verification_file(filename)
        if content is not None:
            return HttpResponse(content, content_type="text/html; charset=UTF-8")

    return HttpResponse("Not Found", status=404)
