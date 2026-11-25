"""
Современные виджеты выбора даты/времени для Django-администрации.

ModernDateTimePickerWidget — для полей DateTimeField (дата + время).
ModernDatePickerWidget    — для полей DateField (только дата).

Оба виджета включают:
  • автоматическую подстановку текущего момента при создании новой записи
  • live-превью выбранного значения на русском языке
  • панель быстрых пресетов (Сейчас / Сегодня 09:00 / Сегодня 14:00 / Сегодня 18:00 / Вчера / Завтра / ±1 день)
"""

from django import forms
from django.utils import timezone
from django.utils.safestring import mark_safe


# ---------------------------------------------------------------------------
# Общий JavaScript (инициализируется один раз на странице)
# ---------------------------------------------------------------------------
_SHARED_JS = """
<script>
if (typeof window._mdpInitialized === "undefined") {
    window._mdpInitialized = true;

    const _MONTHS = [
        "января","февраля","марта","апреля","мая","июня",
        "июля","августа","сентября","октября","ноября","декабря"
    ];
    const _WEEKDAYS = [
        "Воскресенье","Понедельник","Вторник","Среда","Четверг","Пятница","Суббота"
    ];

    function _pad(n) { return String(n).padStart(2,"0"); }

    function _toInputValue(d, withTime) {
        const base = d.getFullYear() + "-" + _pad(d.getMonth()+1) + "-" + _pad(d.getDate());
        return withTime ? base + "T" + _pad(d.getHours()) + ":" + _pad(d.getMinutes()) : base;
    }

    function _formatPreview(d, withTime) {
        const day   = d.getDate();
        const month = _MONTHS[d.getMonth()];
        const year  = d.getFullYear();
        if (!withTime) return `${day} ${month} ${year} г. (${_WEEKDAYS[d.getDay()]})`;
        const h = _pad(d.getHours()), m = _pad(d.getMinutes());
        const isFuture = d > new Date();
        const badge = isFuture
            ? '<span class="badge bg-primary-subtle text-primary border border-primary-subtle ms-1">⏳ Запланировано</span>'
            : '<span class="badge bg-success-subtle text-success border border-success-subtle ms-1">✓ Опубликовано</span>';
        return `${day} ${month} ${year} г., ${h}:${m} (${_WEEKDAYS[d.getDay()]}) ${badge}`;
    }

    window.mdpUpdatePreview = function(fieldId, withTime) {
        const input   = document.getElementById(fieldId);
        const preview = document.getElementById("preview_" + fieldId);
        if (!input || !preview) return;
        const val = input.value;
        if (!val) {
            preview.innerHTML = '<span class="text-muted">Дата не указана</span>';
            return;
        }
        const d = new Date(val);
        if (isNaN(d.getTime())) {
            preview.innerHTML = '<span class="text-danger">Неверный формат</span>';
            return;
        }
        preview.innerHTML = _formatPreview(d, withTime);
    };

    window.mdpApplyPreset = function(fieldId, preset, withTime) {
        const input = document.getElementById(fieldId);
        if (!input) return;
        const now = new Date();
        let t = new Date();
        if      (preset === "now")       t = now;
        else if (preset === "today_9")   t.setHours(9,  0, 0, 0);
        else if (preset === "today_14")  t.setHours(14, 0, 0, 0);
        else if (preset === "today_18")  t.setHours(18, 0, 0, 0);
        else if (preset === "yesterday") t.setDate(t.getDate() - 1);
        else if (preset === "tomorrow")  t.setDate(t.getDate() + 1);
        input.value = _toInputValue(t, withTime);
        input.dispatchEvent(new Event("change"));
    };

    window.mdpAdjustDays = function(fieldId, delta, withTime) {
        const input = document.getElementById(fieldId);
        if (!input) return;
        let cur = input.value ? new Date(input.value) : new Date();
        if (isNaN(cur.getTime())) cur = new Date();
        cur.setDate(cur.getDate() + delta);
        input.value = _toInputValue(cur, withTime);
        input.dispatchEvent(new Event("change"));
    };

    // Автоподстановка «Сейчас» для пустых полей при загрузке страницы
    window.mdpAutoFill = function(fieldId, withTime) {
        const input = document.getElementById(fieldId);
        if (!input) return;
        if (!input.value) {
            input.value = _toInputValue(new Date(), withTime);
            input.dispatchEvent(new Event("change"));
        }
    };
}
</script>
"""


def _render_picker(name, value, attrs, field_id, with_time, fmt_value_fn):
    """Общий рендер пикера для DateTimeField и DateField."""
    input_type = "datetime-local" if with_time else "date"
    input_attrs = dict(attrs or {})
    input_attrs.setdefault("id", field_id)
    input_attrs["type"] = input_type
    input_attrs["name"] = name
    input_attrs.setdefault("class", "")
    input_attrs["class"] = (input_attrs["class"] + " modern-datetime-input").strip()
    input_attrs.setdefault("style", (
        "font-size: 1rem; font-weight: 600; padding: 0.6rem 0.9rem; "
        "border-radius: 10px; border: 1.5px solid #cbd5e1; max-width: 320px; "
        "box-shadow: inset 0 1px 2px rgba(0,0,0,0.05); color: #0f172a;"
    ))

    input_value = fmt_value_fn(value) if value else ""
    attr_str = " ".join(
        f'{k}="{v}"' for k, v in input_attrs.items() if v is not None
    )
    input_html = f'<input {attr_str} value="{input_value}">'

    # Пресеты — только для datetime (time-preset buttons)
    if with_time:
        presets_html = f"""
        <div class="datetime-presets-bar d-flex flex-wrap gap-1 align-items-center" style="font-size: 0.8rem;">
            <span class="text-muted fw-bold me-1" style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;">⚡ Быстро:</span>
            <button type="button" class="btn btn-sm btn-outline-primary rounded-pill px-2 py-0"
                    onclick="mdpApplyPreset('{field_id}','now',true)">🕒 Сейчас</button>
            <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0"
                    onclick="mdpApplyPreset('{field_id}','today_9',true)">🌅 09:00</button>
            <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0"
                    onclick="mdpApplyPreset('{field_id}','today_14',true)">☀️ 14:00</button>
            <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0"
                    onclick="mdpApplyPreset('{field_id}','today_18',true)">🌆 18:00</button>
            <button type="button" class="btn btn-sm btn-outline-info rounded-pill px-2 py-0"
                    onclick="mdpApplyPreset('{field_id}','yesterday',true)">📆 Вчера</button>
            <button type="button" class="btn btn-sm btn-outline-success rounded-pill px-2 py-0"
                    onclick="mdpApplyPreset('{field_id}','tomorrow',true)">🚀 Завтра</button>
            <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0"
                    onclick="mdpAdjustDays('{field_id}',-1,true)">➖ 1 день</button>
            <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0"
                    onclick="mdpAdjustDays('{field_id}',1,true)">➕ 1 день</button>
        </div>"""
    else:
        presets_html = f"""
        <div class="datetime-presets-bar d-flex flex-wrap gap-1 align-items-center" style="font-size: 0.8rem;">
            <span class="text-muted fw-bold me-1" style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;">⚡ Быстро:</span>
            <button type="button" class="btn btn-sm btn-outline-primary rounded-pill px-2 py-0"
                    onclick="mdpApplyPreset('{field_id}','now',false)">📅 Сегодня</button>
            <button type="button" class="btn btn-sm btn-outline-info rounded-pill px-2 py-0"
                    onclick="mdpApplyPreset('{field_id}','yesterday',false)">📆 Вчера</button>
            <button type="button" class="btn btn-sm btn-outline-success rounded-pill px-2 py-0"
                    onclick="mdpApplyPreset('{field_id}','tomorrow',false)">🚀 Завтра</button>
            <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0"
                    onclick="mdpAdjustDays('{field_id}',-1,false)">➖ 1 день</button>
            <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill px-2 py-0"
                    onclick="mdpAdjustDays('{field_id}',1,false)">➕ 1 день</button>
            <button type="button" class="btn btn-sm btn-outline-warning rounded-pill px-2 py-0"
                    onclick="mdpAdjustDays('{field_id}',-7,false)">➖ Неделя</button>
            <button type="button" class="btn btn-sm btn-outline-warning rounded-pill px-2 py-0"
                    onclick="mdpAdjustDays('{field_id}',7,false)">➕ Неделя</button>
            <button type="button" class="btn btn-sm btn-outline-danger rounded-pill px-2 py-0"
                    onclick="mdpAdjustDays('{field_id}',-30,false)">➖ Месяц</button>
            <button type="button" class="btn btn-sm btn-outline-danger rounded-pill px-2 py-0"
                    onclick="mdpAdjustDays('{field_id}',30,false)">➕ Месяц</button>
        </div>"""

    with_time_js = "true" if with_time else "false"
    html = f"""
{_SHARED_JS}
<div class="modern-datetime-picker-wrapper" id="wrap_{field_id}" style="margin: 6px 0 14px 0;">
    <div class="d-flex align-items-center gap-2 mb-2 flex-wrap">
        <div class="position-relative" style="display: inline-block;">
            {input_html}
        </div>
        <div class="datetime-live-preview" id="preview_{field_id}"
             style="display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px;
                    background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 20px;
                    font-size: 0.85rem; font-weight: 600; color: #334155;">
            <span class="preview-text">Загрузка даты...</span>
        </div>
    </div>
    {presets_html}
</div>
<script>
(function() {{
    const fid = "{field_id}";
    const wt  = {with_time_js};
    const inp = document.getElementById(fid);
    if (!inp) return;
    // Автозаполнение пустого поля при создании новой записи
    if (!inp.value) {{
        mdpAutoFill(fid, wt);
    }}
    inp.addEventListener("input",  function() {{ mdpUpdatePreview(fid, wt); }});
    inp.addEventListener("change", function() {{ mdpUpdatePreview(fid, wt); }});
    // Первичное обновление превью (с небольшой задержкой после рендера)
    setTimeout(function() {{ mdpUpdatePreview(fid, wt); }}, 50);
}})();
</script>
"""
    return mark_safe(html)


# ---------------------------------------------------------------------------
# Виджет для DateTimeField
# ---------------------------------------------------------------------------
class ModernDateTimePickerWidget(forms.DateTimeInput):
    """
    Красивый пикер даты+времени для полей DateTimeField.
    • Автозаполняет пустые поля текущим моментом (только для создания).
    • Live-превью на русском: «21 ноября 2026 г., 14:00 (Пятница) ✓ Опубликовано».
    • Быстрые пресеты: Сейчас, 09:00, 14:00, 18:00, Вчера, Завтра, ±1 день.
    """
    input_type = "datetime-local"

    def __init__(self, attrs=None, format="%Y-%m-%dT%H:%M"):
        super().__init__(attrs=attrs or {}, format=format)

    def format_value(self, value):
        if value is None:
            return ""
        if hasattr(value, "strftime"):
            if timezone.is_aware(value):
                value = timezone.localtime(value)
            return value.strftime("%Y-%m-%dT%H:%M")
        return str(value)

    def render(self, name, value, attrs=None, renderer=None):
        field_id = (attrs or {}).get("id", f"id_{name}")
        return _render_picker(
            name=name,
            value=value,
            attrs=attrs,
            field_id=field_id,
            with_time=True,
            fmt_value_fn=self.format_value,
        )


# ---------------------------------------------------------------------------
# Виджет для DateField (только дата, без времени)
# ---------------------------------------------------------------------------
class ModernDatePickerWidget(forms.DateInput):
    """
    Красивый пикер только даты для полей DateField (start_date, end_date, valid_from и т.д.).
    • Автозаполняет пустые поля сегодняшней датой (только для создания).
    • Live-превью на русском: «21 ноября 2026 г. (Пятница)».
    • Быстрые пресеты: Сегодня, Вчера, Завтра, ±1 день, ±1 неделя, ±1 месяц.
    Параметр allow_blank=True (default False) — не автозаполнять пустое поле.
    """
    input_type = "date"

    def __init__(self, attrs=None, format="%Y-%m-%d", allow_blank=False):
        super().__init__(attrs=attrs or {}, format=format)
        self.allow_blank = allow_blank

    def format_value(self, value):
        if value is None:
            return ""
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        return str(value)

    def render(self, name, value, attrs=None, renderer=None):
        field_id = (attrs or {}).get("id", f"id_{name}")
        # Если поле необязательное/end_date — не автозаполнять
        from django.utils.safestring import mark_safe as _ms
        html = _render_picker(
            name=name,
            value=value,
            attrs=attrs,
            field_id=field_id,
            with_time=False,
            fmt_value_fn=self.format_value,
        )
        if self.allow_blank:
            # Перебиваем JS-автозаполнение для необязательных полей
            html = html.replace(
                "if (!inp.value) {\n        mdpAutoFill(fid, wt);\n    }",
                "// allow_blank: auto-fill disabled for optional date"
            )
        return html
