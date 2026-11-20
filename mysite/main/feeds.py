"""
Модуль синдикации RSS-лент (RSS 2.0) для проекта sibsir.ru.
Предоставляет стандартизированные фиды для новостей, статей и общей активности сыроварни «Сибсыр».
Поддерживает стандарты RSS 2.0, Dublin Core, Yahoo Media RSS и Atom.
"""
from django.contrib.syndication.views import Feed
from django.utils.feedgenerator import Rss201rev2Feed
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
import re

from .models import SiteSettings
from news.models import News
from articles.models import Article


class ExtendedRssFeed(Rss201rev2Feed):
    """
    Расширенный генератор RSS 2.0 со строгой поддержкой расширений:
    - xmlns:content (полный HTML-текст в <content:encoded>)
    - xmlns:media (обложки и иллюстрации в <media:content> и <media:thumbnail>)
    - xmlns:atom (канонический тег <atom:link rel="self">)
    - логотип и метаданные сыроварни в заголовке фида
    """
    def root_attributes(self):
        attrs = super().root_attributes()
        attrs['xmlns:content'] = 'http://purl.org/rss/1.0/modules/content/'
        attrs['xmlns:media'] = 'http://search.yahoo.com/mrss/'
        attrs['xmlns:atom'] = 'http://www.w3.org/2005/Atom'
        return attrs

    def add_root_elements(self, handler):
        super().add_root_elements(handler)
        handler.addQuickElement('language', 'ru-RU')
        
        settings = SiteSettings.get_solo()
        base_url = (settings.site_base_url or 'https://sibsir.ru').rstrip('/')
        brand = settings.brand_short_name or 'Сибсыр'
        
        # Логотип канала RSS
        logo_url = f"{base_url}{settings.logo.url}" if settings.logo else f"{base_url}/static/images/favicon.svg"
        handler.startElement('image', {})
        handler.addQuickElement('url', logo_url)
        handler.addQuickElement('title', f"ТМ «{brand}» — Сыроваренное предприятие")
        handler.addQuickElement('link', base_url)
        handler.addQuickElement('description', f"Официальный логотип ТМ «{brand}»")
        handler.endElement('image')
        
        # Копирайт
        handler.addQuickElement('copyright', f"© 1999–{timezone.now().year} {settings.brand_name}")
        handler.addQuickElement('managingEditor', f"{settings.email or 'sibs@list.ru'} ({settings.brand_short_name or 'Сибсыр'})")
        handler.addQuickElement('webMaster', f"{settings.email or 'sibs@list.ru'} (Техническая поддержка {settings.brand_short_name or 'Сибсыр'})")

    def add_item_elements(self, handler, item):
        super().add_item_elements(handler, item)
        # 1. Полный HTML контент для ридеров
        if item.get('content_encoded'):
            handler.addQuickElement('content:encoded', item['content_encoded'])
        
        # 2. Медиа-обложка (Yahoo Media RSS)
        if item.get('media_url'):
            media_attrs = {
                'url': item['media_url'],
                'medium': 'image',
                'type': 'image/jpeg',
            }
            if item.get('media_title'):
                media_attrs['title'] = item['media_title']
            handler.addQuickElement('media:content', '', media_attrs)
            handler.addQuickElement('media:thumbnail', '', {'url': item['media_url']})


class BaseSibsirFeed(Feed):
    """Базовый класс для фидов с общей логикой ссылок, изображений и форматирования."""
    feed_type = ExtendedRssFeed

    def get_base_url(self):
        settings = SiteSettings.get_solo()
        return (settings.site_base_url or 'https://sibsir.ru').rstrip('/')

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        raw = getattr(item, 'snippet', '') or getattr(item, 'content', '') or ''
        clean = strip_tags(raw).replace('&nbsp;', ' ').strip()
        if len(clean) > 350:
            return clean[:347] + '...'
        return clean

    def item_link(self, item):
        return item.get_absolute_url()

    def item_guid(self, item):
        base_url = self.get_base_url()
        return f"{base_url}{item.get_absolute_url()}"

    def item_guid_is_permalink(self, item):
        return True

    def item_author_name(self, item):
        settings = SiteSettings.get_solo()
        return settings.brand_short_name or "Сибсыр"

    def item_author_email(self, item):
        settings = SiteSettings.get_solo()
        return settings.email or "sibs@list.ru"

    def _get_item_image_url(self, item):
        base_url = self.get_base_url()
        img = getattr(item, 'image', None)
        if img:
            try:
                url = img.url
                return url if url.startswith('http') else f"{base_url}{url}"
            except Exception:
                pass
        return None

    def item_enclosure_url(self, item):
        return self._get_item_image_url(item)

    def item_enclosure_length(self, item):
        return "0"

    def item_enclosure_mime_type(self, item):
        if self._get_item_image_url(item):
            return "image/jpeg"
        return None

    def item_extra_kwargs(self, item):
        extra = {}
        # Полный текст публикации
        content = getattr(item, 'content', '')
        if content:
            extra['content_encoded'] = content
        # Обложка
        img_url = self._get_item_image_url(item)
        if img_url:
            extra['media_url'] = img_url
            extra['media_title'] = getattr(item, 'title', '')
        return extra


class LatestEntriesFeed(BaseSibsirFeed):
    """
    Общая RSS-лента всех публикаций сыроварни «Сибсыр».
    Объединяет последние опубликованные новости и статьи базы знаний в единый хронологический поток.
    """
    def title(self):
        settings = SiteSettings.get_solo()
        return f"{settings.brand_short_name or 'Сибсыр'} — Новости, события и статьи сыроварни"

    def link(self):
        return "/"

    def description(self):
        settings = SiteSettings.get_solo()
        return (
            f"Официальная новостная лента и блог сыродельного завода «{settings.brand_short_name or 'Сибсыр'}» (Омск). "
            f"Свежие события производства, поступления в каталог сыров, акции и гастрономические статьи."
        )

    def items(self):
        news = list(News.objects.filter(is_published=True).order_by('-published_at', '-id')[:20])
        articles = list(Article.objects.filter(is_published=True).order_by('-created_at', '-id')[:20])
        
        def get_date(obj):
            if isinstance(obj, News):
                return obj.published_at or timezone.now()
            return obj.created_at or timezone.now()

        combined = sorted(news + articles, key=get_date, reverse=True)
        return combined[:30]

    def item_pubdate(self, item):
        if isinstance(item, News):
            return item.published_at
        return item.created_at

    def item_categories(self, item):
        if isinstance(item, News):
            cat_name = item.get_news_type_display() if hasattr(item, 'get_news_type_display') else "Новости"
            return [cat_name, "Новости сыроварни"]
        return ["Статьи о сыре", "База знаний"]


class NewsFeed(BaseSibsirFeed):
    """
    Специализированная RSS-лента новостей сыроварни «Сибсыр».
    Содержит обновления каталога, события завода, акции и пресс-релизы.
    """
    def title(self):
        settings = SiteSettings.get_solo()
        return f"Новости сыроварни {settings.brand_short_name or 'Сибсыр'}"

    def link(self):
        return reverse('news:news_list')

    def description(self):
        settings = SiteSettings.get_solo()
        return (
            f"Лента новостей сыродельного предприятия ТМ «{settings.brand_short_name or 'Сибсыр'}» (г. Омск). "
            f"Анонсы новинок продукции, сезонные скидки, модернизация производства и жизнь сыроварни."
        )

    def items(self):
        return News.objects.filter(is_published=True).order_by('-published_at', '-id')[:35]

    def item_pubdate(self, item):
        return item.published_at

    def item_updateddate(self, item):
        return item.updated_at

    def item_categories(self, item):
        cat_name = item.get_news_type_display() if hasattr(item, 'get_news_type_display') else "Новости"
        return [cat_name, "Новости сыроварни «Сибсыр»"]


class ArticlesFeed(BaseSibsirFeed):
    """
    Специализированная RSS-лента статей и базы знаний о сыре.
    Содержит авторские статьи мастеров-сыроделов, кулинарные рецепты и советы экспертов.
    """
    def title(self):
        settings = SiteSettings.get_solo()
        return f"Статьи и рецепты сыроварни {settings.brand_short_name or 'Сибсыр'}"

    def link(self):
        return reverse('main:articles')

    def description(self):
        settings = SiteSettings.get_solo()
        return (
            f"База знаний и полезные материалы от мастеров ТМ «{settings.brand_short_name or 'Сибсыр'}»: "
            f"как выбрать натуральный сыр, условия правильного созревания и хранения, гастрономические пары и авторские рецепты."
        )

    def items(self):
        return Article.objects.filter(is_published=True).order_by('order', '-created_at', '-id')[:35]

    def item_pubdate(self, item):
        return item.created_at

    def item_categories(self, item):
        return ["Статьи о сыре", "Рецепты", "Сыроделие"]
