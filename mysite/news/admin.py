from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import News
from .forms import NewsAdminForm


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    form = NewsAdminForm
    date_hierarchy = "published_at"
    list_display = (
        "published_at_formatted",
        "image_thumbnail",
        "title",
        "news_type_badge",
        "is_auto_generated_badge",
        "views_count",
        "is_published",
    )
    list_display_links = ("title",)
    list_editable = ("is_published",)
    list_filter = (
        "is_published",
        "news_type",
        "is_auto_generated",
        ("published_at", admin.DateFieldListFilter),
    )
    search_fields = ("title", "snippet", "content", "slug")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at", "is_auto_generated", "source_model", "source_action")

    fieldsets = (
        ("Основная информация", {
            "fields": ("title", "slug", "news_type", "image", "snippet", "content")
        }),
        ("Дата публикации и параметры отображения", {
            "fields": (
                "published_at",
                "is_published",
                "views_count",
                "related_url",
            ),
            "description": "Дата и время публикации определяют группировку по дню, месяцу и году на сайте."
        }),
        ("Системные сведения об автогенерации", {
            "classes": ("collapse",),
            "fields": ("is_auto_generated", "source_model", "source_action", "created_at", "updated_at"),
            "description": "Сведения об источнике изменений на сайте."
        }),
        ("Поисковая оптимизация (SEO)", {
            "classes": ("collapse",),
            "fields": ("meta_title", "meta_description", "meta_keywords"),
            "description": "Теги для поисковиков Яндекс и Google. Если оставить пустыми, генерируются автоматически."
        }),
    )

    actions = ["make_published", "make_unpublished", "generate_seo_selected"]

    @admin.display(description="Дата публикации", ordering="published_at")
    def published_at_formatted(self, obj):
        if not obj.published_at:
            return "-"
        is_future = obj.published_at > timezone.now()
        status_dot = "🟢" if not is_future else "⏳"
        return format_html(
            '<div style="font-size: 0.85rem; font-weight: 600; white-space: nowrap;">'
            '{} {}<br><small class="text-muted" style="font-weight: 400; color: #64748b;">{}</small></div>',
            status_dot,
            obj.formatted_date,
            f"{obj.formatted_time} ({obj.weekday_name})"
        )

    @admin.display(description="Тип новости")
    def news_type_badge(self, obj):
        colors = {
            "product": "#10b981",
            "category": "#06b6d4",
            "promo": "#ef4444",
            "article": "#3b82f6",
            "review": "#f59e0b",
            "page": "#6b7280",
            "site": "#475569",
            "edit": "#8b5cf6",
            "general": "#ff8400",
        }
        color = colors.get(obj.news_type, "#ff8400")
        label = obj.get_news_type_display()
        return format_html(
            '<span style="display: inline-block; padding: 2px 8px; border-radius: 12px; '
            'font-size: 11px; font-weight: 600; color: #fff; background-color: {};">{}</span>',
            color,
            label
        )

    @admin.display(description="Источник")
    def is_auto_generated_badge(self, obj):
        if obj.is_auto_generated:
            action = f" ({obj.source_model})" if obj.source_model else ""
            return format_html(
                '<span style="color: #6366f1; font-size: 11px; font-weight: 600;">🤖 Авто{}</span>',
                action
            )
        return format_html('<span style="color: #64748b; font-size: 11px;">✍️ Ручная</span>')

    @admin.display(description="Превью")
    def image_thumbnail(self, obj):
        url = obj.image_url
        if url:
            return format_html(
                '<img src="{}" style="width: 50px; height: 35px; object-fit: cover; border-radius: 4px;" />',
                url
            )
        return "-"

    @admin.action(description="Опубликовать выбранные новости")
    def make_published(self, request, queryset):
        count = queryset.update(is_published=True)
        self.message_user(request, f"Опубликовано новостей: {count}.")

    @admin.action(description="Снять с публикации выбранные новости")
    def make_unpublished(self, request, queryset):
        count = queryset.update(is_published=False)
        self.message_user(request, f"Снято с публикации новостей: {count}.")

    @admin.action(description="⚡ Сгенерировать SEO-теги")
    def generate_seo_selected(self, request, queryset):
        count = 0
        for item in queryset:
            item.generate_seo(overwrite=True)
            item.save()
            count += 1
        self.message_user(request, f"SEO-теги сгенерированы для {count} новостей.")
