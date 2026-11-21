import sys
from pathlib import Path
from django.core.management.base import BaseCommand
from main.backup_manager import (
    restore_backup,
    inspect_backup,
    get_backup_manifest,
    get_backup_dir,
    BACKUP_SECTIONS,
    list_existing_backups,
)


class Command(BaseCommand):
    help = "Восстанавливает данные и медиафайлы (товары, картинки, заказы, клиенты, статьи, новости) из архива резервной копии"

    def add_arguments(self, parser):
        parser.add_argument(
            "archive",
            nargs="?",
            type=str,
            default="",
            help="Путь к .zip файлу бэкапа (если не указан, используется самый свежий из папки backups)",
        )
        parser.add_argument(
            "-i", "--include",
            type=str,
            default="all",
            help="Секции для восстановления: catalog, orders, users, articles, news, settings (или 'all', или через запятую)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            default=False,
            help="Очистить таблицы выбранных моделей перед импортом (Режим чистого деплоя). Администраторы сохраняются.",
        )
        parser.add_argument(
            "--merge",
            action="store_true",
            default=False,
            help="Режим слияния: сохранить текущие данные и дополнить/обновить их из архива (по умолчанию)",
        )
        parser.add_argument(
            "--snapshot",
            action="store_true",
            default=False,
            help="Прямое восстановление бинарного снимка базы данных SQLite (при его наличии в архиве)",
        )
        parser.add_argument(
            "--no-media",
            action="store_true",
            default=False,
            help="Не распаковывать картинки в media/ (только восстановление базы данных)",
        )
        parser.add_argument(
            "--no-safety-backup",
            action="store_true",
            default=False,
            help="Не создавать автоматическую точку отката перед восстановлением",
        )
        parser.add_argument(
            "--inspect",
            action="store_true",
            default=False,
            help="Провести подробную инспекцию архива и сравнить с текущей живой БД без внесения изменений",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Тестовая проверка чтения архива без записи в БД",
        )
        parser.add_argument(
            "-y", "--yes",
            action="store_true",
            default=False,
            help="Пропустить интерактивный запрос подтверждения (для автоматизации и CI/CD)",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="Показать список всех доступных архивов резервных копий и выйти",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== СИСТЕМА ВОССТАНОВЛЕНИЯ ДАННЫХ ТМ «СИБСЫР» ==="))

        if options["list"]:
            backups = list_existing_backups()
            if not backups:
                self.stdout.write(self.style.WARNING("Резервные копии не найдены в папке backups/"))
                return
            self.stdout.write(self.style.SUCCESS(f"Найдено {len(backups)} резервных копий в {get_backup_dir()}:"))
            for b in backups:
                date_str = b.get("mtime", "").strftime("%Y-%m-%d %H:%M:%S") if hasattr(b.get("mtime"), "strftime") else str(b.get("created_at", ""))
                safety_tag = " [ТОЧКА ОТКАТА]" if b.get("is_safety_point") else ""
                snap_tag = " [SQLITE SNAPSHOT]" if b.get("has_sqlite_snapshot") else ""
                self.stdout.write(
                    f"  • {b['filename']}{safety_tag}{snap_tag} [{b.get('archive_size_mb', 0)} MB] - "
                    f"Дата: {date_str}, Записей: {b.get('total_db_records', '?')}, Медиа: {b.get('media_files_count', '?')}"
                )
            return

        archive_input = options["archive"].strip()
        if archive_input:
            archive_path = Path(archive_input)
            if not archive_path.is_absolute() and not archive_path.exists():
                alt_path = get_backup_dir() / archive_input
                if alt_path.exists():
                    archive_path = alt_path
        else:
            backups = list_existing_backups()
            if not backups:
                self.stderr.write(self.style.ERROR("[ОШИБКА] Архив не указан, а в папке backups/ нет резервных копий!"))
                self.stderr.write("Сначала создайте бэкап: python manage.py backup_data")
                sys.exit(1)
            archive_path = Path(backups[0]["filepath"])
            self.stdout.write(f"Автоматически выбран самый свежий архив: {archive_path.name}")

        if not archive_path.exists():
            self.stderr.write(self.style.ERROR(f"[ОШИБКА] Файл архива не найден: {archive_path}"))
            sys.exit(1)

        # Инспекция архива
        if options["inspect"]:
            report = inspect_backup(archive_path)
            if not report.get("valid"):
                self.stderr.write(self.style.ERROR(f"Ошибка проверки архива: {report.get('error')}"))
                sys.exit(1)

            self.stdout.write(self.style.SUCCESS(f"\n[ИНСПЕКЦИЯ АРХИВА]: {report['filename']}"))
            self.stdout.write(f"  • Размер:            {report['archive_size_mb']} MB")
            self.stdout.write(f"  • Дата создания:     {report.get('created_at', 'не указана')}")
            self.stdout.write(f"  • Описание:          {report.get('description', '')}")
            self.stdout.write(f"  • Точка отката:      {'Да' if report.get('is_safety_point') else 'Нет'}")
            self.stdout.write(f"  • Снимок SQLite:     {'Присутствует' if report.get('has_sqlite_snapshot') else 'Отсутствует'}")
            self.stdout.write(f"  • Всего записей:     {report.get('total_db_records', 0)}")
            self.stdout.write(f"  • Медиафайлов:       {report.get('media_files_count', 0)} ({report.get('media_total_mb', 0)} MB)")
            self.stdout.write(f"  • SHA-256:           {report.get('sha256', '')}")

            self.stdout.write("\nСравнение записей архива с текущей базой данных:")
            self.stdout.write(f"  {'Модель':<32} {'В архиве':<10} {'В текущей БД':<14} {'Разница':<10}")
            self.stdout.write("  " + "-" * 68)
            for item in report.get("models_comparison", []):
                diff_str = f"+{item['diff']}" if item['diff'] > 0 else str(item['diff'])
                self.stdout.write(f"  {item['title']:<32} {item['backup_count']:<10} {item['current_db_count']:<14} {diff_str:<10}")

            if report.get("media_folders"):
                self.stdout.write("\nПапки с медиафайлами:")
                for mf in report["media_folders"]:
                    self.stdout.write(f"  • media/{mf['folder']}/ — {mf['count']} файлов")
            return

        include_raw = options["include"].strip()
        if include_raw == "all":
            sections = list(BACKUP_SECTIONS.keys())
        else:
            sections = [s.strip().lower() for s in include_raw.split(",") if s.strip()]

        # Определение режима восстановления
        if options["snapshot"]:
            mode = "snapshot"
        elif options["clear"]:
            mode = "clean"
        else:
            mode = "merge"

        restore_media = not options["no_media"]
        create_safety = not options["no_safety_backup"]
        dry_run = options["dry_run"]
        auto_yes = options["yes"]

        try:
            manifest = get_backup_manifest(archive_path)
            self.stdout.write(self.style.SUCCESS(f"\nАрхив для восстановления: {archive_path.name}"))
            self.stdout.write(f"  • Дата создания:     {manifest.get('created_at', 'неизвестно')}")
            self.stdout.write(f"  • Описание:          {manifest.get('description', '')}")
            self.stdout.write(f"  • Записей в архиве:  {manifest.get('total_db_records', 0)}")
            self.stdout.write(f"  • Медиафайлов:       {manifest.get('media_files_count', 0)} ({manifest.get('media_total_mb', 0)} MB)")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Предупреждение при чтении манифеста: {e}"))

        self.stdout.write(f"\nПараметры восстановления:")
        self.stdout.write(f"  • Режим:               {mode.upper()} ({'Чистый деплой с очисткой' if mode == 'clean' else ('Прямой снимок SQLite' if mode == 'snapshot' else 'Слияние/дополнение данных')})")
        self.stdout.write(f"  • Секции:              {', '.join(sections)}")
        self.stdout.write(f"  • Медиафайлы:          {'Восстанавливать' if restore_media else 'Пропустить (только БД)'}")
        self.stdout.write(f"  • Точка безопасности:  {'Создавать автоматически' if create_safety else 'Отключена'}")

        if dry_run:
            res = restore_backup(
                archive_path_or_file=archive_path,
                sections=sections,
                mode=mode,
                restore_media=restore_media,
                dry_run=True,
            )
            self.stdout.write(self.style.SUCCESS("\n[DRY RUN] Тестовая проверка завершена успешно!"))
            self.stdout.write(f"  • Найдено записей для импорта: {res['total_records_in_backup']}")
            self.stdout.write(f"  • Найдено медиафайлов:         {res.get('media_files_found', 0)}")
            return

        if not auto_yes:
            prompt_msg = (
                "\nВНИМАНИЕ: При режиме чистого деплоя выбранные таблицы будут очищены и заменены данными из архива!\n"
                if mode == "clean" else "\nПрименить восстановление данных из архива? "
            )
            confirm = input(f"{prompt_msg} Введите 'yes' для продолжения: ").strip().lower()
            if confirm not in ("yes", "y", "да"):
                self.stdout.write(self.style.WARNING("Операция отменена пользователем."))
                return

        self.stdout.write("\nВыполняется восстановление...")
        try:
            res = restore_backup(
                archive_path_or_file=archive_path,
                sections=sections,
                mode=mode,
                restore_media=restore_media,
                preserve_superusers=True,
                create_safety_backup=create_safety,
                dry_run=False,
            )

            self.stdout.write(self.style.SUCCESS(f"\n[OK] Восстановление данных успешно завершено за {res.get('duration_seconds', 0)}с!"))
            if res.get("safety_backup"):
                self.stdout.write(self.style.WARNING(f"  • Создана точка отката: {res['safety_backup']}"))
            self.stdout.write(f"  • Восстановлено объектов БД: {res['restored_total_records']}")
            self.stdout.write(f"  • Восстановлено медиа:       {res['restored_media_count']} ({res['restored_media_mb']} MB)")
            self.stdout.write("  • Кэш сайта очищен.")

            if res.get("restored_counts"):
                self.stdout.write("\nДетализация восстановленных моделей:")
                for m, cnt in res["restored_counts"].items():
                    if cnt > 0:
                        self.stdout.write(f"  - {m}: {cnt} записей")

            if res.get("errors"):
                self.stdout.write(self.style.WARNING(f"\nЗамечены предупреждения ({len(res['errors'])}):"))
                for err in res["errors"]:
                    self.stdout.write(f"  ! {err}")

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"\n[ОШИБКА] Сбой при восстановлении данных: {e}"))
            sys.exit(1)
