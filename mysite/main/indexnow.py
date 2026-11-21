"""
Модуль интеграции с протоколом мгновенного поискового оповещения IndexNow.
Поддерживается поисковыми системами Яндекс (yandex.com/indexnow) и Bing (api.indexnow.org/indexnow).
Обеспечивает индексацию новых и обновленных страниц за считанные минуты вместо недель ожидания.
"""
import logging
import threading
from typing import Iterable, List, Optional
import requests
from django.conf import settings as django_settings
from django.urls import reverse

logger = logging.getLogger("seo.indexnow")

INDEXNOW_ENDPOINTS = [
    "https://yandex.com/indexnow",
    "https://api.indexnow.org/indexnow",
]

DEFAULT_KEY = "e8b15d07a12c4b8b93cb4a15b81a5c67"


def get_indexnow_key() -> str:
    """Возвращает актуальный API-ключ IndexNow из настроек сайта."""
    try:
        from main.models import SiteSettings
        s = SiteSettings.get_solo()
        return s.indexnow_key or DEFAULT_KEY
    except Exception:
        return DEFAULT_KEY


def get_site_host() -> str:
    """Возвращает чистый хост сайта (например, sibsir.ru)."""
    try:
        from main.models import SiteSettings
        s = SiteSettings.get_solo()
        base_url = (s.site_base_url or "https://sibsir.ru").rstrip("/")
        clean = base_url.replace("https://", "").replace("http://", "").split("/")[0]
        return clean or "sibsir.ru"
    except Exception:
        return "sibsir.ru"


def get_site_base_url() -> str:
    """Возвращает базовый URL сайта с протоколом (например, https://sibsir.ru)."""
    try:
        from main.models import SiteSettings
        s = SiteSettings.get_solo()
        return (s.site_base_url or "https://sibsir.ru").rstrip("/")
    except Exception:
        return "https://sibsir.ru"


def _send_payload(payload: dict, endpoints: List[str] = INDEXNOW_ENDPOINTS) -> dict:
    """Синхронная внутренняя функция отправки JSON payload в эндпоинты IndexNow."""
    results = {}
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "Sibsir-IndexNow-Notifier/1.0",
    }
    for ep in endpoints:
        try:
            resp = requests.post(ep, json=payload, headers=headers, timeout=6)
            results[ep] = {
                "status_code": resp.status_code,
                "text": resp.text[:200] if resp.text else "",
                "success": resp.status_code in (200, 202),
            }
            if resp.status_code in (200, 202):
                logger.info(f"IndexNow [{ep}] OK ({resp.status_code}): {len(payload.get('urlList', []))} URLs")
            else:
                logger.warning(f"IndexNow [{ep}] warning status {resp.status_code}: {resp.text[:150]}")
        except Exception as e:
            results[ep] = {"status_code": 0, "text": str(e), "success": False}
            logger.error(f"IndexNow [{ep}] connection error: {e}")
    return results


def submit_urls_to_indexnow(
    urls: Iterable[str],
    key: Optional[str] = None,
    host: Optional[str] = None,
    async_req: bool = True,
) -> dict:
    """
    Отправляет список URL-адресов в IndexNow (Яндекс и Bing).
    
    :param urls: итерируемый набор относительных или абсолютных URL
    :param key: опциональный API-ключ (если None, берется из настроек)
    :param host: опциональный хост (если None, берется из настроек)
    :param async_req: выполнять ли отправку в фоновом демоническом потоке
    """
    clean_host = host or get_site_host()
    api_key = key or get_indexnow_key()
    base_url = get_site_base_url()

    # Приводим все адреса к абсолютному виду
    clean_urls = []
    for u in urls:
        if not u:
            continue
        u_str = str(u).strip()
        if not u_str.startswith("http://") and not u_str.startswith("https://"):
            u_str = f"{base_url}/{u_str.lstrip('/')}"
        clean_urls.append(u_str)

    # Дедупликация с сохранением порядка
    seen = set()
    dedup_urls = []
    for u in clean_urls:
        if u not in seen:
            seen.add(u)
            dedup_urls.append(u)

    if not dedup_urls:
        return {"error": "No URLs provided"}

    # Лимит IndexNow — до 10 000 URL за один POST
    batch = dedup_urls[:10000]

    payload = {
        "host": clean_host,
        "key": api_key,
        "keyLocation": f"{base_url}/{api_key}.txt",
        "urlList": batch,
    }

    if async_req:
        thread = threading.Thread(
            target=_send_payload,
            args=(payload,),
            daemon=True,
            name="IndexNowSenderThread",
        )
        thread.start()
        return {"status": "async_started", "urls_count": len(batch)}
    else:
        return _send_payload(payload)


def collect_all_site_urls() -> List[str]:
    """
    Собирает все публичные и активные URL сайта для первичной или полной переиндексации:
    - Главная и основные статические разделы (Каталог, О нас, Доставка, Контакты, FAQ, Отзывы, Статьи, Новости, Карта сайта)
    - Все активные категории каталога
    - Все активные товары
    - Все опубликованные статьи
    - Все опубликованные новости
    - Все опубликованные динамические страницы Page
    - Карта сайта sitemap.xml
    """
    base_url = get_site_base_url()
    urls = []

    # 1. Основные страницы
    static_paths = [
        "/",
        "/catalog/",
        "/categories/",
        "/about/",
        "/delivery/",
        "/contacts/",
        "/faq/",
        "/reviews/",
        "/articles/",
        "/news/",
        "/sitemap/",
        "/sitemap.xml",
    ]
    for p in static_paths:
        urls.append(f"{base_url}{p}")

    # 2. Категории
    try:
        from shop.models import Category
        for c in Category.objects.filter(is_active=True):
            urls.append(f"{base_url}/catalog/?cat={c.slug}")
    except Exception as e:
        logger.warning(f"Error collecting categories: {e}")

    # 3. Товары
    try:
        from shop.models import Product
        for p in Product.objects.filter(is_active=True):
            urls.append(f"{base_url}{p.get_absolute_url()}")
    except Exception as e:
        logger.warning(f"Error collecting products: {e}")

    # 4. Статьи
    try:
        from articles.models import Article
        for a in Article.objects.filter(is_published=True):
            urls.append(f"{base_url}{a.get_absolute_url()}")
    except Exception as e:
        logger.warning(f"Error collecting articles: {e}")

    # 5. Новости
    try:
        from news.models import News
        for n in News.objects.filter(is_published=True):
            urls.append(f"{base_url}{n.get_absolute_url()}")
    except Exception as e:
        logger.warning(f"Error collecting news: {e}")

    # 6. Динамические страницы
    try:
        from main.models import Page
        for pg in Page.objects.filter(is_published=True, sitemap_include=True):
            if "noindex" not in pg.meta_robots_index:
                urls.append(f"{base_url}{pg.get_absolute_url()}")
    except Exception as e:
        logger.warning(f"Error collecting pages: {e}")

    return urls


def submit_all_site_urls(async_req: bool = False) -> dict:
    """Собирает все актуальные страницы сайта и отправляет их в IndexNow."""
    urls = collect_all_site_urls()
    return submit_urls_to_indexnow(urls, async_req=async_req)
