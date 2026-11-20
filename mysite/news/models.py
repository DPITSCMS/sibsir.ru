import re
import uuid
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.templatetags.static import static
from django.utils.text import slugify
from tinymce.models import HTMLField

RUSSIAN_MONTHS_GENITIVE = [
    "",
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]

RUSSIAN_MONTHS_NOMINATIVE = [
    "",
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
]

RUSSIAN_WEEKDAYS = [
    "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"
]

TRANSLIT_MAP = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    ' ': '-', '_': '-'
}


def transliterate_to_slug(text: str) -> str:
    """Транслитерация русскоязычного текста в латинский slug."""
    text = (text or "").lower().strip()
    result = []
    for ch in text:
        if ch in TRANSLIT_MAP:
            result.append(TRANSLIT_MAP[ch])
        elif ch.isalnum() or ch == '-':
            result.append(ch)
    raw = "".join(result)
    slug = slugify(raw)
    return slug[:180] or "novost"


class News(models.Model):
    TYPE_CHOICES = [
        ("general", "Общая новость сыроварни"),
        ("product", "Новинки и ассортимент товаров"),
        ("category", "Категории каталога"),
        ("promo", "Акции и спецпредложения"),
        ("article", "Статьи и рецепты"),
        ("review", "Отзывы клиентов"),
        ("page", "Страницы и разделы сайта"),
        ("site", "События и реквизиты компании"),
        ("edit", "Редактирование новости"),
    ]

    title = models.CharField(max_length=255, verbose_name="Заголовок новости")
    slug = models.SlugField(max_length=255, unique=True, verbose_name="Слаг (URL)")
    snippet = models.TextField(verbose_name="Краткий анонс")
    content = HTMLField(verbose_name="Полный текст новости")
    image = models.ImageField(upload_to="news/", blank=True, null=True, verbose_name="Изображение / баннер")
    published_at = models.DateTimeField(
        default=timezone.now, 
        verbose_name="Дата и время публикации", 
        db_index=True,
        help_text="Определяет день, месяц и год публикации новости"
    )
    is_published = models.BooleanField(default=True, verbose_name="Опубликовано")
    views_count = models.PositiveIntegerField(default=0, verbose_name="Просмотры")
    news_type = models.CharField(
        max_length=30, 
        choices=TYPE_CHOICES, 
        default="general", 
        verbose_name="Категория / Тип новости"
    )
    is_auto_generated = models.BooleanField(
        default=False, 
        verbose_name="Создана автоматически при изменении на сайте"
    )
    source_model = models.CharField(max_length=60, blank=True, verbose_name="Модель-источник")
    source_action = models.CharField(max_length=60, blank=True, verbose_name="Действие-источник")
    related_url = models.CharField(max_length=255, blank=True, verbose_name="Ссылка на связанный объект/раздел")

    # SEO поля
    meta_title = models.CharField(max_length=255, blank=True, verbose_name="SEO Заголовок (Title)")
    meta_description = models.TextField(blank=True, verbose_name="SEO Описание (Description)")
    meta_keywords = models.CharField(max_length=255, blank=True, verbose_name="SEO Ключевые слова (Keywords)")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания записи")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата последнего изменения")

    class Meta:
        verbose_name = "Новость"
        verbose_name_plural = "Новости"
        ordering = ["-published_at", "-id"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        if self.slug:
            return reverse("news:news_detail", kwargs={"slug": self.slug})
        return reverse("news:news_list")

    @property
    def image_url(self):
        if self.image and hasattr(self.image, "url"):
            return self.image.url
        return static("images/hero_cheese.jpg")

    # ---------------------------------------------------------
    # Хелперы группировки по дате: День, Месяц, Год
    # ---------------------------------------------------------
    @property
    def year(self):
        return self.published_at.year if self.published_at else None

    @property
    def month(self):
        return self.published_at.month if self.published_at else None

    @property
    def day(self):
        return self.published_at.day if self.published_at else None

    @property
    def month_name_genitive(self):
        if self.published_at and 1 <= self.published_at.month <= 12:
            return RUSSIAN_MONTHS_GENITIVE[self.published_at.month]
        return ""

    @property
    def month_name_nominative(self):
        if self.published_at and 1 <= self.published_at.month <= 12:
            return RUSSIAN_MONTHS_NOMINATIVE[self.published_at.month]
        return ""

    @property
    def weekday_name(self):
        if self.published_at:
            return RUSSIAN_WEEKDAYS[self.published_at.weekday()]
        return ""

    @property
    def formatted_day_month(self):
        """Пример: 21 ноября"""
        if self.published_at:
            return f"{self.published_at.day} {self.month_name_genitive}"
        return ""

    @property
    def formatted_date(self):
        """Пример: 21 ноября 2026"""
        if self.published_at:
            return f"{self.published_at.day} {self.month_name_genitive} {self.published_at.year}"
        return ""

    @property
    def formatted_date_full(self):
        """Пример: 21 ноября 2026 г., Суббота"""
        if self.published_at:
            return f"{self.published_at.day} {self.month_name_genitive} {self.published_at.year} г. ({self.weekday_name})"
        return ""

    @property
    def formatted_time(self):
        """Пример: 14:30"""
        if self.published_at:
            return self.published_at.strftime("%H:%M")
        return ""

    @property
    def formatted_datetime(self):
        """Пример: 21 ноября 2026 в 14:30"""
        if self.published_at:
            return f"{self.formatted_date} в {self.formatted_time}"
        return ""

    @property
    def date_key(self):
        """Ключ для группировки по дате (YYYY-MM-DD)"""
        if self.published_at:
            return self.published_at.strftime("%Y-%m-%d")
        return ""

    @property
    def month_key(self):
        """Ключ для группировки по месяцу (YYYY-MM)"""
        if self.published_at:
            return self.published_at.strftime("%Y-%m")
        return ""

    @property
    def badge_color(self):
        mapping = {
            "product": "success",
            "category": "info",
            "promo": "danger",
            "article": "primary",
            "review": "warning",
            "page": "secondary",
            "site": "dark",
            "edit": "info",
            "general": "warning",
        }
        return mapping.get(self.news_type, "warning")

    @property
    def badge_icon(self):
        mapping = {
            "product": "bi-bag-check-fill",
            "category": "bi-grid-fill",
            "promo": "bi-percent",
            "article": "bi-journal-richtext",
            "review": "bi-chat-quote-fill",
            "page": "bi-file-earmark-text-fill",
            "site": "bi-building-fill",
            "edit": "bi-pencil-square",
            "general": "bi-newspaper",
        }
        return mapping.get(self.news_type, "bi-newspaper")

    def generate_seo(self, overwrite=False):
        """Автоматическая генерация SEO-тегов для новости."""
        clean_title = (self.title or "").strip()
        if not self.meta_title or overwrite:
            self.meta_title = f"{clean_title} — Новости сыроварни «Сибсыр»"[:250]

        if not self.meta_description or overwrite:
            raw_text = self.snippet or self.content or ""
            clean_text = re.sub(r'<[^>]+>', '', raw_text).replace('&nbsp;', ' ').strip()
            if clean_text:
                words = clean_text.split()
                clean_text = " ".join(words[:25])
            else:
                clean_text = f"Свежая новость сыроварни «Сибсыр»: {clean_title}."
            self.meta_description = f"{clean_text} Читайте подробности на официальном сайте ТМ «Сибсыр»."[:280]

        if not self.meta_keywords or overwrite:
            self.meta_keywords = f"новости сибсыр, сыроварня омск, {clean_title.lower()}"[:250]

        if overwrite and self.pk:
            self.save(update_fields=["meta_title", "meta_description", "meta_keywords"])

    def save(self, *args, **kwargs):
        # Автоматическая генерация слага
        if not self.slug:
            base_slug = transliterate_to_slug(self.title)
            slug = base_slug
            counter = 1
            while News.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f"{base_slug}-{counter}"
            self.slug = slug

        if not self.snippet and self.content:
            clean = re.sub(r'<[^>]+>', '', self.content).replace('&nbsp;', ' ').strip()
            self.snippet = clean[:250] + ("..." if len(clean) > 250 else "")

        if not self.meta_title or not self.meta_description or not self.meta_keywords:
            self.generate_seo(overwrite=False)

        super().save(*args, **kwargs)
