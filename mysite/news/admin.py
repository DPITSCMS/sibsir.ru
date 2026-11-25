from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils import timezone
from .models import News
from .forms import NewsAdminForm


# ---------------------------------------------------------------------------
# Кастомный фильтр: только авто/ручные новости
# ---------------------------------------------------------------------------
class SourceActionFilter(admin.SimpleListFilter):
    title = "Действие-источник"
    parameter_name = "source_action"

    def lookups(self, request, model_admin):
        return [
            ("create", "✨ Создание"),
            ("update", "✏️ Обновление"),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(source_action=self.value())
        return queryset


# ---------------------------------------------------------------------------
# Кастомный фильтр: наличие изображения
# ---------------------------------------------------------------------------
class HasImageFilter(admin.SimpleListFilter):
    title = "Изображение"
    parameter_name = "has_image"

    def lookups(self, request, model_admin):
        return [
            ("yes", "✅ С изображением"),
            ("no", "❌ Без изображения"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(image="").exclude(image__isnull=True)
        if self.value() == "no":
            return queryset.filter(image="") | queryset.filter(image__isnull=True)
        return queryset


# ---------------------------------------------------------------------------
# Кастомный фильтр: наличие связей с каталогом
# ---------------------------------------------------------------------------
class HasRelatedFilter(admin.SimpleListFilter):
    title = "Связи с каталогом"
    parameter_name = "has_related"

    def lookups(self, request, model_admin):
        return [
            ("products", "🛒 Есть товары"),
            ("categories", "📂 Есть категории"),
            ("none", "— Без связей"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "products":
            return queryset.filter(related_products__isnull=False).distinct()
        if self.value() == "categories":
            return queryset.filter(related_categories__isnull=False).distinct()
        if self.value() == "none":
            return queryset.filter(
                related_products__isnull=True,
                related_categories__isnull=True,
            ).distinct()
        return queryset


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    form = NewsAdminForm
    date_hierarchy = "published_at"
    save_on_top = True
    list_per_page = 25
    show_full_result_count = True
    view_on_site = True

    list_display = (
        "published_at_formatted",
        "image_thumbnail",
        "title",
        "news_type_badge",
        "related_items_badge",
        "is_auto_generated_badge",
        "views_count",
        "is_published",
        "view_link",
    )
    list_display_links = ("title",)
    list_editable = ("is_published",)

    list_filter = (
        "is_published",
        "news_type",
        "is_auto_generated",
        SourceActionFilter,
        HasImageFilter,
        HasRelatedFilter,
        "related_categories",
        ("published_at", admin.DateFieldListFilter),
    )

    search_fields = ("title", "snippet", "content", "slug", "source_model")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = (
        "created_at",
        "updated_at",
        "is_auto_generated",
        "source_model",
        "source_action",
        "views_count",
    )
    filter_horizontal = ("related_products", "related_categories")

    # Устраняем N+1: prefetch связей M2M для list_display
    list_select_related = False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("related_products", "related_categories")

    fieldsets = (
        ("Основная информация", {
            "fields": ("title", "slug", "news_type", "image", "snippet", "content")
        }),
        ("Прикрепление к каталогу (Товары и Категории)", {
            "fields": ("related_products", "related_categories"),
            "description": (
                "Прикрепите новость к конкретным товарам или категориям каталога. "
                "Новость появится на страницах этих товаров и категорий, "
                "а сами товары будут показаны в новости."
            ),
        }),
        ("Дата публикации и параметры отображения", {
            "fields": (
                "published_at",
                "is_published",
                "views_count",
                "related_url",
            ),
            "description": (
                "Дата и время публикации определяют группировку "
                "по дню, месяцу и году на сайте."
            ),
        }),
        ("Системные сведения об автогенерации", {
            "classes": ("collapse",),
            "fields": (
                "is_auto_generated",
                "source_model",
                "source_action",
                "created_at",
                "updated_at",
            ),
            "description": "Сведения об источнике изменений на сайте.",
        }),
        ("Поисковая оптимизация (SEO)", {
            "classes": ("collapse",),
            "fields": ("meta_title", "meta_description", "meta_keywords"),
            "description": (
                "Теги для поисковиков Яндекс и Google. "
                "Если оставить пустыми, генерируются автоматически."
            ),
        }),
    )

    actions = [
        "make_published",
        "make_unpublished",
        "generate_seo_selected",
        "delete_auto_generated",
        "reset_views_count",
    ]

    # -------------------------------------------------------------------
    # list_display: колонки
    # -------------------------------------------------------------------

    @admin.display(description="Дата публикации", ordering="published_at")
    def published_at_formatted(self, obj):
        if not obj.published_at:
            return "-"
        is_future = obj.published_at > timezone.now()
        status_dot = "⏳" if is_future else "🟢"
        return format_html(
            '<div style="font-size: 0.85rem; font-weight: 600; white-space: nowrap;">'
            "{} {}<br><small style=\"font-weight: 400; color: #64748b;\">{}</small></div>",
            status_dot,
            obj.formatted_date,
            f"{obj.formatted_time} ({obj.weekday_name})",
        )

    @admin.display(description="Тип новости")
    def news_type_badge(self, obj):
        colors = {
            "product":  "#10b981",
            "category": "#06b6d4",
            "promo":    "#ef4444",
            "article":  "#3b82f6",
            "review":   "#f59e0b",
            "page":     "#6b7280",
            "site":     "#475569",
            "edit":     "#8b5cf6",
            "general":  "#ff8400",
        }
        color = colors.get(obj.news_type, "#ff8400")
        label = obj.get_news_type_display()
        return format_html(
            '<span style="display: inline-block; padding: 2px 8px; border-radius: 12px; '
            'font-size: 11px; font-weight: 600; color: #fff; background-color: {};">{}</span>',
            color,
            label,
        )

    @admin.display(description="Связи с каталогом")
    def related_items_badge(self, obj):
        # prefetch_related сделан в get_queryset — count() не делает доп. запрос
        p_cnt = len(obj.related_products.all())
        c_cnt = len(obj.related_categories.all())
        parts = []
        if p_cnt:
            parts.append(
                f'<span style="background: #e0f2fe; color: #0369a1; padding: 2px 6px; '
                f'border-radius: 4px; font-weight: 600; font-size: 11px;">{p_cnt} тов.</span>'
            )
        if c_cnt:
            parts.append(
                f'<span style="background: #fef3c7; color: #b45309; padding: 2px 6px; '
                f'border-radius: 4px; font-weight: 600; font-size: 11px;">{c_cnt} кат.</span>'
            )
        if parts:
            return mark_safe(" ".join(parts))
        return "—"

    @admin.display(description="Источник")
    def is_auto_generated_badge(self, obj):
        if obj.is_auto_generated:
            action = f" ({obj.source_model})" if obj.source_model else ""
            return format_html(
                '<span style="color: #6366f1; font-size: 11px; font-weight: 600;">🤖 Авто{}</span>',
                action,
            )
        return mark_safe('<span style="color: #64748b; font-size: 11px;">✍️ Ручная</span>')

    @admin.display(description="Превью")
    def image_thumbnail(self, obj):
        url = obj.image_url
        if url:
            return format_html(
                '<img src="{}" style="width: 50px; height: 35px; object-fit: cover; border-radius: 4px;" />',
                url,
            )
        return "-"

    @admin.display(description="Витрина")
    def view_link(self, obj):
        if obj.is_published:
            return format_html(
                '<a href="{}" target="_blank" title="Открыть новость на сайте" '
                'style="color: var(--admin-primary); text-decoration: none; '
                'font-size: 0.85rem; font-weight: 600;">↗ На сайт</a>',
                obj.get_absolute_url(),
            )
        # Для черновика показываем ссылку на связанный объект, если есть
        if obj.related_url:
            return format_html(
                '<span style="color: #94a3b8; font-size: 0.78rem;">Черновик &mdash; '
                '<a href="{}" target="_blank" style="color: #94a3b8;">↗ объект</a></span>',
                obj.related_url,
            )
        return mark_safe('<span style="color: #94a3b8; font-size: 0.78rem;">Черновик</span>')

    # -------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------

    @admin.action(description="✅ Опубликовать выбранные новости")
    def make_published(self, request, queryset):
        count = queryset.update(is_published=True)
        self.message_user(request, f"Опубликовано новостей: {count}.")

    @admin.action(description="⏸️ Снять с публикации выбранные новости")
    def make_unpublished(self, request, queryset):
        count = queryset.update(is_published=False)
        self.message_user(request, f"Снято с публикации новостей: {count}.")

    @admin.action(description="⚡ Сгенерировать SEO-теги")
    def generate_seo_selected(self, request, queryset):
        count = 0
        for item in queryset:
            item.generate_seo(overwrite=True)
            count += 1
        self.message_user(request, f"SEO-теги сгенерированы для {count} новостей.")

    @admin.action(description="🗑️ Удалить авто-сгенерированные новости из выборки")
    def delete_auto_generated(self, request, queryset):
        auto_qs = queryset.filter(is_auto_generated=True)
        count = auto_qs.count()
        auto_qs.delete()
        self.message_user(
            request,
            f"Удалено авто-сгенерированных новостей: {count}.",
            level="WARNING" if count else "SUCCESS",
        )

    @admin.action(description="🔄 Обнулить счётчик просмотров у выбранных")
    def reset_views_count(self, request, queryset):
        count = queryset.update(views_count=0)
        self.message_user(request, f"Обнулён счётчик просмотров у {count} новостей.")
