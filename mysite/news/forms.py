from django import forms
from tinymce.widgets import TinyMCE
from .models import News
from .widgets import ModernDateTimePickerWidget


class NewsAdminForm(forms.ModelForm):
    """Форма для панели управления Django с красивым выбором даты и времени."""
    class Meta:
        model = News
        fields = "__all__"
        widgets = {
            "published_at": ModernDateTimePickerWidget(),
            "content": TinyMCE(),
            "snippet": forms.Textarea(attrs={
                "rows": 3,
                "class": "vLargeTextField",
                "placeholder": "Краткое описание новости для карточки и анонса..."
            }),
        }


class NewsForm(forms.ModelForm):
    """Публичная / внутренняя форма для добавления и быстрого редактирования новостей."""
    class Meta:
        model = News
        fields = [
            "title",
            "slug",
            "news_type",
            "published_at",
            "related_products",
            "related_categories",
            "image",
            "snippet",
            "content",
            "related_url",
            "is_published",
            "meta_title",
            "meta_description",
            "meta_keywords",
        ]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control form-control-lg",
                "placeholder": "Введите заголовок новости..."
            }),
            "slug": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "novost-primera (если оставить пустым, сформируется автоматически)"
            }),
            "news_type": forms.Select(attrs={
                "class": "form-select"
            }),
            "related_products": forms.SelectMultiple(attrs={
                "class": "form-select",
                "size": 6,
                "title": "Удерживайте Ctrl (Cmd на Mac) для выбора нескольких товаров"
            }),
            "related_categories": forms.SelectMultiple(attrs={
                "class": "form-select",
                "size": 4,
                "title": "Удерживайте Ctrl (Cmd на Mac) для выбора нескольких категорий"
            }),
            "published_at": ModernDateTimePickerWidget(attrs={
                "class": "form-control form-control-lg"
            }),
            "image": forms.ClearableFileInput(attrs={
                "class": "form-control"
            }),
            "snippet": forms.Textarea(attrs={
                "rows": 3,
                "class": "form-control",
                "placeholder": "Краткий анонс для ленты новостей..."
            }),
            "content": forms.Textarea(attrs={
                "rows": 8,
                "class": "form-control",
                "placeholder": "Полный текст новости (поддерживается HTML-разметка)..."
            }),
            "related_url": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "/catalog/ или /about/ (необязательно)"
            }),
            "is_published": forms.CheckboxInput(attrs={
                "class": "form-check-input"
            }),
            "meta_title": forms.TextInput(attrs={"class": "form-control"}),
            "meta_description": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "meta_keywords": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["snippet"].required = False
        if "related_products" in self.fields:
            self.fields["related_products"].required = False
        if "related_categories" in self.fields:
            self.fields["related_categories"].required = False
