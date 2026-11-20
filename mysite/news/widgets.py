import json
from django import forms
from django.utils import timezone
from django.utils.safestring import mark_safe


class ModernDateTimePickerWidget(forms.DateTimeInput):
    """
    Современный интерактивный виджет для красивого выбора и изменения даты и времени публикации.
    Включает быстрые кнопки-пресеты (Сейчас, Сегодня 09:00, 14:00, 18:00, Завтра, Вчера, +/- 1 день),
    а также динамический предпросмотр даты на русском языке и статуса публикации.
    """
    input_type = "datetime-local"

    def __init__(self, attrs=None, format="%Y-%m-%dT%H:%M"):
        default_attrs = {
            "class": "form-control modern-datetime-input",
            "style": (
                "font-size: 1rem; font-weight: 600; padding: 0.6rem 0.9rem; "
                "border-radius: 10px; border: 1.5px solid #cbd5e1; max-width: 320px; "
                "box-shadow: inset 0 1px 2px rgba(0,0,0,0.05); color: #0f172a;"
            ),
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs, format=format)

    def format_value(self, value):
        if value is None:
            return ""
        if hasattr(value, "strftime"):
            # Если таймзона активна, приводим к локальному времени
            if timezone.is_aware(value):
                value = timezone.localtime(value)
            return value.strftime("%Y-%m-%dT%H:%M")
        return str(value)

    def render(self, name, value, attrs=None, renderer=None):
        input_html = super().render(name, value, attrs, renderer)
        field_id = attrs.get("id") if attrs else f"id_{name}"

        widget_html = f"""
        <div class="modern-datetime-picker-wrapper" id="wrap_{field_id}" style="margin: 6px 0 14px 0;">
            <div class="d-flex align-items-center gap-2 mb-2 flex-wrap">
                <div class="position-relative" style="display: inline-block;">
                    {input_html}
                </div>
                <div class="datetime-live-preview" id="preview_{field_id}" 
                     style="display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; 
                            background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 20px; 
                            font-size: 0.85rem; font-weight: 600; color: #334155;">
                    <i class="bi bi-calendar-check text-warning" style="font-size: 1rem;"></i>
                    <span class="preview-text">Загрузка даты...</span>
                </div>
            </div>

            <div class="datetime-presets-bar d-flex flex-wrap gap-1 align-items-center" style="font-size: 0.8rem;">
                <span class="text-muted fw-bold me-1" style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;">
                    ⚡ Быстрый выбор:
                </span>
                <button type="button" class="btn btn-sm btn-outline-primary rounded-pill px-2 py-0" 
                        onclick="applyDateTimePreset('{field_id}', 'now')" title="Установить текущие дату и время">
                    🕒 Сейчас
                </button>
                <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0" 
                        onclick="applyDateTimePreset('{field_id}', 'today_9')" title="Сегодня в 09:00">
                    🌅 09:00
                </button>
                <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0" 
                        onclick="applyDateTimePreset('{field_id}', 'today_14')" title="Сегодня в 14:00">
                    ☀️ 14:00
                </button>
                <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0" 
                        onclick="applyDateTimePreset('{field_id}', 'today_18')" title="Сегодня в 18:00">
                    🌆 18:00
                </button>
                <button type="button" class="btn btn-sm btn-outline-info rounded-pill px-2 py-0" 
                        onclick="applyDateTimePreset('{field_id}', 'yesterday')" title="Вчера в это же время">
                    📆 Вчера
                </button>
                <button type="button" class="btn btn-sm btn-outline-success rounded-pill px-2 py-0" 
                        onclick="applyDateTimePreset('{field_id}', 'tomorrow')" title="Завтра в это же время">
                    🚀 Завтра
                </button>
                <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0" 
                        onclick="adjustDateTimeDays('{field_id}', -1)" title="Сдвинуть на 1 день назад">
                    ➖ 1 день
                </button>
                <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0" 
                        onclick="adjustDateTimeDays('{field_id}', 1)" title="Сдвинуть на 1 день вперед">
                    ➕ 1 день
                </button>
            </div>
        </div>

        <script>
        (function() {{
            const input = document.getElementById("{field_id}");
            const preview = document.getElementById("preview_{field_id}");
            if (!input || !preview) return;

            const months = [
                "января", "февраля", "марта", "апреля", "мая", "июня",
                "июля", "августа", "сентября", "октября", "ноября", "декабря"
            ];
            const weekdays = [
                "Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"
            ];

            function updatePreview() {{
                const val = input.value;
                if (!val) {{
                    preview.innerHTML = '<i class="bi bi-exclamation-circle text-muted"></i> <span class="text-muted">Дата не указана</span>';
                    return;
                }}
                const d = new Date(val);
                if (isNaN(d.getTime())) {{
                    preview.innerHTML = '<span class="text-danger">Неверный формат</span>';
                    return;
                }}

                const now = new Date();
                const day = d.getDate();
                const month = months[d.getMonth()];
                const year = d.getFullYear();
                const hours = String(d.getHours()).padStart(2, '0');
                const mins = String(d.getMinutes()).padStart(2, '0');
                const wday = weekdays[d.getDay()];

                const isFuture = d > now;
                const badge = isFuture 
                    ? '<span class="badge bg-primary-subtle text-primary border border-primary-subtle ms-1">⏳ Запланировано</span>'
                    : '<span class="badge bg-success-subtle text-success border border-success-subtle ms-1">✓ Опубликовано</span>';

                preview.innerHTML = `<i class="bi bi-calendar-event text-warning"></i> <span>${{day}} ${{month}} ${{year}} г., ${{hours}}:${{mins}} (${{wday}})</span> ${{badge}}`;
            }}

            input.addEventListener("input", updatePreview);
            input.addEventListener("change", updatePreview);
            updatePreview();
        }})();

        if (typeof window.applyDateTimePreset === "undefined") {{
            window.applyDateTimePreset = function(fieldId, preset) {{
                const input = document.getElementById(fieldId);
                if (!input) return;
                const now = new Date();
                let target = new Date();

                if (preset === "now") {{
                    target = now;
                }} else if (preset === "today_9") {{
                    target.setHours(9, 0, 0, 0);
                }} else if (preset === "today_14") {{
                    target.setHours(14, 0, 0, 0);
                }} else if (preset === "today_18") {{
                    target.setHours(18, 0, 0, 0);
                }} else if (preset === "yesterday") {{
                    target.setDate(target.getDate() - 1);
                }} else if (preset === "tomorrow") {{
                    target.setDate(target.getDate() + 1);
                }}

                const pad = (n) => String(n).padStart(2, '0');
                const formatted = target.getFullYear() + '-' +
                                  pad(target.getMonth() + 1) + '-' +
                                  pad(target.getDate()) + 'T' +
                                  pad(target.getHours()) + ':' +
                                  pad(target.getMinutes());
                input.value = formatted;
                input.dispatchEvent(new Event("change"));
            }};

            window.adjustDateTimeDays = function(fieldId, deltaDays) {{
                const input = document.getElementById(fieldId);
                if (!input) return;
                let cur = input.value ? new Date(input.value) : new Date();
                if (isNaN(cur.getTime())) cur = new Date();
                cur.setDate(cur.getDate() + deltaDays);

                const pad = (n) => String(n).padStart(2, '0');
                const formatted = cur.getFullYear() + '-' +
                                  pad(cur.getMonth() + 1) + '-' +
                                  pad(cur.getDate()) + 'T' +
                                  pad(cur.getHours()) + ':' +
                                  pad(cur.getMinutes());
                input.value = formatted;
                input.dispatchEvent(new Event("change"));
            }};
        }}
        </script>
        """
        return mark_safe(widget_html)
