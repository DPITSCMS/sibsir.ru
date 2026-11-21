import sys
from pathlib import Path
from django.core.management.base import BaseCommand
from main.backup_manager import (
    create_backup,
    cleanup_old_backups,
    get_system_stats,
    BACKUP_SECTIONS,
    get_backup_dir,
)


class Command(BaseCommand):
    help = "Создает резервную копию базы данных и медиафайлов (каталог, заказы, клиенты, статьи, новости, настройки)"

    def add_arguments(self, parser):
        parser.add_argument(
            "-i", "--include",
            type=str,
            default="all",
            help="Секции для бэкапа: catalog, orders, users, articles, news, settings (или 'all', или через запятую)",
        )
        parser.add_argument(
            "--no-media",
            action="store_true",
            default=False,
            help="Не включать картинки и медиафайлы в архив (только база данных)",
        )
        parser.add_argument(
            "--quick-db",
            action="store_true",
            default=False,
            help="Быстрый дамп: отключить медиафайлы (аналог --no-media)",
        )
        parser.add_argument(
            "-o", "--output",
            type=str,
            default="",
            help="Путь для сохранения .zip файла архива",
        )
        parser.add_argument(
            "-d", "--description",
            type=str,
            default="",
            help="Пояснительное описание резервной копии",
        )
        parser.add_argument(
            "--no-snapshot",
            action="store_true",
            default=False,
            help="Не создавать бинарный снимок SQLite базы данных",
        )
        parser.add_argument(
            "--rotate",
            type=int,
            default=0,
            help="Автоматически удалить старые бэкапы, сохранив указанное количество свежих архивов",
        )
        parser.add_argument(
            "--stats",
            action="store_true",
            help="Показать текущую статистику базы данных и файлов без создания бэкапа",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== РЕЗЕРВНОЕ КОПИРОВАНИЕ ТМ «СИБСЫР» ==="))

        if options["stats"]:
            stats = get_system_stats()
            self.stdout.write(self.style.SUCCESS("Текущая статистика системы:"))
            self.stdout.write(f"  • Категории каталога:       {stats.get('categories_count', 0)}")
            self.stdout.write(f"  • Товары в каталоге:        {stats.get('products_count', 0)}")
            self.stdout.write(f"  • Акции и спецпредложения:  {stats.get('promotions_count', 0)}")
            self.stdout.write(f"  • Отзывы к товарам:         {stats.get('reviews_count', 0)}")
            self.stdout.write(f"  • Заказы покупателей:       {stats.get('orders_count', 0)} (позиций: {stats.get('order_items_count', 0)})")
            self.stdout.write(f"  • Клиенты и пользователи:   {stats.get('users_count', 0)} (профилей: {stats.get('profiles_count', 0)}, юрлиц: {stats.get('legal_profiles_count', 0)})")
            self.stdout.write(f"  • Новости компании:         {stats.get('news_count', 0)}")
            self.stdout.write(f"  • Статьи блога:             {stats.get('articles_count', 0)}")
            self.stdout.write(f"  • CMS страницы:             {stats.get('pages_count', 0)}")
            self.stdout.write(f"  • Заявки на звонки/прайс:   {stats.get('callbacks_count', 0)} / {stats.get('wholesale_requests_count', 0)}")
            self.stdout.write(f"  • Медиафайлы (изображения): {stats.get('media_files_count', 0)} ({stats.get('media_total_mb', 0)} MB)")
            self.stdout.write(f"  • Свободно на диске:        {stats.get('disk_free_mb', 0)} MB")
            return

        include_raw = options["include"].strip()
        if include_raw == "all":
            sections = list(BACKUP_SECTIONS.keys())
        else:
            sections = [s.strip().lower() for s in include_raw.split(",") if s.strip()]

        include_media = not (options["no_media"] or options["quick_db"])
        output_file = options["output"] or None
        description = options["description"]
        include_snapshot = not options["no_snapshot"]

        self.stdout.write(f"Выбранные секции: {', '.join(sections)}")
        self.stdout.write(f"Включение медиафайлов: {'Да (адаптивное быстрое сжатие)' if include_media else 'Нет (только база данных)'}")
        self.stdout.write(f"Снимок SQLite: {'Да' if include_snapshot else 'Нет'}")
        self.stdout.write("Создание резервной копии...")

        try:
            res = create_backup(
                sections=sections,
                include_media=include_media,
                output_path=output_file,
                description=description,
                include_db_snapshot=include_snapshot,
            )

            self.stdout.write(self.style.SUCCESS(f"\n[OK] Резервная копия успешно создана за {res.get('duration_seconds', 0)}с!"))
            self.stdout.write(f"  • Файл архива:     {res['archive_filename']}")
            self.stdout.write(f"  • Полный путь:     {res['archive_path']}")
            self.stdout.write(f"  • Размер архива:   {res['archive_size_mb']} MB")
            self.stdout.write(f"  • Записей в БД:    {res['total_db_records']}")
            self.stdout.write(f"  • Медиафайлов:     {res['media_files_count']} ({res['media_total_mb']} MB)")
            self.stdout.write(f"  • Контрольная сумма: SHA-256 = {res.get('sha256', '')}")
            self.stdout.write(f"  • Секции:          {', '.join(res['sections'])}")

            self.stdout.write("\nДетализация объектов по секциям:")
            for sec, cnt in res.get("section_stats", {}).items():
                title = BACKUP_SECTIONS.get(sec, {}).get("title", sec)
                self.stdout.write(f"  - {title}: {cnt} записей")

            if options["rotate"] > 0:
                rot_res = cleanup_old_backups(keep_count=options["rotate"], keep_safety_count=5)
                if rot_res["deleted_count"] > 0:
                    self.stdout.write(self.style.WARNING(
                        f"\nРотация: удалено {rot_res['deleted_count']} старых архивов, "
                        f"освобождено {rot_res['freed_mb']} MB"
                    ))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"\n[ОШИБКА] Не удалось создать резервную копию: {e}"))
            sys.exit(1)
