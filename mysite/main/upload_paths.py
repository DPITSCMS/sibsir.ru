import os
from django.utils import timezone
from django.utils.deconstruct import deconstructible


def build_image_upload_path(category: str, filename: str, now=None) -> str:
    """
    Формирует относительный путь для загрузки изображений:
    <category>/<YYYY>/<MM>/<DD>/sibsir-ru_<category>_<YYYY-MM-DD>.<ext>
    """
    clean_category = (category or "images").strip("/").replace("/", "_")
    current_dt = timezone.localtime(now or timezone.now())
    year = current_dt.strftime("%Y")
    month = current_dt.strftime("%m")
    day = current_dt.strftime("%d")
    upload_date = current_dt.strftime("%Y-%m-%d")

    _, ext = os.path.splitext(filename or "")
    ext = ext.lower()

    new_filename = f"sibsir-ru_{clean_category}_{upload_date}{ext}"
    return f"{clean_category}/{year}/{month}/{day}/{new_filename}"


@deconstructible
class CategoryDateUploadTo:
    """Сериализуемый генератор upload_to для ImageField и FileField."""

    def __init__(self, category: str):
        self.category = category

    def __call__(self, instance, filename: str) -> str:
        return build_image_upload_path(self.category, filename)

    def __eq__(self, other):
        return (
            isinstance(other, CategoryDateUploadTo)
            and self.category == other.category
        )
