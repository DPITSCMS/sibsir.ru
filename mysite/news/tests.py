import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from news.models import News
from news.forms import NewsForm, NewsAdminForm
from shop.models import Product, Category, Promotion
from articles.models import Article

User = get_user_model()


class NewsModuleTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_superuser(
            username="admin_test",
            email="admin@sibsir.test",
            password="testpassword123"
        )

    def test_news_date_helpers(self):
        """Проверка работы свойств группировки даты: день, месяц, год, русские названия."""
        dt = timezone.make_aware(datetime.datetime(2026, 11, 21, 14, 30))
        news = News.objects.create(
            title="Тестовая новость сыроварни",
            snippet="Краткий анонс",
            content="<p>Полный текст</p>",
            published_at=dt,
        )
        self.assertEqual(news.year, 2026)
        self.assertEqual(news.month, 11)
        self.assertEqual(news.day, 21)
        self.assertEqual(news.month_name_nominative, "Ноябрь")
        self.assertEqual(news.month_name_genitive, "ноября")
        self.assertEqual(news.formatted_time, "14:30")
        self.assertIn("21 ноября 2026", news.formatted_date)
        self.assertTrue(news.slug)

    def test_news_list_view_and_date_grouping(self):
        """Проверка отображения новостей с группировкой по Году, Месяцу и Дню."""
        dt1 = timezone.make_aware(datetime.datetime(2026, 11, 21, 10, 0))
        dt2 = timezone.make_aware(datetime.datetime(2026, 11, 21, 16, 0))
        dt3 = timezone.make_aware(datetime.datetime(2026, 10, 15, 12, 0))
        dt4 = timezone.make_aware(datetime.datetime(2025, 5, 1, 9, 0))

        News.objects.create(title="Новость 21 ноября утро", published_at=dt1)
        News.objects.create(title="Новость 21 ноября вечер", published_at=dt2)
        News.objects.create(title="Новость 15 октября", published_at=dt3)
        News.objects.create(title="Новость мая 2025", published_at=dt4)

        url = reverse("news:news_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Проверяем наличие группировки по годам в контексте
        grouped_years = response.context["grouped_years"]
        years = [g["year"] for g in grouped_years]
        self.assertIn(2026, years)
        self.assertIn(2025, years)

        # Фильтрация по году
        res_2026 = self.client.get(url, {"year": "2026"})
        self.assertEqual(res_2026.status_code, 200)
        self.assertEqual(len(res_2026.context["news_list"]), 3)

        # Фильтрация по дате (день)
        res_date = self.client.get(url, {"date": "2026-11-21"})
        self.assertEqual(res_date.status_code, 200)
        self.assertEqual(len(res_date.context["news_list"]), 2)

    def test_news_detail_view(self):
        """Проверка детальной страницы новости."""
        news = News.objects.create(
            title="Открытие новой линии производства",
            content="<p>Текст о новой линии</p>",
        )
        url = reverse("news:news_detail", kwargs={"slug": news.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, news.title)

        # Проверяем, что просмотры инкрементируются
        news.refresh_from_db()
        self.assertEqual(news.views_count, 1)

    def test_widget_and_forms(self):
        """Проверка работы формы и виджета даты."""
        form = NewsForm(data={
            "title": "Новость через форму",
            "published_at": "2026-11-21T15:45",
            "content": "<p>Контент</p>",
            "news_type": "general",
            "is_published": True,
        })
        self.assertTrue(form.is_valid(), form.errors)
        instance = form.save()
        self.assertEqual(instance.published_at.year, 2026)
        self.assertEqual(instance.published_at.month, 11)
        self.assertEqual(instance.published_at.day, 21)

        # Проверяем admin форму
        admin_form = NewsAdminForm(instance=instance)
        rendered = admin_form.as_p()
        self.assertIn("modern-datetime-picker-wrapper", rendered)
        self.assertIn("applyDateTimePreset", rendered)

    def test_product_change_creates_news(self):
        """Проверка: добавление и редактирование товара создает новость."""
        initial_news_count = News.objects.count()

        # Создание товара
        product = Product.objects.create(
            title="Сыр Сулугуни Экстра",
            price_display="450 ₽",
        )
        # Должна появиться новость о новинке
        self.assertEqual(News.objects.count(), initial_news_count + 1)
        news_item = News.objects.latest("id")
        self.assertIn("Сыр Сулугуни Экстра", news_item.title)
        self.assertEqual(news_item.news_type, "product")
        self.assertTrue(news_item.is_auto_generated)

        # Редактирование товара
        product.title = "Сыр Сулугуни Экстра Копченый"
        product.save()

        # Должна появиться новость об обновлении товара
        self.assertEqual(News.objects.count(), initial_news_count + 2)
        news_update = News.objects.latest("id")
        self.assertIn("Обновлен товар", news_update.title)
        self.assertIn("Сыр Сулугуни Экстра Копченый", news_update.title)

    def test_news_editing_creates_news_about_edit(self):
        """
        Проверка ключевого требования ТЗ:
        "редактирование новости так же будет добавлять об этом новость"
        И защита от бесконечной рекурсии!
        """
        # Создаем новость вручную
        original_news = News.objects.create(
            title="График работы сыроварни в праздники",
            content="<p>Информация о праздничных днях</p>",
            is_auto_generated=False,
        )
        count_after_create = News.objects.count()

        # Редактируем новость
        original_news.title = "Обновленный график работы сыроварни в праздники"
        original_news.content = "<p>Уточненный график работы</p>"
        original_news.save()

        # Должна добавиться новость о редактировании новости
        self.assertEqual(News.objects.count(), count_after_create + 1)
        edit_notification = News.objects.latest("id")
        self.assertIn("Отредактирована новость", edit_notification.title)
        self.assertEqual(edit_notification.news_type, "edit")
        self.assertTrue(edit_notification.is_auto_generated)
        self.assertEqual(edit_notification.source_model, "News")
        self.assertEqual(edit_notification.source_action, "update")

    def test_news_pagination_9_per_page(self):
        """Проверка постраничной навигации новостей по 9 на страницу с сохранением фильтров."""
        base_dt = timezone.make_aware(datetime.datetime(2026, 11, 1, 12, 0))
        for i in range(1, 21):
            News.objects.create(
                title=f"Новость пагинации {i}",
                snippet=f"Анонс {i}",
                content=f"<p>Текст {i}</p>",
                news_type="promo" if i <= 11 else "general",
                published_at=base_dt + datetime.timedelta(hours=i),
            )

        url = reverse("news:news_list")

        res_p1 = self.client.get(url)
        self.assertEqual(res_p1.status_code, 200)
        self.assertEqual(res_p1.context["total_count"], 20)
        self.assertEqual(len(res_p1.context["news_list"]), 9)
        self.assertEqual(res_p1.context["page_obj"].number, 1)
        self.assertEqual(res_p1.context["page_obj"].paginator.num_pages, 3)
        html_p1 = res_p1.content.decode("utf-8")
        self.assertIn("9 новостей на страницу", html_p1)
        self.assertIn("?page=2", html_p1)

        res_p2 = self.client.get(url, {"page": 2})
        self.assertEqual(res_p2.status_code, 200)
        self.assertEqual(len(res_p2.context["news_list"]), 9)
        self.assertEqual(res_p2.context["page_obj"].number, 2)

        res_p3 = self.client.get(url, {"page": 3})
        self.assertEqual(res_p3.status_code, 200)
        self.assertEqual(len(res_p3.context["news_list"]), 2)
        self.assertEqual(res_p3.context["page_obj"].number, 3)

        # Проверка сохранения фильтра type=promo в ссылках пагинации
        res_filtered = self.client.get(url, {"type": "promo"})
        self.assertEqual(res_filtered.status_code, 200)
        self.assertEqual(res_filtered.context["total_count"], 11)
        self.assertEqual(len(res_filtered.context["news_list"]), 9)
        self.assertIn("type=promo&page=2", res_filtered.content.decode("utf-8"))
