from django.templatetags.static import static
from django.core.cache import cache
from .models import SiteSettings, SocialLink


def site_settings(request):
    """
    Глобальный процессор контекста для шаблонов сайта:
    передает объект SiteSettings, канонический URL, метатеги по умолчанию,
    домен, данные для соцсетей (OpenGraph) и список активных соцсетей.
    """
    try:
        settings_obj = SiteSettings.get_solo()
    except Exception:
        settings_obj = None

    site_base_url = "https://sibsir.ru"
    if settings_obj and settings_obj.site_base_url:
        site_base_url = settings_obj.site_base_url.rstrip('/')
    elif hasattr(request, "scheme") and hasattr(request, "get_host"):
        site_base_url = f"{request.scheme}://{request.get_host()}".rstrip('/')

    canonical_url = f"{site_base_url}{request.path}" if hasattr(request, "path") else site_base_url

    # Изображение для соцсетей по умолчанию
    og_image_url = f"{site_base_url}{static('images/hero_cheese.jpg')}"
    if settings_obj and settings_obj.seo_og_image:
        og_image_url = f"{site_base_url}{settings_obj.seo_og_image.url}"
    elif settings_obj and settings_obj.hero_image:
        og_image_url = f"{site_base_url}{settings_obj.hero_image.url}"

    brand_name = settings_obj.brand_name if settings_obj else "ТМ «Сибсыр»"
    brand_short = settings_obj.brand_short_name if settings_obj else "Сибсыр"

    nav_categories = cache.get("sibsir_nav_categories")
    if nav_categories is None:
        try:
            from shop.models import Category
            nav_categories = list(Category.objects.filter(is_active=True).order_by('order', 'id'))
            cache.set("sibsir_nav_categories", nav_categories, 120)
        except Exception:
            nav_categories = []

    social_links = cache.get("sibsir_social_links")
    if social_links is None:
        try:
            social_links = list(SocialLink.objects.filter(is_active=True).order_by('order', 'id'))
            cache.set("sibsir_social_links", social_links, 120)
        except Exception:
            social_links = []

    layout_pages_data = cache.get("sibsir_layout_pages_data")
    if layout_pages_data is None:
        try:
            from .models import Page, FooterStatBanner
            header_pages = list(Page.objects.filter(is_published=True, show_in_header=True).order_by('order', 'id'))
            footer_pages = list(Page.objects.filter(is_published=True, show_in_footer=True).order_by('order', 'id'))
            footer_stat_banners = list(FooterStatBanner.objects.filter(is_active=True).order_by('order', 'id'))
            layout_pages_data = (header_pages, footer_pages, footer_stat_banners)
            cache.set("sibsir_layout_pages_data", layout_pages_data, 120)
        except Exception:
            header_pages = []
            footer_pages = []
            footer_stat_banners = []
    else:
        header_pages, footer_pages, footer_stat_banners = layout_pages_data

    footer_payment_methods = cache.get("sibsir_footer_payments")
    if footer_payment_methods is None:
        try:
            from .models import PaymentMethod
            footer_payment_methods = list(
                PaymentMethod.objects.filter(is_active=True, show_in_footer=True).order_by('order', 'id')
            )
            cache.set("sibsir_footer_payments", footer_payment_methods, 120)
        except Exception:
            footer_payment_methods = []

    return {
        "site_settings": settings_obj,
        "site_base_url": site_base_url,
        "canonical_url": canonical_url,
        "site_og_image_url": og_image_url,
        "brand_name": brand_name,
        "brand_short_name": brand_short,
        "nav_categories": nav_categories,
        "social_links": social_links,
        "header_pages": header_pages,
        "footer_pages": footer_pages,
        "footer_stat_banners": footer_stat_banners,
        "footer_payment_methods": footer_payment_methods,
    }
