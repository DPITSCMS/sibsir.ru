from django.core.management.base import BaseCommand
from main.indexnow import submit_all_site_urls, collect_all_site_urls


class Command(BaseCommand):
    help = "Отправляет все опубликованные страницы сайта в Яндекс и Bing по протоколу IndexNow"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать список найденных URL без фактической отправки запроса",
        )

    def handle(self, *args, **options):
        urls = collect_all_site_urls()
        self.stdout.write(self.style.NOTICE(f"Найдено URL для индексации: {len(urls)}"))

        if options.get("dry_run"):
            for u in urls:
                self.stdout.write(f" - {u}")
            self.stdout.write(self.style.SUCCESS("Режим --dry-run завершен без отправки."))
            return

        self.stdout.write("Отправка запроса в поисковые системы Яндекс и Bing...")
        results = submit_all_site_urls(async_req=False)

        for endpoint, res in results.items():
            status = res.get("status_code", 0)
            if res.get("success"):
                self.stdout.write(self.style.SUCCESS(f"✔ [{endpoint}] Успешно (HTTP {status})"))
            else:
                self.stdout.write(self.style.WARNING(f"✖ [{endpoint}] Ошибка (HTTP {status}): {res.get('text', '')}"))

        self.stdout.write(self.style.SUCCESS("Процесс IndexNow завершен."))
