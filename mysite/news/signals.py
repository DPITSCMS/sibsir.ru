import threading
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import News

_signal_local = threading.local()


def _is_in_signal():
    return getattr(_signal_local, "in_news_signal", False)


class SignalGuard:
    def __enter__(self):
        _signal_local.in_news_signal = True

    def __exit__(self, exc_type, exc_val, exc_tb):
        _signal_local.in_news_signal = False


# 1. ОБРАБОТЧИК ДЛЯ САМИХ НОВОСТЕЙ (редактирование новости добавляет об этом новость)
@receiver(post_save, sender=News)
def handle_news_post_save(sender, instance, created, **kwargs):
    if kwargs.get("raw", False) or _is_in_signal():
        return

    # При создании новости повторно новость о создании не генерируется
    if created:
        return

    # Игнорируем обновление ТОЛЬКО просмотров (views_count)
    update_fields = kwargs.get("update_fields")
    if update_fields and set(update_fields) == {"views_count"}:
        return

    # Если новость была ОТРЕДАКТИРОВАНА (изменена) - требование:
    # "редактирование новости так же будет добавлять об этом новость"
    with SignalGuard():
        date_str = instance.formatted_date or instance.published_at.strftime("%d.%m.%Y")
        title = f"Отредактирована новость: «{instance.title}»"
        snippet = f"В публикацию от {date_str} «{instance.title}» были внесены изменения и уточнения."
        content = (
            f"<p>Администрация сыроварни «Сибсыр» внесла актуальные изменения в новость "
            f'<strong><a href="{instance.get_absolute_url()}">«{instance.title}»</a></strong>.</p>'
            f"<p>Ознакомьтесь с обновленными материалами на странице публикации.</p>"
        )
        News.objects.create(
            title=title,
            snippet=snippet,
            content=content,
            news_type="edit",
            is_published=True,
            is_auto_generated=True,
            source_model="News",
            source_action="update",
            related_url=instance.get_absolute_url(),
            published_at=timezone.now(),
        )


# 2. ОБРАБОТЧИК ДЛЯ ТОВАРОВ (Product)
try:
    from shop.models import Product

    @receiver(post_save, sender=Product)
    def handle_product_post_save(sender, instance, created, **kwargs):
        if kwargs.get("raw", False) or _is_in_signal():
            return

        with SignalGuard():
            if created:
                title = f"Новинка в каталоге: {instance.title}"
                snippet = (
                    f"В ассортимент сыроварни «Сибсыр» поступил новый товар: «{instance.title}». "
                    f"Натуральное сырье и стандарты качества ГОСТ."
                )
                desc = f"<p>{instance.description}</p>" if instance.description else ""
                content = (
                    f"<p>Рады сообщить о пополнении каталога сыроварни «Сибсыр»! "
                    f"В продажу поступил товар <strong>{instance.title}</strong>.</p>"
                    f"{desc}"
                    f'<p class="mt-3"><a href="{instance.get_absolute_url()}" class="btn btn-warning">'
                    f'Посмотреть товар в каталоге →</a></p>'
                )
                news = News(
                    title=title,
                    snippet=snippet,
                    content=content,
                    news_type="product",
                    is_published=True,
                    is_auto_generated=True,
                    source_model="Product",
                    source_action="create",
                    related_url=instance.get_absolute_url(),
                    published_at=timezone.now(),
                )
                if instance.image:
                    news.image = instance.image
                news.save()
            else:
                title = f"Обновлен товар: {instance.title}"
                snippet = f"Обновлена информация и характеристики товара «{instance.title}» в каталоге продукции."
                content = (
                    f"<p>В каталоге сыроварни обновлена карточка продукции "
                    f'<strong><a href="{instance.get_absolute_url()}">{instance.title}</a></strong>. '
                    f"Уточняйте актуальные цены, фасовку и наличие на складе.</p>"
                )
                News.objects.create(
                    title=title,
                    snippet=snippet,
                    content=content,
                    news_type="product",
                    is_published=True,
                    is_auto_generated=True,
                    source_model="Product",
                    source_action="update",
                    related_url=instance.get_absolute_url(),
                    published_at=timezone.now(),
                )
except ImportError:
    pass


# 3. ОБРАБОТЧИК ДЛЯ КАТЕГОРИЙ (Category)
try:
    from shop.models import Category

    @receiver(post_save, sender=Category)
    def handle_category_post_save(sender, instance, created, **kwargs):
        if kwargs.get("raw", False) or _is_in_signal():
            return

        with SignalGuard():
            url = f"/catalog/?cat={instance.slug}"
            if created:
                title = f"Новый раздел в каталоге: {instance.name}"
                snippet = f"В каталоге сыров и молочной продукции открыта новая категория: «{instance.name}»."
                content = (
                    f"<p>Мы расширили структуру каталога! Создан новый раздел продукции: "
                    f'<strong><a href="{url}">{instance.name}</a></strong>.</p>'
                    f"<p>Приглашаем ознакомиться с ассортиментом раздела.</p>"
                )
                news = News(
                    title=title,
                    snippet=snippet,
                    content=content,
                    news_type="category",
                    is_published=True,
                    is_auto_generated=True,
                    source_model="Category",
                    source_action="create",
                    related_url=url,
                    published_at=timezone.now(),
                )
                if instance.image:
                    news.image = instance.image
                news.save()
            else:
                title = f"Обновлена категория продукции: {instance.name}"
                snippet = f"Обновлена информация в разделе «{instance.name}» каталога «Сибсыр»."
                content = (
                    f"<p>Обновлены описания и состав категории "
                    f'<strong><a href="{url}">{instance.name}</a></strong>.</p>'
                )
                News.objects.create(
                    title=title,
                    snippet=snippet,
                    content=content,
                    news_type="category",
                    is_published=True,
                    is_auto_generated=True,
                    source_model="Category",
                    source_action="update",
                    related_url=url,
                    published_at=timezone.now(),
                )
except ImportError:
    pass


# 4. ОБРАБОТЧИК ДЛЯ АКЦИЙ (Promotion)
try:
    from shop.models import Promotion

    @receiver(post_save, sender=Promotion)
    def handle_promotion_post_save(sender, instance, created, **kwargs):
        if kwargs.get("raw", False) or _is_in_signal():
            return

        with SignalGuard():
            if created:
                title = f"Новая выгодная акция: {instance.title}"
                snippet = instance.subtitle or f"Стартовала новая акция для покупателей сыроварни: «{instance.title}»."
                desc = f"<p>{instance.description}</p>" if instance.description else ""
                content = (
                    f"<p>Для всех клиентов сыроварни «Сибсыр» действует специальное предложение: "
                    f"<strong>{instance.title}</strong>!</p>"
                    f"{desc}"
                    f'<p class="mt-3"><a href="/catalog/" class="btn btn-warning">Перейти к покупкам →</a></p>'
                )
                news = News(
                    title=title,
                    snippet=snippet,
                    content=content,
                    news_type="promo",
                    is_published=True,
                    is_auto_generated=True,
                    source_model="Promotion",
                    source_action="create",
                    related_url="/catalog/",
                    published_at=timezone.now(),
                )
                if instance.image:
                    news.image = instance.image
                news.save()
            else:
                title = f"Обновлены условия акции: {instance.title}"
                snippet = f"Внесены изменения в условия специального предложения «{instance.title}»."
                content = (
                    f"<p>Обратите внимание: обновлены условия акции "
                    f"<strong>{instance.title}</strong>. Подробности уточняйте у менеджеров или в каталоге.</p>"
                )
                News.objects.create(
                    title=title,
                    snippet=snippet,
                    content=content,
                    news_type="promo",
                    is_published=True,
                    is_auto_generated=True,
                    source_model="Promotion",
                    source_action="update",
                    related_url="/catalog/",
                    published_at=timezone.now(),
                )
except ImportError:
    pass


# 5. ОБРАБОТЧИК ДЛЯ СТАТЕЙ (Article)
try:
    from articles.models import Article

    @receiver(post_save, sender=Article)
    def handle_article_post_save(sender, instance, created, **kwargs):
        if kwargs.get("raw", False) or _is_in_signal():
            return

        with SignalGuard():
            if created:
                title = f"Новая статья в блоге: {instance.title}"
                snippet = instance.snippet or f"Опубликован новый полезный материал: «{instance.title}»."
                content = (
                    f"<p>В базе знаний сыроварни опубликована новая полезная статья: "
                    f'<strong><a href="{instance.get_absolute_url()}">«{instance.title}»</a></strong>.</p>'
                    f"<p>{snippet}</p>"
                    f'<p><a href="{instance.get_absolute_url()}" class="btn btn-outline-warning">Читать статью полностью →</a></p>'
                )
                news = News(
                    title=title,
                    snippet=snippet,
                    content=content,
                    news_type="article",
                    is_published=True,
                    is_auto_generated=True,
                    source_model="Article",
                    source_action="create",
                    related_url=instance.get_absolute_url(),
                    published_at=timezone.now(),
                )
                if instance.image:
                    news.image = instance.image
                news.save()
            else:
                title = f"Обновлена статья: {instance.title}"
                snippet = f"Материал «{instance.title}» был дополнен актуальной информацией и советами экспертов."
                content = (
                    f"<p>Мы обновили статью "
                    f'<strong><a href="{instance.get_absolute_url()}">«{instance.title}»</a></strong> '
                    f"в базе знаний сыроварни. Приглашаем ознакомиться с дополнениями!</p>"
                )
                News.objects.create(
                    title=title,
                    snippet=snippet,
                    content=content,
                    news_type="article",
                    is_published=True,
                    is_auto_generated=True,
                    source_model="Article",
                    source_action="update",
                    related_url=instance.get_absolute_url(),
                    published_at=timezone.now(),
                )
except ImportError:
    pass


# 6. ОБРАБОТЧИК ДЛЯ ОТЗЫВОВ (Review)
try:
    from shop.models import Review

    @receiver(post_save, sender=Review)
    def handle_review_post_save(sender, instance, created, **kwargs):
        if kwargs.get("raw", False) or _is_in_signal():
            return

        if created and instance.is_active:
            with SignalGuard():
                title = f"Новый отзыв о продукции «Сибсыр»"
                snippet = f"Покупатель {instance.author_name} оставил отзыв с оценкой {instance.rating}★."
                content = (
                    f"<p>Благодарим за обратную связь! Покупатель <strong>{instance.author_name}</strong> "
                    f"оставил отзыв о продукции «Сибсыр» с оценкой <strong>{instance.rating} из 5</strong>.</p>"
                    f"<blockquote>«{instance.text}»</blockquote>"
                    f'<p><a href="/reviews/">Смотреть все отзывы покупателей →</a></p>'
                )
                News.objects.create(
                    title=title,
                    snippet=snippet,
                    content=content,
                    news_type="review",
                    is_published=True,
                    is_auto_generated=True,
                    source_model="Review",
                    source_action="create",
                    related_url="/reviews/",
                    published_at=timezone.now(),
                )
except ImportError:
    pass


# 7. ОБРАБОТЧИК ДЛЯ СТРАНИЦ САЙТА (Page)
try:
    from main.models import Page

    @receiver(post_save, sender=Page)
    def handle_page_post_save(sender, instance, created, **kwargs):
        if kwargs.get("raw", False) or _is_in_signal():
            return

        with SignalGuard():
            if created:
                title = f"Новая страница на сайте: {instance.title}"
                snippet = f"На сайте сыроварни опубликован новый информационный раздел: «{instance.title}»."
                content = (
                    f"<p>На официальном сайте ТМ «Сибсыр» открыта страница: "
                    f'<strong><a href="{instance.get_absolute_url()}">{instance.title}</a></strong>.</p>'
                )
                News.objects.create(
                    title=title,
                    snippet=snippet,
                    content=content,
                    news_type="page",
                    is_published=True,
                    is_auto_generated=True,
                    source_model="Page",
                    source_action="create",
                    related_url=instance.get_absolute_url(),
                    published_at=timezone.now(),
                )
            else:
                title = f"Обновлена страница «{instance.title}»"
                snippet = f"Обновлена информация в разделе «{instance.title}» на сайте «Сибсыр»."
                content = (
                    f"<p>Обновлено содержание страницы "
                    f'<strong><a href="{instance.get_absolute_url()}">{instance.title}</a></strong>.</p>'
                )
                News.objects.create(
                    title=title,
                    snippet=snippet,
                    content=content,
                    news_type="page",
                    is_published=True,
                    is_auto_generated=True,
                    source_model="Page",
                    source_action="update",
                    related_url=instance.get_absolute_url(),
                    published_at=timezone.now(),
                )
except ImportError:
    pass


# 8. ОБРАБОТЧИК ДЛЯ НАСТРОЕК САЙТА (SiteSettings)
try:
    from main.models import SiteSettings

    @receiver(post_save, sender=SiteSettings)
    def handle_site_settings_post_save(sender, instance, created, **kwargs):
        if kwargs.get("raw", False) or _is_in_signal() or created:
            return

        with SignalGuard():
            title = "Обновлена информация и реквизиты сыроварни"
            snippet = "На официальном сайте актуализированы контакты, график работы или реквизиты ТМ «Сибсыр»."
            content = (
                "<p>На сайте ТМ «Сибсыр» обновлены общие сведения о компании, "
                "контактные данные или график работы отделов.</p>"
                '<p><a href="/contacts/">Перейти в раздел «Контакты» →</a></p>'
            )
            News.objects.create(
                title=title,
                snippet=snippet,
                content=content,
                news_type="site",
                is_published=True,
                is_auto_generated=True,
                source_model="SiteSettings",
                source_action="update",
                related_url="/contacts/",
                published_at=timezone.now(),
            )
except ImportError:
    pass
