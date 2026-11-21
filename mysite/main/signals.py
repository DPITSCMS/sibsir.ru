"""
Django сигналы для автоматической поисковой индексации (IndexNow).
При создании, редактировании или удалении товаров, категорий, новостей, статей и страниц
отправляет измененные URL в поисковую систему Яндекс и Bing.
"""
import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

logger = logging.getLogger("seo.signals")


def _is_auto_submit_enabled() -> bool:
    try:
        from main.models import SiteSettings
        s = SiteSettings.get_solo()
        return bool(s.is_indexing_enabled and s.indexnow_auto_submit)
    except Exception:
        return False


def _trigger_indexnow(urls):
    if not _is_auto_submit_enabled():
        return
    try:
        from main.indexnow import submit_urls_to_indexnow
        submit_urls_to_indexnow(urls, async_req=True)
    except Exception as e:
        logger.warning(f"Failed to auto-submit to IndexNow: {e}")


def connect_seo_signals():
    """Подключает сигналы поискового оповещения для ключевых моделей контента."""
    try:
        from shop.models import Product, Category
        from articles.models import Article
        from news.models import News
        from main.models import Page

        # 1. Товары
        @receiver(post_save, sender=Product, weak=False)
        def on_product_save(sender, instance, **kwargs):
            if instance.is_active:
                urls = [instance.get_absolute_url(), "/catalog/", "/sitemap.xml"]
                if instance.category_id:
                    urls.append(f"/catalog/?cat={instance.category.slug}")
                _trigger_indexnow(urls)

        @receiver(post_delete, sender=Product, weak=False)
        def on_product_delete(sender, instance, **kwargs):
            urls = ["/catalog/", "/sitemap.xml"]
            if instance.category_id:
                urls.append(f"/catalog/?cat={instance.category.slug}")
            _trigger_indexnow(urls)

        # 2. Категории
        @receiver(post_save, sender=Category, weak=False)
        def on_category_save(sender, instance, **kwargs):
            if instance.is_active:
                _trigger_indexnow([f"/catalog/?cat={instance.slug}", "/catalog/", "/categories/", "/sitemap.xml"])

        @receiver(post_delete, sender=Category, weak=False)
        def on_category_delete(sender, instance, **kwargs):
            _trigger_indexnow(["/catalog/", "/categories/", "/sitemap.xml"])

        # 3. Статьи
        @receiver(post_save, sender=Article, weak=False)
        def on_article_save(sender, instance, **kwargs):
            if instance.is_published:
                _trigger_indexnow([instance.get_absolute_url(), "/articles/", "/sitemap.xml", "/rss/articles/"])

        @receiver(post_delete, sender=Article, weak=False)
        def on_article_delete(sender, instance, **kwargs):
            _trigger_indexnow(["/articles/", "/sitemap.xml", "/rss/articles/"])

        # 4. Новости
        @receiver(post_save, sender=News, weak=False)
        def on_news_save(sender, instance, **kwargs):
            if instance.is_published:
                _trigger_indexnow([instance.get_absolute_url(), "/news/", "/", "/sitemap.xml", "/rss/news/"])

        @receiver(post_delete, sender=News, weak=False)
        def on_news_delete(sender, instance, **kwargs):
            _trigger_indexnow(["/news/", "/", "/sitemap.xml", "/rss/news/"])

        # 5. Динамические страницы
        @receiver(post_save, sender=Page, weak=False)
        def on_page_save(sender, instance, **kwargs):
            if instance.is_published and instance.sitemap_include:
                _trigger_indexnow([instance.get_absolute_url(), "/sitemap.xml"])

        @receiver(post_delete, sender=Page, weak=False)
        def on_page_delete(sender, instance, **kwargs):
            _trigger_indexnow(["/sitemap.xml"])

    except Exception as e:
        logger.error(f"Error registering SEO signals: {e}")
