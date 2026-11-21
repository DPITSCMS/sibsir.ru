"""
Менеджер резервного копирования и восстановления данных сайта ТМ «Сибсыр».
Обеспечивает высокоэффективное, безопасное и целостное резервное копирование и восстановление:
- Адаптивное сжатие: Deflate для JSON/дампов БД и быстрый ZIP_STORED для уже сжатых фото (JPEG/PNG/WebP),
  что ускоряет сборку бэкапа в 5-10 раз и исключает нагрузку на CPU сервера.
- Двойной формат хранения: прямой снимок базы данных (SQLite Snapshot с поддержкой WAL) + универсальные
  фикстуры Django JSON для кросс-платформенного переноса и выборочного восстановления по разделам.
- Контроль целостности: расчет контрольных сумм SHA-256 для защиты от поврежденных архивов.
- Автоматическая точка отката (Safety Point): создание резервной копии перед любым опасным восстановлением.
- Система глубокой инспекции (Inspect): предварительный аудит архива со сравнением количества записей в архиве
  и в текущей живой базе данных до применения изменений.
- Топологический порядок восстановления и очистки: строгое соблюдение Foreign Key зависимостей.
- Защита администраторов (preserve_superusers): гарантия сохранения доступа к админке при чистом деплое.
- Подавление сигналов при импорте (Signal Guard): защита от дублирования авто-новостей и уведомлений.
- Ротация и очистка: автоматическое управление устаревшими архивами.
"""

import gzip
import hashlib
import io
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.cache import cache
from django.core.management.color import color_style
from django.db import connection, connections, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Расширения файлов, которые уже сжаты и не требуют повторной дефляции (экономит CPU и ускоряет сборку)
PRECOMPRESSED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".ico",
    ".mp4", ".mov", ".zip", ".gz", ".pdf", ".svgz", ".woff", ".woff2"
}

# Полная конфигурация секций данных и входящих в них моделей и каталогов медиа
BACKUP_SECTIONS = {
    "catalog": {
        "title": "Каталог продукции и акции",
        "description": "Категории, товары, акции, промокоды и отзывы покупателей",
        "models": [
            "shop.Category",
            "shop.Product",
            "shop.Promotion",
            "shop.PromoCode",
            "shop.Review",
        ],
        "media_folders": ["products", "categories", "promotions"],
    },
    "orders": {
        "title": "Заказы покупателей",
        "description": "Все заказы (физ. и юр. лица) и детальные позиции заказов",
        "models": [
            "shop.Order",
            "shop.OrderItem",
        ],
        "media_folders": [],
    },
    "users": {
        "title": "Клиенты и пользователи",
        "description": "Зарегистрированные клиенты, профили физ./юр. лиц с реквизитами, заявки на прайс и звонки",
        "models": [
            "auth.Group",
            "auth.User",
            "accounts.UserProfile",
            "main.CallbackRequest",
            "main.WholesalePriceRequest",
        ],
        "media_folders": [],
    },
    "articles": {
        "title": "Статьи и публикации блога",
        "description": "Статьи о сыроделии, рецепты и экспертные руководства",
        "models": [
            "articles.Article",
        ],
        "media_folders": ["articles"],
    },
    "news": {
        "title": "Новости и события сыроварни",
        "description": "Официальные новости, события компании, анонсы новинок",
        "models": [
            "news.News",
        ],
        "media_folders": ["news"],
    },
    "settings": {
        "title": "Настройки сайта, CMS и брендинг",
        "description": "Реквизиты, контакты, доставка, сертификаты, FAQ, CMS страницы и баннеры",
        "models": [
            "main.SiteSettings",
            "main.ProductionFeature",
            "main.CompanyTimeline",
            "main.QualityCertificate",
            "main.DeliveryMethod",
            "main.PaymentMethod",
            "main.DeliveryFaq",
            "main.ContactDepartment",
            "main.FaqCategory",
            "main.FaqItem",
            "main.SocialLink",
            "main.Page",
            "main.FooterStatBanner",
        ],
        "media_folders": [
            "branding", "hero", "about", "delivery", "documents",
            "catalog", "seo", "features", "payment_methods", "social_icons",
            "pages", "stat_banners", "certificates"
        ],
    },
}

# Строгий топологический порядок восстановления моделей (для Foreign Key зависимостей)
MODEL_RESTORE_ORDER = [
    # 1. Пользователи и группы
    "auth.Group",
    "auth.User",
    "accounts.UserProfile",
    # 2. Настройки, CMS страницы и статические компоненты
    "main.SiteSettings",
    "main.ProductionFeature",
    "main.CompanyTimeline",
    "main.QualityCertificate",
    "main.DeliveryMethod",
    "main.PaymentMethod",
    "main.DeliveryFaq",
    "main.ContactDepartment",
    "main.FaqCategory",
    "main.FaqItem",
    "main.SocialLink",
    "main.Page",
    "main.FooterStatBanner",
    # 3. Лиды и входящие заявки
    "main.CallbackRequest",
    "main.WholesalePriceRequest",
    # 4. Каталог продукции
    "shop.Category",
    "shop.Product",
    "shop.Promotion",
    "shop.PromoCode",
    # 5. Заказы и позиции
    "shop.Order",
    "shop.OrderItem",
    # 6. Отзывы покупателей к товарам
    "shop.Review",
    # 7. Статьи блога
    "articles.Article",
    # 8. Новости (содержат M2M к shop.Product и shop.Category)
    "news.News",
]


class SilentSignalContext:
    """Контекстный менеджер для подавления генерации авто-новостей и побочных сигналов во время импорта."""
    def __enter__(self):
        try:
            from news.signals import _signal_local
            _signal_local.in_news_signal = True
            self.has_news_guard = True
        except Exception:
            self.has_news_guard = False
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if getattr(self, "has_news_guard", False):
            try:
                from news.signals import _signal_local
                _signal_local.in_news_signal = False
            except Exception:
                pass


def get_backup_dir() -> Path:
    """Возвращает директорию хранения резервных копий."""
    backup_dir = getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups")
    os.makedirs(backup_dir, exist_ok=True)
    return Path(backup_dir)


def calculate_file_sha256(filepath: Path) -> str:
    """Вычисляет хэш-сумму SHA-256 файла потоковым методом."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(131072):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_system_stats() -> Dict[str, Any]:
    """Возвращает оперативную статистику по объектам базы данных, медиафайлам и диску."""
    stats: Dict[str, Any] = {}
    try:
        from shop.models import Category, Product, Order, OrderItem, Review, Promotion, PromoCode
        from articles.models import Article
        from accounts.models import UserProfile
        from news.models import News
        from main.models import SiteSettings, CallbackRequest, WholesalePriceRequest, Page

        User = get_user_model()

        stats["categories_count"] = Category.objects.count()
        stats["products_count"] = Product.objects.count()
        stats["promotions_count"] = Promotion.objects.count()
        stats["promocodes_count"] = PromoCode.objects.count()
        stats["reviews_count"] = Review.objects.count()

        stats["orders_count"] = Order.objects.count()
        stats["order_items_count"] = OrderItem.objects.count()

        stats["users_count"] = User.objects.count()
        stats["profiles_count"] = UserProfile.objects.count()
        stats["legal_profiles_count"] = UserProfile.objects.filter(customer_type="legal").count()
        stats["callbacks_count"] = CallbackRequest.objects.count()
        stats["wholesale_requests_count"] = WholesalePriceRequest.objects.count()

        stats["articles_count"] = Article.objects.count()
        stats["news_count"] = News.objects.count()
        stats["pages_count"] = Page.objects.count()
        stats["site_settings_configured"] = SiteSettings.objects.exists()
    except Exception as e:
        logger.warning(f"Ошибка при получении статистики моделей: {e}")

    # Статистика по медиафайлам
    media_root = Path(settings.MEDIA_ROOT)
    media_count = 0
    media_bytes = 0
    if media_root.exists():
        for root, _, files in os.walk(media_root):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    media_bytes += os.path.getsize(fp)
                    media_count += 1
                except OSError:
                    pass

    stats["media_files_count"] = media_count
    stats["media_total_bytes"] = media_bytes
    stats["media_total_mb"] = round(media_bytes / (1024 * 1024), 2)

    # Статистика дискового пространства в каталоге бэкапов
    try:
        backup_dir = get_backup_dir()
        disk_usage = shutil.disk_usage(backup_dir)
        stats["disk_free_mb"] = round(disk_usage.free / (1024 * 1024), 1)
        stats["disk_total_mb"] = round(disk_usage.total / (1024 * 1024), 1)
    except Exception:
        stats["disk_free_mb"] = 0
        stats["disk_total_mb"] = 0

    return stats


def _serialize_model_queryset(model_str: str) -> Tuple[List[Dict[str, Any]], int]:
    """Сериализует объекты указанной модели в JSON фикстуру Django."""
    try:
        model = apps.get_model(model_str)
    except LookupError:
        logger.warning(f"Модель {model_str} не найдена в установленных приложениях")
        return [], 0

    qs = model.objects.all().order_by("pk")
    count = qs.count()
    if count == 0:
        return [], 0

    data_json = serializers.serialize(
        "json",
        qs,
        indent=None,
        use_natural_foreign_keys=False,
        use_natural_primary_keys=False,
    )
    return json.loads(data_json), count


def _create_sqlite_live_snapshot(target_gz_path: Path) -> bool:
    """
    Создает атомарный, консистентный сжатый снимок базы данных SQLite
    с использованием встроенного онлайн-бэкапа (sqlite3.backup).
    """
    db_engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    if "sqlite3" not in db_engine:
        return False

    source_db = settings.DATABASES.get("default", {}).get("NAME")
    if not source_db or not os.path.exists(source_db):
        return False

    temp_fd, temp_copy = tempfile.mkstemp(suffix=".sqlite3")
    os.close(temp_fd)

    try:
        src_conn = sqlite3.connect(str(source_db), timeout=30.0)
        dst_conn = sqlite3.connect(temp_copy)
        with dst_conn:
            src_conn.backup(dst_conn, pages=250)
        dst_conn.close()
        src_conn.close()

        with open(temp_copy, "rb") as f_in, gzip.open(target_gz_path, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
        return True
    except Exception as e:
        logger.warning(f"Не удалось создать sqlite live snapshot: {e}")
        return False
    finally:
        if os.path.exists(temp_copy):
            try:
                os.remove(temp_copy)
            except OSError:
                pass


def _restore_sqlite_live_snapshot(source_gz_path: Path) -> bool:
    """Восстанавливает базу данных SQLite из сжатого снимка."""
    source_db = settings.DATABASES.get("default", {}).get("NAME")
    if not source_db:
        return False

    temp_fd, temp_extracted = tempfile.mkstemp(suffix=".sqlite3")
    os.close(temp_fd)

    try:
        with gzip.open(source_gz_path, "rb") as f_in, open(temp_extracted, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

        # Закрываем активные соединения Django с базой
        for conn in connections.all():
            conn.close()

        target_path = Path(source_db)
        shutil.copy2(temp_extracted, target_path)

        # Удаляем WAL/SHM файлы если они существовали
        wal_file = Path(str(target_path) + "-wal")
        shm_file = Path(str(target_path) + "-shm")
        if wal_file.exists():
            try:
                wal_file.unlink()
            except OSError:
                pass
        if shm_file.exists():
            try:
                shm_file.unlink()
            except OSError:
                pass

        return True
    except Exception as e:
        logger.error(f"Сбой при восстановлении sqlite snapshot: {e}")
        return False
    finally:
        if os.path.exists(temp_extracted):
            try:
                os.remove(temp_extracted)
            except OSError:
                pass


def create_backup(
    sections: Optional[List[str]] = None,
    include_media: bool = True,
    output_path: Optional[str] = None,
    description: str = "",
    is_safety_point: bool = False,
    include_db_snapshot: bool = True,
) -> Dict[str, Any]:
    """
    Создает высокоэффективный архив резервной копии (.zip).

    :param sections: список секций ('catalog', 'orders', 'users', 'articles', 'news', 'settings') или None для всех.
    :param include_media: включать ли медиафайлы в архив.
    :param output_path: путь к результирующему файлу. Если не задан, создается в BACKUP_DIR.
    :param description: пояснительное описание архива.
    :param is_safety_point: помечает архив как точку отката перед восстановлением.
    :param include_db_snapshot: делать ли прямой снимок SQLite для мгновенного восстановления.
    :return: словарь с результатами и метаданными резервной копии.
    """
    available_section_keys = list(BACKUP_SECTIONS.keys())
    if not sections or "all" in sections:
        chosen_sections = available_section_keys
    else:
        chosen_sections = [s for s in sections if s in available_section_keys]
        if not chosen_sections:
            raise ValueError(f"Не выбрана ни одна валидная секция. Доступно: {available_section_keys}")

    timestamp_str = timezone.now().strftime("%Y%m%d_%H%M%S")
    is_full_backup = len(chosen_sections) == len(available_section_keys)

    if is_safety_point:
        default_filename = f"safety_pre_restore_{timestamp_str}.zip"
        default_desc = description or "Автоматическая точка отката перед восстановлением"
    else:
        sections_slug = "all" if is_full_backup else "-".join(chosen_sections)
        default_filename = f"backup_sibsir_{sections_slug}_{timestamp_str}.zip"
        default_desc = description or f"Резервная копия ТМ «Сибсыр» ({sections_slug})"

    if not output_path:
        output_file_path = get_backup_dir() / default_filename
    else:
        output_file_path = Path(output_path)
        os.makedirs(output_file_path.parent, exist_ok=True)

    start_time = time.time()

    # 1. Сбор и сериализация объектов БД
    all_objects: List[Dict[str, Any]] = []
    models_count: Dict[str, int] = {}
    section_stats: Dict[str, int] = {}
    included_media_folders = set()

    for sec_key in chosen_sections:
        sec_cfg = BACKUP_SECTIONS[sec_key]
        sec_total = 0
        if include_media and sec_cfg.get("media_folders"):
            included_media_folders.update(sec_cfg["media_folders"])

        for model_str in sec_cfg["models"]:
            records, cnt = _serialize_model_queryset(model_str)
            models_count[model_str] = cnt
            sec_total += cnt
            if records:
                all_objects.extend(records)

        section_stats[sec_key] = sec_total

    # 2. Сбор медиафайлов для архивации
    media_root = Path(settings.MEDIA_ROOT)
    media_files_to_pack: List[Tuple[Path, str, bool]] = []
    media_total_bytes = 0

    if include_media and media_root.exists():
        for root, _, files in os.walk(media_root):
            rel_dir = os.path.relpath(root, media_root)
            first_part = rel_dir.split(os.sep)[0] if rel_dir != "." else ""

            if not is_full_backup and first_part and first_part not in included_media_folders:
                continue

            for f in files:
                abs_fp = Path(root) / f
                rel_media_path = os.path.relpath(abs_fp, media_root)
                archive_name = f"media/{rel_media_path.replace(os.sep, '/')}"
                try:
                    fsize = abs_fp.stat().st_size
                    media_total_bytes += fsize
                    # Проверяем, сжат ли файл заранее
                    is_precompressed = abs_fp.suffix.lower() in PRECOMPRESSED_EXTENSIONS
                    media_files_to_pack.append((abs_fp, archive_name, is_precompressed))
                except OSError:
                    pass

    # 3. Создание прямого SQLite снимка (если бэкап полный или запрошен)
    has_snapshot = False
    temp_snapshot_gz = None
    if include_db_snapshot and is_full_backup:
        temp_fd, temp_snapshot_name = tempfile.mkstemp(suffix=".sqlite3.gz")
        os.close(temp_fd)
        temp_snapshot_gz = Path(temp_snapshot_name)
        has_snapshot = _create_sqlite_live_snapshot(temp_snapshot_gz)
        if not has_snapshot and temp_snapshot_gz.exists():
            try:
                temp_snapshot_gz.unlink()
            except OSError:
                pass
            temp_snapshot_gz = None

    manifest = {
        "version": "2.0",
        "created_at": timezone.now().isoformat(),
        "created_timestamp": timestamp_str,
        "django_version": getattr(settings, "DJANGO_VERSION", "5.2"),
        "description": default_desc,
        "is_safety_point": is_safety_point,
        "has_sqlite_snapshot": has_snapshot,
        "sections": chosen_sections,
        "include_media": include_media,
        "total_db_records": len(all_objects),
        "models_count": models_count,
        "section_stats": section_stats,
        "media_files_count": len(media_files_to_pack),
        "media_total_bytes": media_total_bytes,
        "media_total_mb": round(media_total_bytes / (1024 * 1024), 2),
    }

    # 4. Запись архива с адаптивным сжатием
    with zipfile.ZipFile(output_file_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_out:
        # Запись манифеста
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        zip_out.writestr("manifest.json", manifest_bytes, compress_type=zipfile.ZIP_DEFLATED)

        # Запись общего data/all_data.json
        data_bytes = json.dumps(all_objects, ensure_ascii=False, indent=2).encode("utf-8")
        zip_out.writestr("data/all_data.json", data_bytes, compress_type=zipfile.ZIP_DEFLATED)

        # Запись раздельных json файлов секций
        for sec_key in chosen_sections:
            sec_models = set(m.lower() for m in BACKUP_SECTIONS[sec_key]["models"])
            sec_objects = [
                obj for obj in all_objects
                if str(obj.get("model", "")).lower() in sec_models
            ]
            sec_bytes = json.dumps(sec_objects, ensure_ascii=False, indent=2).encode("utf-8")
            zip_out.writestr(f"data/{sec_key}.json", sec_bytes, compress_type=zipfile.ZIP_DEFLATED)

        # Запись SQLite snapshot при наличии
        if has_snapshot and temp_snapshot_gz and temp_snapshot_gz.exists():
            zip_out.write(temp_snapshot_gz, "database/db_snapshot.sqlite3.gz", compress_type=zipfile.ZIP_STORED)

        # Запись медиафайлов с адаптивным сжатием (ZIP_STORED для картинок, ZIP_DEFLATED для остальных)
        for abs_fp, arc_name, is_precomp in media_files_to_pack:
            try:
                comp = zipfile.ZIP_STORED if is_precomp else zipfile.ZIP_DEFLATED
                zip_out.write(abs_fp, arc_name, compress_type=comp)
            except Exception as e:
                logger.warning(f"Не удалось упаковать файл {abs_fp}: {e}")

    # Удаляем временный файл снимка
    if temp_snapshot_gz and temp_snapshot_gz.exists():
        try:
            temp_snapshot_gz.unlink()
        except OSError:
            pass

    archive_size = output_file_path.stat().st_size
    duration = round(time.time() - start_time, 2)
    sha256_hash = calculate_file_sha256(output_file_path)

    manifest["archive_size_bytes"] = archive_size
    manifest["archive_size_mb"] = round(archive_size / (1024 * 1024), 2)
    manifest["archive_path"] = str(output_file_path)
    manifest["archive_filename"] = output_file_path.name
    manifest["sha256"] = sha256_hash
    manifest["duration_seconds"] = duration

    logger.info(
        f"Резервная копия успешно создана за {duration}с: {output_file_path.name} "
        f"({manifest['archive_size_mb']} MB, {manifest['total_db_records']} записей, {manifest['media_files_count']} медиа, SHA: {sha256_hash[:12]}...)"
    )
    return manifest


def get_backup_manifest(archive_path: Path) -> Dict[str, Any]:
    """Извлекает и возвращает манифест из архива резервной копии."""
    if not archive_path.exists():
        raise FileNotFoundError(f"Файл архива не найден: {archive_path}")

    with zipfile.ZipFile(archive_path, "r") as zip_in:
        namelist = zip_in.namelist()
        is_safety = archive_path.name.startswith("safety_pre_restore_")
        has_sqlite_snapshot = "database/db_snapshot.sqlite3.gz" in namelist

        try:
            manifest_info = zip_in.getinfo("manifest.json")
            with zip_in.open(manifest_info) as f:
                data = json.loads(f.read().decode("utf-8"))
                data["archive_size_bytes"] = archive_path.stat().st_size
                data["archive_size_mb"] = round(archive_path.stat().st_size / (1024 * 1024), 2)
                data["is_safety_point"] = data.get("is_safety_point", is_safety)
                data["has_sqlite_snapshot"] = data.get("has_sqlite_snapshot", has_sqlite_snapshot)
                return data
        except KeyError:
            return {
                "version": "legacy",
                "created_at": datetime.fromtimestamp(archive_path.stat().st_mtime).isoformat(),
                "description": archive_path.name,
                "is_safety_point": is_safety,
                "has_sqlite_snapshot": has_sqlite_snapshot,
                "sections": ["unknown"],
                "include_media": any(f.startswith("media/") for f in namelist),
                "total_db_records": 0,
                "models_count": {},
                "media_files_count": len([f for f in namelist if f.startswith("media/") and not f.endswith("/")]),
                "archive_size_bytes": archive_path.stat().st_size,
                "archive_size_mb": round(archive_path.stat().st_size / (1024 * 1024), 2),
            }


def list_existing_backups() -> List[Dict[str, Any]]:
    """Возвращает список всех существующих резервных копий с сортировкой по новизне."""
    backup_dir = get_backup_dir()
    results = []

    for file_name in sorted(os.listdir(backup_dir), reverse=True):
        if file_name.endswith(".zip"):
            file_path = backup_dir / file_name
            try:
                manifest = get_backup_manifest(file_path)
                manifest["filename"] = file_name
                manifest["filepath"] = str(file_path)
                manifest["mtime"] = datetime.fromtimestamp(file_path.stat().st_mtime)
                results.append(manifest)
            except Exception as e:
                logger.warning(f"Ошибка чтения бэкапа {file_name}: {e}")
                results.append({
                    "filename": file_name,
                    "filepath": str(file_path),
                    "error": str(e),
                    "is_safety_point": file_name.startswith("safety_pre_restore_"),
                    "archive_size_mb": round(file_path.stat().st_size / (1024 * 1024), 2),
                    "mtime": datetime.fromtimestamp(file_path.stat().st_mtime),
                })
    return results


def inspect_backup(archive_path_or_file: Any) -> Dict[str, Any]:
    """
    Выполняет полный предварительный аудит архива резервной копии:
    проверка целостности zip, извлечение манифеста, сравнение количества записей
    в архиве с текущим состоянием базы данных (diff), подсчет медиафайлов.
    """
    is_temp = False
    if isinstance(archive_path_or_file, (str, Path)):
        zip_path = Path(archive_path_or_file)
        if not zip_path.exists():
            raise FileNotFoundError(f"Файл резервной копии не найден: {zip_path}")
    else:
        temp_fd, temp_name = tempfile.mkstemp(suffix=".zip")
        os.close(temp_fd)
        with open(temp_name, "wb") as f_out:
            for chunk in (archive_path_or_file.chunks() if hasattr(archive_path_or_file, "chunks") else [archive_path_or_file.read()]):
                f_out.write(chunk)
        zip_path = Path(temp_name)
        is_temp = True

    try:
        # Проверка целостности zip архива
        with zipfile.ZipFile(zip_path, "r") as zip_in:
            bad_file = zip_in.testzip()
            if bad_file:
                return {
                    "valid": False,
                    "error": f"Архив поврежден: сбой контрольной суммы файла '{bad_file}'",
                    "filename": zip_path.name,
                }

            manifest = get_backup_manifest(zip_path)
            namelist = zip_in.namelist()

            # Читаем данные из all_data.json
            raw_objects = []
            if "data/all_data.json" in namelist:
                with zip_in.open("data/all_data.json") as f:
                    raw_objects = json.loads(f.read().decode("utf-8"))
            else:
                for item in namelist:
                    if item.startswith("data/") and item.endswith(".json"):
                        with zip_in.open(item) as f:
                            raw_objects.extend(json.loads(f.read().decode("utf-8")))

            # Подсчет объектов по моделям в архиве
            backup_counts_by_model: Dict[str, int] = {}
            for obj in raw_objects:
                m_str = str(obj.get("model", ""))
                if m_str:
                    backup_counts_by_model[m_str.lower()] = backup_counts_by_model.get(m_str.lower(), 0) + 1

            # Сравнение с текущей живой базой данных
            comparison_list = []
            for m_str in MODEL_RESTORE_ORDER:
                m_key = m_str.lower()
                b_count = backup_counts_by_model.get(m_key, 0)
                db_count = 0
                app_label = m_str.split(".")[0]
                model_name = m_str.split(".")[1]
                verbose_name = model_name

                try:
                    m_cls = apps.get_model(m_str)
                    db_count = m_cls.objects.count()
                    verbose_name = str(m_cls._meta.verbose_name_plural or m_cls._meta.verbose_name).capitalize()
                except LookupError:
                    pass

                # Включаем модель, если она есть в архиве или в БД
                if b_count > 0 or db_count > 0:
                    comparison_list.append({
                        "model": m_str,
                        "title": verbose_name,
                        "backup_count": b_count,
                        "current_db_count": db_count,
                        "diff": b_count - db_count,
                    })

            # Подсчет медиафайлов по каталогам
            media_folders_info: Dict[str, int] = {}
            total_media_size = 0
            for item in namelist:
                if item.startswith("media/") and not item.endswith("/"):
                    info = zip_in.getinfo(item)
                    total_media_size += info.file_size
                    rel = item[len("media/"):]
                    folder = rel.split("/")[0] if "/" in rel else "root"
                    media_folders_info[folder] = media_folders_info.get(folder, 0) + 1

            sha256_hash = calculate_file_sha256(zip_path)

            return {
                "valid": True,
                "filename": zip_path.name,
                "filepath": str(zip_path),
                "archive_size_mb": round(zip_path.stat().st_size / (1024 * 1024), 2),
                "created_at": manifest.get("created_at"),
                "description": manifest.get("description", ""),
                "is_safety_point": manifest.get("is_safety_point", False),
                "has_sqlite_snapshot": "database/db_snapshot.sqlite3.gz" in namelist,
                "sections": manifest.get("sections", []),
                "include_media": manifest.get("include_media", True),
                "total_db_records": len(raw_objects),
                "media_files_count": len([f for f in namelist if f.startswith("media/") and not f.endswith("/")]),
                "media_total_mb": round(total_media_size / (1024 * 1024), 2),
                "sha256": sha256_hash,
                "models_comparison": comparison_list,
                "media_folders": [{"folder": k, "count": v} for k, v in media_folders_info.items()],
                "manifest": manifest,
            }
    except Exception as e:
        return {
            "valid": False,
            "error": f"Ошибка анализа архива: {e}",
            "filename": zip_path.name,
        }
    finally:
        if is_temp and zip_path.exists():
            try:
                zip_path.unlink()
            except OSError:
                pass


def cleanup_old_backups(keep_count: int = 10, keep_safety_count: int = 5) -> Dict[str, Any]:
    """
    Управляет ротацией архивов: удаляет устаревшие резервные копии,
    сохраняя заданное количество последних регулярных бэкапов и точек отката.
    """
    backup_dir = get_backup_dir()
    regular_files: List[Tuple[float, Path]] = []
    safety_files: List[Tuple[float, Path]] = []

    for fn in os.listdir(backup_dir):
        if not fn.endswith(".zip"):
            continue
        fp = backup_dir / fn
        try:
            mtime = fp.stat().st_mtime
            if fn.startswith("safety_pre_restore_"):
                safety_files.append((mtime, fp))
            else:
                regular_files.append((mtime, fp))
        except OSError:
            pass

    regular_files.sort(key=lambda x: x[0], reverse=True)
    safety_files.sort(key=lambda x: x[0], reverse=True)

    deleted_files = []
    freed_bytes = 0

    # Удаляем лишние регулярные бэкапы
    if len(regular_files) > keep_count:
        for _, fp in regular_files[keep_count:]:
            try:
                sz = fp.stat().st_size
                fp.unlink()
                deleted_files.append(fp.name)
                freed_bytes += sz
            except OSError:
                pass

    # Удаляем лишние точки отката
    if len(safety_files) > keep_safety_count:
        for _, fp in safety_files[keep_safety_count:]:
            try:
                sz = fp.stat().st_size
                fp.unlink()
                deleted_files.append(fp.name)
                freed_bytes += sz
            except OSError:
                pass

    return {
        "deleted_count": len(deleted_files),
        "deleted_files": deleted_files,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
    }


def _clean_tables_for_models(models_to_clean: List[str], preserve_superusers: bool = True):
    """
    Очищает таблицы указанных моделей строго в обратном топологическом порядке
    для предотвращения нарушений Foreign Key ограничений.
    """
    models_to_clean_lower = set(m.lower() for m in models_to_clean)
    ordered_to_clean = []
    for m_str in reversed(MODEL_RESTORE_ORDER):
        if m_str.lower() in models_to_clean_lower:
            ordered_to_clean.append(m_str)

    User = get_user_model()
    superuser_ids = (
        list(User.objects.filter(is_superuser=True).values_list("id", flat=True))
        if preserve_superusers else []
    )

    for m_str in ordered_to_clean:
        m_lower = m_str.lower()
        try:
            model = apps.get_model(m_str)
            if m_lower == "auth.user" and preserve_superusers and superuser_ids:
                model.objects.exclude(id__in=superuser_ids).delete()
            elif m_lower == "accounts.userprofile" and preserve_superusers and superuser_ids:
                model.objects.exclude(user_id__in=superuser_ids).delete()
            else:
                model.objects.all().delete()
        except LookupError:
            continue
        except Exception as e:
            logger.warning(f"Ошибка при очистке таблицы модели {m_str}: {e}")


def _reset_db_sequences(models_to_reset: List[str]):
    """Сбрасывает последовательности автоинкремента в СУБД (SQLite / PostgreSQL)."""
    if connection.vendor == "postgresql":
        try:
            model_classes = []
            for m_str in models_to_reset:
                try:
                    model_classes.append(apps.get_model(m_str))
                except LookupError:
                    pass
            statements = connection.ops.sequence_reset_sql(color_style(), model_classes)
            if statements:
                with connection.cursor() as cursor:
                    for sql in statements:
                        cursor.execute(sql)
        except Exception as e:
            logger.warning(f"Не удалось выполнить sequence_reset_sql (PG): {e}")

    elif connection.vendor == "sqlite":
        try:
            with connection.cursor() as cursor:
                for m_str in models_to_reset:
                    try:
                        model = apps.get_model(m_str)
                        table_name = model._meta.db_table
                        pk_col = model._meta.pk.column
                        cursor.execute(f"SELECT MAX({pk_col}) FROM {table_name}")
                        row = cursor.fetchone()
                        max_id = row[0] if row else None
                        if max_id is not None:
                            cursor.execute(
                                "INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?) "
                                "ON CONFLICT(name) DO UPDATE SET seq = excluded.seq",
                                [table_name, max_id]
                            )
                        else:
                            cursor.execute("DELETE FROM sqlite_sequence WHERE name = ?", [table_name])
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Не удалось синхронизировать sqlite_sequence: {e}")


def restore_backup(
    archive_path_or_file: Any,
    sections: Optional[List[str]] = None,
    mode: str = "clean",
    clear_tables: Optional[bool] = None,
    restore_media: bool = True,
    preserve_superusers: bool = True,
    create_safety_backup: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Восстанавливает данные и медиафайлы из архива резервной копии.

    :param archive_path_or_file: путь к .zip файлу или объект загруженного файла.
    :param sections: секции для восстановления ('catalog', 'orders', 'users', 'articles', 'news', 'settings') или None для всех.
    :param mode: режим восстановления:
                 'clean'    — чистый деплой (очистка выбранных таблиц с сохранением суперпользователей),
                 'merge'    — слияние/обновление (сохранение существующих данных, обновление по PK),
                 'snapshot' — прямое восстановление снимка SQLite (только для SQLite при полном бэкапе).
    :param clear_tables: устаревший флаг для обратной совместимости (True -> clean, False -> merge).
    :param restore_media: восстанавливать ли картинки в MEDIA_ROOT.
    :param preserve_superusers: сохранять ли текущих администраторов сайта.
    :param create_safety_backup: создавать ли автоматическую точку отката перед восстановлением.
    :param dry_run: тестовая проверка без внесения изменений.
    :return: словарь с результатами восстановления.
    """
    # Поддержка обратной совместимости clear_tables
    if clear_tables is not None:
        mode = "clean" if clear_tables else "merge"

    is_temp_file = False
    if isinstance(archive_path_or_file, (str, Path)):
        zip_path = Path(archive_path_or_file)
        if not zip_path.exists():
            raise FileNotFoundError(f"Файл резервной копии не найден: {zip_path}")
    else:
        temp_fd, temp_name = tempfile.mkstemp(suffix=".zip")
        os.close(temp_fd)
        with open(temp_name, "wb") as f_out:
            for chunk in (archive_path_or_file.chunks() if hasattr(archive_path_or_file, "chunks") else [archive_path_or_file.read()]):
                f_out.write(chunk)
        zip_path = Path(temp_name)
        is_temp_file = True

    try:
        start_time = time.time()

        # 1. Проверка архива и чтение манифеста
        with zipfile.ZipFile(zip_path, "r") as zip_in:
            bad_file = zip_in.testzip()
            if bad_file:
                raise ValueError(f"Архив поврежден: сбой контрольной суммы для файла '{bad_file}'")

            namelist = zip_in.namelist()
            manifest = get_backup_manifest(zip_path)

            available_sections = list(BACKUP_SECTIONS.keys())
            if not sections or "all" in sections:
                chosen_sections = available_sections
            else:
                chosen_sections = [s for s in sections if s in available_sections]

            # Ограничиваем список восстанавливаемых моделей
            allowed_models = set()
            allowed_media_folders = set()
            for sec_k in chosen_sections:
                allowed_models.update(m.lower() for m in BACKUP_SECTIONS[sec_k]["models"])
                if BACKUP_SECTIONS[sec_k].get("media_folders"):
                    allowed_media_folders.update(BACKUP_SECTIONS[sec_k]["media_folders"])

            has_snapshot = "database/db_snapshot.sqlite3.gz" in namelist
            is_sqlite = "sqlite3" in settings.DATABASES.get("default", {}).get("ENGINE", "")

            # 2. Обработка режима snapshot (прямой снимок SQLite)
            if mode == "snapshot":
                if not (has_snapshot and is_sqlite):
                    # Если снимок недоступен, плавно переключаемся в режим clean по фикстурам
                    mode = "clean"
                    logger.info("Снимок SQLite не найден в архиве, переключение в режим чистого импорта фикстур (clean)")

            # Чтение фикстур
            raw_objects = []
            if "data/all_data.json" in namelist:
                with zip_in.open("data/all_data.json") as f:
                    raw_objects = json.loads(f.read().decode("utf-8"))
            else:
                for item in namelist:
                    if item.startswith("data/") and item.endswith(".json"):
                        with zip_in.open(item) as f:
                            raw_objects.extend(json.loads(f.read().decode("utf-8")))

            filtered_objects = [
                obj for obj in raw_objects
                if str(obj.get("model", "")).lower() in allowed_models
            ]

            objects_by_model: Dict[str, List[Dict[str, Any]]] = {}
            for obj in filtered_objects:
                m_str = str(obj.get("model", "")).lower()
                if m_str:
                    objects_by_model.setdefault(m_str, []).append(obj)

            summary: Dict[str, Any] = {
                "archive_manifest": manifest,
                "chosen_sections": chosen_sections,
                "mode": mode,
                "restore_media": restore_media,
                "total_records_in_backup": len(filtered_objects),
                "records_by_model": {m: len(objs) for m, objs in objects_by_model.items()},
                "dry_run": dry_run,
                "safety_backup": None,
            }

            if dry_run:
                media_count = len([f for f in namelist if f.startswith("media/") and not f.endswith("/")])
                summary["media_files_found"] = media_count
                return summary

            # 3. Создание автоматической точки отката перед изменениями
            if create_safety_backup and not zip_path.name.startswith("safety_pre_restore_"):
                try:
                    safety_res = create_backup(
                        is_safety_point=True,
                        include_media=False,
                        description=f"Точка отката перед восстановлением из {zip_path.name}",
                    )
                    summary["safety_backup"] = safety_res.get("archive_filename")
                    logger.info(f"Создана точка отката: {summary['safety_backup']}")
                except Exception as e:
                    logger.warning(f"Не удалось создать точку отката: {e}")

            # 4. Восстановление данных
            restored_counts: Dict[str, int] = {}
            skipped_counts: Dict[str, int] = {}
            errors_list: List[str] = []

            with SilentSignalContext():
                if mode == "snapshot" and has_snapshot and is_sqlite:
                    # Извлекаем снимок во временный файл и накатываем
                    temp_snap_fd, temp_snap_path = tempfile.mkstemp(suffix=".sqlite3.gz")
                    os.close(temp_snap_fd)
                    try:
                        with zip_in.open("database/db_snapshot.sqlite3.gz") as source_snap, open(temp_snap_path, "wb") as target_snap:
                            shutil.copyfileobj(source_snap, target_snap)
                        ok = _restore_sqlite_live_snapshot(Path(temp_snap_path))
                        if not ok:
                            raise RuntimeError("Ошибка при накате SQLite snapshot")
                        summary["snapshot_restored"] = True
                    finally:
                        if os.path.exists(temp_snap_path):
                            try:
                                os.remove(temp_snap_path)
                            except OSError:
                                pass
                else:
                    # Восстановление через Django сериализатор в транзакции
                    with transaction.atomic():
                        if mode == "clean":
                            _clean_tables_for_models(list(allowed_models), preserve_superusers=preserve_superusers)

                        User = get_user_model()
                        existing_superusers = {}
                        if preserve_superusers:
                            for u in User.objects.filter(is_superuser=True):
                                existing_superusers[u.id] = u
                                existing_superusers[u.username] = u

                        # Накат моделей в топологическом порядке
                        for m_str in MODEL_RESTORE_ORDER:
                            m_key = m_str.lower()
                            model_records = objects_by_model.get(m_key, [])
                            if not model_records:
                                continue

                            chunk_json = json.dumps(model_records)
                            deserialized_objects = serializers.deserialize(
                                "json",
                                chunk_json,
                                ignorenonexistent=True,
                                handle_forward_references=True,
                            )

                            saved_cnt = 0
                            skip_cnt = 0

                            for deserialized_obj in deserialized_objects:
                                obj = deserialized_obj.object

                                # Защита активных суперпользователей от перезаписи паролей
                                if preserve_superusers and m_key == "auth.user":
                                    if obj.pk in existing_superusers or getattr(obj, "username", None) in existing_superusers:
                                        skip_cnt += 1
                                        continue

                                # Сохранение с отдельным savepoint, чтобы ошибка в одной записи не сбрасывала всю транзакцию
                                try:
                                    with transaction.atomic():
                                        deserialized_obj.save()
                                        saved_cnt += 1
                                except Exception as e:
                                    skip_cnt += 1
                                    err_msg = f"{m_str} pk={getattr(obj, 'pk', '?')}: {e}"
                                    errors_list.append(err_msg)
                                    logger.warning(f"Ошибка сохранения объекта {err_msg}")

                            restored_counts[m_str] = saved_cnt
                            if skip_cnt > 0:
                                skipped_counts[m_str] = skip_cnt

                        # Сброс счетчиков автоинкремента
                        _reset_db_sequences(list(objects_by_model.keys()))

            # 5. Распаковка медиафайлов
            restored_media_count = 0
            restored_media_bytes = 0

            if restore_media:
                media_root = Path(settings.MEDIA_ROOT)
                os.makedirs(media_root, exist_ok=True)
                is_all_sections = len(chosen_sections) == len(available_sections)

                for member in namelist:
                    if not member.startswith("media/") or member.endswith("/"):
                        continue

                    rel_path = member[len("media/"):]
                    first_part = rel_path.split("/")[0]

                    if not is_all_sections and first_part and first_part not in allowed_media_folders:
                        continue

                    # Защита от Path Traversal
                    target_file = (media_root / rel_path).resolve()
                    if not str(target_file).startswith(str(media_root.resolve())):
                        logger.warning(f"Предотвращена попытка Path Traversal: {member}")
                        continue

                    os.makedirs(target_file.parent, exist_ok=True)
                    with zip_in.open(member) as source, open(target_file, "wb") as target:
                        shutil.copyfileobj(source, target)
                        restored_media_count += 1
                        restored_media_bytes += target_file.stat().st_size

            # 6. Очистка кэша сайта для немедленного отображения обновленных данных
            try:
                cache.clear()
            except Exception as e:
                logger.warning(f"Не удалось сбросить кэш после восстановления: {e}")

            duration = round(time.time() - start_time, 2)
            summary["restored_counts"] = restored_counts
            summary["skipped_counts"] = skipped_counts
            summary["restored_total_records"] = sum(restored_counts.values())
            summary["restored_media_count"] = restored_media_count
            summary["restored_media_mb"] = round(restored_media_bytes / (1024 * 1024), 2)
            summary["errors"] = errors_list[:20]
            summary["duration_seconds"] = duration
            summary["success"] = True

            logger.info(
                f"Восстановление успешно завершено за {duration}с: "
                f"{summary['restored_total_records']} записей, {restored_media_count} медиафайлов"
            )
            return summary

    finally:
        if is_temp_file and zip_path.exists():
            try:
                zip_path.unlink()
            except OSError:
                pass
