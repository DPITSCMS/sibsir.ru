from decimal import Decimal
import json
import zipfile
import io

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from shop.models import Category, Product, Promotion, PromoCode, Order, OrderItem, Review
from shop.utils import amount_in_words, count_items_in_words, plural_form
from shop.price_list_generator import generate_wholesale_price_list_xlsx
from main.models import SiteSettings

User = get_user_model()


class ShopUtilsTest(TestCase):
    def test_plural_form(self):
        forms = ("рубль", "рубля", "рублей")
        self.assertEqual(plural_form(1, forms), "рубль")
        self.assertEqual(plural_form(2, forms), "рубля")
        self.assertEqual(plural_form(5, forms), "рублей")
        self.assertEqual(plural_form(11, forms), "рублей")
        self.assertEqual(plural_form(21, forms), "рубль")
        self.assertEqual(plural_form(24, forms), "рубля")

    def test_amount_in_words(self):
        res = amount_in_words(1540.50)
        self.assertIn("Одна тысяча пятьсот сорок рублей", res)
        self.assertIn("50 копеек", res)

        zero = amount_in_words(0)
        self.assertIn("Ноль рублей 00 копеек", zero)

    def test_count_items_in_words(self):
        self.assertEqual(count_items_in_words(1), "один")
        self.assertEqual(count_items_in_words(3), "три")
        self.assertEqual(count_items_in_words(12), "двенадцать")


class CategoryModelTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(
            name="Полутвердые сыры",
            slug="polutverdye-syry",
            description="Натуральные полутвердые сыры из коровьего молока.",
            order=1,
            is_active=True,
        )

    def test_str_and_urls(self):
        self.assertEqual(str(self.category), "Полутвердые сыры")
        self.assertEqual(self.category.get_absolute_url(), "/catalog/?cat=polutverdye-syry")
        self.assertIn("/catalog/?cat=polutverdye-syry", self.category.get_canonical_url())

    def test_seo_generation(self):
        self.category.generate_seo(overwrite=True)
        self.assertIn("Полутвердые сыры", self.category.get_meta_title())
        self.assertIn("ТМ «Сибсыр»", self.category.get_meta_title())
        self.assertTrue(len(self.category.get_meta_description()) > 0)
        self.assertTrue(len(self.category.get_meta_keywords()) > 0)


class ProductModelTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(
            name="Рассольные сыры",
            slug="rassolnye-syry",
            order=1
        )
        self.product = Product.objects.create(
            category=self.category,
            title="Сыр Сулугуни",
            slug="suluguni",
            price_display="450 ₽",
            price_numeric=450,
            wholesale_price_display="380 ₽",
            wholesale_price_numeric=380,
            wholesale_min_qty="от 5 кг",
            fat_content="45%",
            unit_weight="0.5 кг",
            shelf_life="60 суток",
            is_active=True,
        )

    def test_str_and_url(self):
        self.assertIn("Сыр Сулугуни", str(self.product))
        self.assertEqual(self.product.get_absolute_url(), reverse("main:product_detail", kwargs={"slug": "suluguni"}))

    def test_effective_pricing_without_discount(self):
        self.assertEqual(self.product.effective_price_numeric, 450)
        self.assertEqual(self.product.effective_price_display, "450 ₽")
        self.assertEqual(self.product.effective_wholesale_price_display, "380 ₽")
        self.assertFalse(self.product.has_discount)

    def test_effective_pricing_with_direct_discount(self):
        self.product.discount_percent = 10
        self.product.save()
        self.assertTrue(self.product.has_discount)
        self.assertEqual(self.product.effective_price_numeric, 405)
        self.assertEqual(self.product.effective_badge, "-10%")

    def test_price_sync_in_save(self):
        self.product.price_display = "520 ₽"
        self.product.save()
        self.product.refresh_from_db()
        self.assertEqual(self.product.price_numeric, 520)


class PromotionModelTest(TestCase):
    def setUp(self):
        self.promo = Promotion.objects.create(
            title="Весенняя скидка",
            slug="vesna-promo",
            badge_text="-15%",
            discount_percent=15,
            applies_to="all",
            is_active=True,
        )

    def test_is_currently_active(self):
        self.assertTrue(self.promo.is_currently_active())
        promo_map = Promotion.get_active_promotions_map()
        self.assertEqual(promo_map["all"].id, self.promo.id)


class PromoCodeModelTest(TestCase):
    def setUp(self):
        self.promocode = PromoCode.objects.create(
            code="welcome10",
            title="Скидка 10% новичкам",
            discount_type="percent",
            discount_value=Decimal("10.00"),
            min_order_amount=Decimal("500.00"),
            applies_to="all",
            is_active=True,
        )

    def test_clean_and_uppercase(self):
        self.assertEqual(self.promocode.code, "WELCOME10")
        self.assertTrue(self.promocode.is_currently_active())

    def test_calculate_discount_valid(self):
        cart_items = [
            {"title": "Сыр Российский", "numPrice": 300, "count": 2}
        ]
        res = self.promocode.calculate_discount_for_cart(cart_items)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["discount_amount"], Decimal("60.00"))
        self.assertEqual(res["subtotal"], Decimal("600.00"))
        self.assertEqual(res["total"], Decimal("540.00"))

    def test_calculate_discount_below_min_order(self):
        cart_items = [
            {"title": "Сыр Российский", "numPrice": 200, "count": 1}
        ]
        res = self.promocode.calculate_discount_for_cart(cart_items)
        self.assertFalse(res["is_valid"])
        self.assertIn("Минимальная сумма заказа", res["error"])


class OrderModelTest(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            customer_type="individual",
            name="Иван Петров",
            phone="+7 (999) 111-22-33",
            subtotal_price=Decimal("1000.00"),
            discount_amount=Decimal("100.00"),
            total_price=Decimal("900.00"),
            product_choice="Сыр Российский x 2 шт.",
        )
        self.item = OrderItem.objects.create(
            order=self.order,
            title="Сыр Российский",
            unit="шт.",
            quantity=2,
            price=Decimal("500.00")
        )

    def test_order_properties_and_methods(self):
        self.assertTrue(len(self.order.order_token) > 0)
        self.assertEqual(self.order.clean_phone, "+79991112233")
        self.assertIn("1 000.00 ₽", self.order.formatted_subtotal_price)
        self.assertIn("900.00 ₽", self.order.formatted_total_price)
        self.assertEqual(self.order.get_items_count(), 1)
        self.assertEqual(self.order.get_items_count_in_words(), "один")
        self.assertIn("Девятьсот рублей", self.order.get_total_in_words())

    def test_order_item_total(self):
        self.assertEqual(self.item.total, Decimal("1000.00"))


class ReviewModelTest(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            title="Сыр Гауда",
            slug="gauda",
            price_display="500 ₽",
            price_numeric=500,
            rating=Decimal("5.0"),
            reviews_count=0
        )
        self.review = Review.objects.create(
            product=self.product,
            author_name="Анна",
            city="Омск",
            rating=5,
            text="Отличный сыр, свежий и вкусный!",
            is_approved=True
        )

    def test_review_str_and_stars(self):
        self.assertIn("Анна", str(self.review))
        self.assertEqual(self.review.get_rating_stars(), "★★★★★")

    def test_product_rating_signal(self):
        self.product.refresh_from_db()
        self.assertEqual(self.product.reviews_count, 1)
        self.assertEqual(self.product.rating, Decimal("5.0"))


class ShopViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testclient", password="password123")
        self.staff_user = User.objects.create_superuser(username="adminuser", password="password123")
        self.order = Order.objects.create(
            user=self.user,
            customer_type="individual",
            name="Иван",
            phone="+79990001122",
            subtotal_price=Decimal("500.00"),
            total_price=Decimal("500.00"),
        )
        self.promocode = PromoCode.objects.create(
            code="SALE20",
            title="Скидка 20%",
            discount_type="percent",
            discount_value=Decimal("20.00"),
            is_active=True
        )

    def test_document_by_token(self):
        for doc in ["receipt", "waybill", "torg12", "bill"]:
            url = reverse("shop:order_token_doc", kwargs={"token": self.order.order_token, "doc_type": doc})
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)

    def test_document_by_id_permissions(self):
        receipt_url = reverse("shop:order_receipt", kwargs={"order_id": self.order.id})
        
        # Unauthorized without token -> 403 Forbidden
        resp = self.client.get(receipt_url)
        self.assertEqual(resp.status_code, 403)

        # Access with token -> 200 OK
        resp = self.client.get(f"{receipt_url}?token={self.order.order_token}")
        self.assertEqual(resp.status_code, 200)

        # Access by staff user -> 200 OK
        self.client.force_login(self.staff_user)
        resp = self.client.get(receipt_url)
        self.assertEqual(resp.status_code, 200)

    def test_apply_promocode_api(self):
        url = reverse("shop:apply_promocode_api")
        payload = {
            "code": "SALE20",
            "items": [{"title": "Сыр", "numPrice": 500, "count": 1}]
        }
        resp = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["discount_amount"], 100.0)


class PriceListGeneratorTest(TestCase):
    def test_generate_price_list_xlsx(self):
        content, filename = generate_wholesale_price_list_xlsx()
        self.assertTrue(len(content) > 0)
        self.assertTrue(filename.endswith(".xlsx"))
        
        # Verify valid zip package
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("xl/workbook.xml", names)
            self.assertIn("xl/styles.xml", names)
            self.assertIn("xl/worksheets/sheet1.xml", names)
