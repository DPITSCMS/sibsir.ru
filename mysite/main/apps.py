from django.apps import AppConfig


class MainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "main"
    verbose_name = "Управление сайтом"

    def ready(self):
        try:
            from .signals import connect_seo_signals
            connect_seo_signals()
        except Exception:
            pass

