from django.test import TestCase, Client
from django.urls import reverse
from articles.models import Article
from shop.models import Category, Product
from main.models import SiteSettings, FooterStatBanner


class CatalogPaginationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.cat = Category.objects.create(name="Тестовые сыры", slug="test-cheese", is_active=True)
        # Create 20 products
        for i in range(1, 21):
            Product.objects.create(
                category=self.cat,
                title=f"Продукт {i}",
                slug=f"product-{i}",
                price_display=f"{100 * i} ₽",
                price_numeric=100 * i,
                is_active=True,
                order=i,
            )

    def test_catalog_page_1(self):
        res = self.client.get(reverse("main:catalog"), HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["page_size"], 9)
        self.assertEqual(res.context["current_page"], 1)
        self.assertEqual(res.context["total_pages"], 3)  # 20 items / 9 = 3 pages
        self.assertEqual(res.context["start_product_idx"], 1)
        self.assertEqual(res.context["end_product_idx"], 9)
        html = res.content.decode("utf-8")
        self.assertIn("catalogPaginationNav", html)
        self.assertIn("9 товаров на страницу", html)
        self.assertIn("goToPage", html)
        self.assertIn("ITEMS_PER_PAGE = 9", html)

    def test_catalog_page_2(self):
        res = self.client.get(reverse("main:catalog") + "?page=2", HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["current_page"], 2)
        self.assertEqual(res.context["start_product_idx"], 10)
        self.assertEqual(res.context["end_product_idx"], 18)

    def test_catalog_page_3(self):
        res = self.client.get(reverse("main:catalog") + "?page=3", HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["current_page"], 3)
        self.assertEqual(res.context["start_product_idx"], 19)
        self.assertEqual(res.context["end_product_idx"], 20)

    def test_catalog_category_filtering(self):
        res_cat = self.client.get(reverse("main:catalog") + "?cat=test-cheese", HTTP_HOST="127.0.0.1")
        self.assertEqual(res_cat.status_code, 200)
        self.assertEqual(res_cat.context["selected_cat"], "test-cheese")

        res_category = self.client.get(reverse("main:catalog") + "?category=test-cheese", HTTP_HOST="127.0.0.1")
        self.assertEqual(res_category.status_code, 200)
        self.assertEqual(res_category.context["selected_cat"], "test-cheese")


class CoreSiteEndpointsTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_favicon_ico(self):
        res = self.client.get("/favicon.ico", HTTP_HOST="127.0.0.1")
        self.assertIn(res.status_code, [200, 302])

    def test_robots_txt(self):
        res = self.client.get("/robots.txt", HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 200)
        self.assertIn("User-agent", res.content.decode("utf-8"))

    def test_sitemap_xml(self):
        res = self.client.get("/sitemap.xml", HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 200)
        self.assertIn("urlset", res.content.decode("utf-8"))

    def test_google_verification_file(self):
        res = self.client.get("/google70ba8bfb8c55d9f9.html", HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.content.decode("utf-8").strip(),
            "google-site-verification: google70ba8bfb8c55d9f9.html",
        )

    def test_google_verification_nonexistent_returns_404(self):
        res = self.client.get("/googlenonexistent123456.html", HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 404)

    def test_yandex_verification_file(self):
        res = self.client.get("/yandex_2481be1b37f5b18c.html", HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 200)
        self.assertIn("2481be1b37f5b18c", res.content.decode("utf-8"))

    def test_yandex_verification_nonexistent_returns_404(self):
        res = self.client.get("/yandex_nonexistent123456.html", HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 404)


class FooterStatBannerTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_stat_banner_rendering_in_footer(self):
        # 1. Создаем активный баннер-информер с HTML кодом
        banner_code = FooterStatBanner.objects.create(
            name="Яндекс Метрика Информер",
            banner_type=FooterStatBanner.BANNER_TYPE_HTML,
            html_code='<a id="ym-informer" href="https://metrika.yandex.ru"><img src="https://informer.yandex.ru/informer" alt="Яндекс.Метрика" /></a>',
            order=1,
            is_active=True
        )

        # 2. Создаем активный графический баннер со ссылкой
        banner_img = FooterStatBanner.objects.create(
            name="LiveInternet",
            banner_type=FooterStatBanner.BANNER_TYPE_IMAGE,
            url="https://www.liveinternet.ru/click",
            alt_text="LiveInternet: число просмотров за 24 часа",
            order=2,
            is_active=True
        )

        # 3. Создаем неактивный баннер (не должен отображаться)
        banner_hidden = FooterStatBanner.objects.create(
            name="Скрытый баннер",
            banner_type=FooterStatBanner.BANNER_TYPE_HTML,
            html_code='<span id="hidden-counter">Hidden</span>',
            order=3,
            is_active=False
        )

        # Запрашиваем страницу сайта
        res = self.client.get(reverse("main:index"), HTTP_HOST="127.0.0.1")
        self.assertEqual(res.status_code, 200)
        
        # Проверяем, что контекст-процессор передал список баннеров
        banners_in_context = res.context["footer_stat_banners"]
        self.assertEqual(len(banners_in_context), 2)
        self.assertIn(banner_code, banners_in_context)
        self.assertIn(banner_img, banners_in_context)
        self.assertNotIn(banner_hidden, banners_in_context)

        # Проверяем HTML-вывод в подвале
        content = res.content.decode("utf-8")
        self.assertIn('ym-informer', content)
        self.assertIn('https://www.liveinternet.ru/click', content)
        self.assertIn('LiveInternet: число просмотров за 24 часа', content)
        self.assertNotIn('hidden-counter', content)


class ArticlesPaginationTest(TestCase):
    def setUp(self):
        self.client = Client()
        for i in range(1, 21):
            Article.objects.create(
                title=f"Статья о сыре {i}" if i <= 11 else f"Материал производства {i}",
                slug=f"article-test-{i}",
                snippet=f"Краткое описание {i}",
                content=f"<p>Содержимое {i}</p>",
                is_published=True,
                order=i,
            )

    def test_articles_pagination_9_per_page(self):
        url = reverse("main:articles")

        res_p1 = self.client.get(url, HTTP_HOST="127.0.0.1")
        self.assertEqual(res_p1.status_code, 200)
        self.assertEqual(res_p1.context["total_count"], 20)
        self.assertEqual(len(res_p1.context["articles"]), 9)
        self.assertEqual(res_p1.context["page_obj"].number, 1)
        self.assertEqual(res_p1.context["page_obj"].paginator.num_pages, 3)
        html_p1 = res_p1.content.decode("utf-8")
        self.assertIn("9 статей на страницу", html_p1)
        self.assertIn("?page=2", html_p1)

        res_p2 = self.client.get(url, {"page": 2}, HTTP_HOST="127.0.0.1")
        self.assertEqual(res_p2.status_code, 200)
        self.assertEqual(len(res_p2.context["articles"]), 9)
        self.assertEqual(res_p2.context["page_obj"].number, 2)

        res_p3 = self.client.get(url, {"page": 3}, HTTP_HOST="127.0.0.1")
        self.assertEqual(res_p3.status_code, 200)
        self.assertEqual(len(res_p3.context["articles"]), 2)
        self.assertEqual(res_p3.context["page_obj"].number, 3)

        # Проверка сохранения поискового запроса в ссылках пагинации
        res_q = self.client.get(url, {"q": "сыре"}, HTTP_HOST="127.0.0.1")
        self.assertEqual(res_q.status_code, 200)
        self.assertEqual(res_q.context["total_count"], 11)
        self.assertEqual(len(res_q.context["articles"]), 9)
        self.assertIn("page=2", res_q.content.decode("utf-8"))
        self.assertIn("q=", res_q.content.decode("utf-8"))


class ImageUploadPathTest(TestCase):
    def test_build_image_upload_path_format(self):
        from datetime import datetime
        from django.utils import timezone
        from main.upload_paths import build_image_upload_path

        dt = timezone.make_aware(datetime(2026, 11, 27, 10, 30, 0))
        path = build_image_upload_path("products", "My Photo.PNG", now=dt)
        self.assertEqual(path, "products/2026/11/27/sibsir-ru_products_2026-11-27.png")

    def test_model_image_uploads_use_category_date_structure(self):
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from django.utils import timezone

        now = timezone.localtime(timezone.now())
        y, m, d = now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")
        date_str = now.strftime("%Y-%m-%d")

        tiny_gif = (
            b"GIF89a\x01\x00\x01\x00\x00\xff\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )

        with tempfile.TemporaryDirectory() as tmp_media:
            with override_settings(MEDIA_ROOT=tmp_media):
                cat = Category.objects.create(name="Сыры", slug="cheeses-upload-test")
                prod = Product.objects.create(
                    category=cat,
                    title="Тестовый сыр",
                    slug="test-cheese-upload",
                    price_display="500 ₽",
                    price_numeric=500,
                    image=SimpleUploadedFile("cheese.gif", tiny_gif, content_type="image/gif"),
                )
                expected_prefix = f"products/{y}/{m}/{d}/sibsir-ru_products_{date_str}"
                self.assertTrue(prod.image.name.startswith(expected_prefix), prod.image.name)
                self.assertTrue(prod.image.name.endswith(".gif"), prod.image.name)

                article = Article.objects.create(
                    title="Тестовая статья",
                    slug="test-article-upload",
                    snippet="Анонс",
                    content="<p>Текст</p>",
                    image=SimpleUploadedFile("cover.gif", tiny_gif, content_type="image/gif"),
                )
                expected_art_prefix = f"articles/{y}/{m}/{d}/sibsir-ru_articles_{date_str}"
                self.assertTrue(article.image.name.startswith(expected_art_prefix), article.image.name)

    def test_tinymce_image_upload_format_and_collision_handling(self):
        import json
        import tempfile
        from django.contrib.auth import get_user_model
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from django.utils import timezone

        now = timezone.localtime(timezone.now())
        y, m, d = now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")
        date_str = now.strftime("%Y-%m-%d")

        User = get_user_model()
        staff = User.objects.create_user(username="staff_uploader", password="pw", is_staff=True)
        self.client.force_login(staff)

        tiny_gif = (
            b"GIF89a\x01\x00\x01\x00\x00\xff\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )

        with tempfile.TemporaryDirectory() as tmp_media:
            with override_settings(MEDIA_ROOT=tmp_media):
                res1 = self.client.post(
                    reverse("tinymce_image_upload"),
                    {"file": SimpleUploadedFile("first.gif", tiny_gif, content_type="image/gif")},
                    HTTP_HOST="127.0.0.1",
                )
                self.assertEqual(res1.status_code, 200)
                loc1 = json.loads(res1.content)["location"]
                self.assertIn(f"/media/editor_uploads/{y}/{m}/{d}/sibsir-ru_editor_uploads_{date_str}.gif", loc1)

                res2 = self.client.post(
                    reverse("tinymce_image_upload"),
                    {"file": SimpleUploadedFile("second.gif", tiny_gif, content_type="image/gif")},
                    HTTP_HOST="127.0.0.1",
                )
                self.assertEqual(res2.status_code, 200)
                loc2 = json.loads(res2.content)["location"]
                self.assertNotEqual(loc1, loc2)
                self.assertIn(f"/media/editor_uploads/{y}/{m}/{d}/sibsir-ru_editor_uploads_{date_str}_", loc2)
                self.assertTrue(loc2.endswith(".gif"))

