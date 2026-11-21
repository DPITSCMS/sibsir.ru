"""
Модуль экспорта и импорта прайс-листа каталога продукции ТМ «Сибсыр».
Формат: Excel (.xlsx, чистый OpenXML без сторонних библиотек) и CSV (UTF-8).
Поддерживает свободное редактирование наименований, цен и условий на всех устройствах (Windows, macOS, iOS, Android, Linux).
Файл полностью открыт для редактирования в любых табличных редакторах (Excel, LibreOffice, МойОфис, Google Таблицы).
"""

import io
import re
import csv
import zipfile
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

from django.utils import timezone
from django.db import transaction
from django.utils.text import slugify

logger = logging.getLogger(__name__)


def _col_letter(n: int) -> str:
    """Преобразует порядковый номер столбца (1-based) в букву Excel (1 -> A, 27 -> AA)."""
    string = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        string = chr(65 + remainder) + string
    return string


def _clean_price_value(val) -> int:
    """Извлекает целое число цены в рублях из числа или строки (например: '450 ₽' -> 450)."""
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return max(0, int(round(val)))
    
    val_str = str(val).strip().lower()
    if not val_str or "запрос" in val_str:
        return 0
    
    # Заменяем запятую на точку для разделителя дробей (если передано например 450,00)
    # Удаляем пробелы и неразрывные пробелы
    val_clean = val_str.replace("\xa0", "").replace(" ", "").replace("₽", "").replace("руб", "").replace("р.", "").replace("р", "")
    
    # Ищем числа
    match = re.search(r"(\d+(?:[.,]\d+)?)", val_clean)
    if match:
        try:
            num_float = float(match.group(1).replace(",", "."))
            return max(0, int(round(num_float)))
        except (ValueError, TypeError):
            pass
    return 0


def _clean_qty_value(val) -> str:
    """Нормализует значение минимального объема для опта."""
    if val is None:
        return ""
    val_str = str(val).strip()
    if not val_str:
        return ""
    # Если передано просто число, например '10', приводим к понятному 'от 10 шт.'
    if val_str.isdigit():
        return f"от {val_str} шт."
    return val_str


def export_catalog_prices_xlsx(queryset=None) -> tuple[bytes, str]:
    """
    Генерирует Excel (.xlsx) с прайс-листом каталога продукции для свободного редактирования цен и наименований.
    
    Колонки:
    1. Наименование товара (редактируемое)
    2. Цена для обычных пользователей, ₽ (редактируемое)
    3. Цена оптом, ₽ (редактируемое)
    4. Количество для покупки оптом (редактируемое)
    5. ID товара (служебный код для точной привязки)
    
    Возвращает (bytes, filename).
    """
    from shop.models import Product

    if queryset is None:
        queryset = Product.objects.all().select_related("category").order_by("category__order", "order", "title")
    else:
        # Не применяем повторный order_by, если передан срез (slice)
        if getattr(queryset, "query", None) and queryset.query.low_mark == 0 and queryset.query.high_mark is None:
            queryset = queryset.select_related("category").order_by("category__order", "order", "title")

    today = timezone.localtime(timezone.now())
    date_str = today.strftime("%d.%m.%Y %H:%M")
    filename = f"Sibsir_Catalog_Prices_{today.strftime('%Y-%m-%d')}.xlsx"

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    wb_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Прайс-лист товаров" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

    # Стили:
    # Шрифты:
    # 0: Regular Calibri 10pt #0F172A
    # 1: Bold Calibri 13pt #1E293B (Заголовок листа)
    # 2: Bold Calibri 10pt #FFFFFF (Заголовки колонок)
    # 3: Regular Calibri 9pt #64748B (Инструкция / подзаголовок)
    # 4: Bold Calibri 10pt #15803D (Оптовая цена)
    # 5: Bold Calibri 10pt #0F172A (Розничная цена)
    # 6: Regular Calibri 10pt #475569 (Служебный ID)
    #
    # Заливки:
    # 0: none
    # 1: gray125
    # 2: #FF8400 (Оранжевый Сибсыр - заголовки)
    # 3: #F8FAFC (Светло-серый фон)
    # 4: #FFFFFF (Белый для редактируемых колонок)
    # 5: #F0FDF4 (Светло-зеленый для оптовых цен)
    # 6: #FEF3C7 (Предупреждение / памятка)
    #
    # Границы:
    # 0: none
    # 1: thin #CBD5E1 (все стороны)
    #
    # CellXfs:
    # xfId 0: default
    # xfId 1: Title bold
    # xfId 2: Subtitle/Instruction
    # xfId 3: Header cell
    # xfId 4: Product title (EDITABLE, white background, left align)
    # xfId 5: Editable regular price (white background, right align)
    # xfId 6: Editable wholesale price (light-green background, right align, bold green text)
    # xfId 7: Editable min quantity (white background, left align)
    # xfId 8: Product ID (subtle gray background, center align)
    # xfId 9: Instruction banner
    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="7">
    <font><name val="Calibri"/><sz val="10"/><color rgb="FF0F172A"/></font>
    <font><b/><name val="Calibri"/><sz val="13"/><color rgb="FF1E293B"/></font>
    <font><b/><name val="Calibri"/><sz val="10"/><color rgb="FFFFFFFF"/></font>
    <font><name val="Calibri"/><sz val="9"/><color rgb="FF64748B"/></font>
    <font><b/><name val="Calibri"/><sz val="10"/><color rgb="FF15803D"/></font>
    <font><b/><name val="Calibri"/><sz val="10"/><color rgb="FF0F172A"/></font>
    <font><name val="Calibri"/><sz val="10"/><color rgb="FF475569"/></font>
  </fonts>
  <fills count="7">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFF8400"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF8FAFC"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFFFFFF"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF0FDF4"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFEF3C7"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFCBD5E1"/></left>
      <right style="thin"><color rgb="FFCBD5E1"/></right>
      <top style="thin"><color rgb="FFCBD5E1"/></top>
      <bottom style="thin"><color rgb="FFCBD5E1"/></bottom>
    </border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="10">
    <!-- 0: default -->
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <!-- 1: title -->
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <!-- 2: subtitle -->
    <xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <!-- 3: header cell -->
    <xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <!-- 4: Product title (EDITABLE, white background, left align) -->
    <xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>
    <!-- 5: Regular price (EDITABLE, white background, right align) -->
    <xf numFmtId="0" fontId="5" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
    <!-- 6: Wholesale price (EDITABLE, light-green background, right align, bold green text) -->
    <xf numFmtId="0" fontId="4" fillId="5" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
    <!-- 7: Wholesale min qty (EDITABLE, white background, left align) -->
    <xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>
    <!-- 8: Technical Product ID (subtle gray background, center align) -->
    <xf numFmtId="0" fontId="6" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <!-- 9: Instruction banner warning -->
    <xf numFmtId="0" fontId="0" fillId="6" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf>
  </cellXfs>
</styleSheet>"""

    def make_cell(coord: str, value, style_id: int = 0, is_numeric: bool = False):
        if is_numeric and value is not None and str(value).strip() != "":
            try:
                num = float(value)
                if num.is_integer():
                    return f'<c r="{coord}" s="{style_id}"><v>{int(num)}</v></c>'
                return f'<c r="{coord}" s="{style_id}"><v>{num}</v></c>'
            except (ValueError, TypeError):
                pass
        val_str = xml_escape(str(value) if value is not None else "")
        return f'<c r="{coord}" t="inlineStr" s="{style_id}"><is><t>{val_str}</t></is></c>'

    sheet_rows = []
    current_row = 1

    # Заголовок
    sheet_rows.append(f'<row r="{current_row}">')
    sheet_rows.append(make_cell(f"A{current_row}", "ТМ «СИБСЫР» — ПРАЙС-ЛИСТ КАТАЛОГА ПРОДУКЦИИ (РЕДАКТИРОВАНИЕ ЦЕН И ТОВАРОВ)", 1))
    sheet_rows.append('</row>')
    current_row += 1

    # Подзаголовок
    sheet_rows.append(f'<row r="{current_row}">')
    sheet_rows.append(make_cell(f"A{current_row}", f"Выгружен: {date_str} | Всего товаров: {queryset.count()} | Кодировка: UTF-8 (полностью открыт для редактирования на любых устройствах)", 2))
    sheet_rows.append('</row>')
    current_row += 1

    # Инструкция
    sheet_rows.append(f'<row r="{current_row}" ht="32" customHeight="1">')
    sheet_rows.append(make_cell(
        f"A{current_row}", 
        "💡 ПАМЯТКА: Файл полностью доступен для редактирования. Вы можете свободно изменять наименования товаров, розничные и оптовые цены, а также условия минимального опта. Столбец «ID товара» используется для точного сопоставления товара в базе данных при импорте.", 
        9
    ))
    sheet_rows.append('</row>')
    current_row += 2  # Пустая строка

    # Заголовки колонок
    headers = [
        ("Наименование товара", 46),
        ("Цена для обычных пользователей (₽)", 26),
        ("Цена оптом (₽)", 22),
        ("Количество для покупки оптом", 30),
        ("ID товара", 14),
    ]

    header_cells = []
    for col_idx, (h_title, _) in enumerate(headers, start=1):
        c_coord = f"{_col_letter(col_idx)}{current_row}"
        header_cells.append(make_cell(c_coord, h_title, 3))
    sheet_rows.append(f'<row r="{current_row}" ht="28" customHeight="1">{"".join(header_cells)}</row>')
    current_row += 1

    # Данные товаров
    for prod in queryset:
        retail_price = prod.price_numeric or 0
        wholesale_price = prod.wholesale_price_numeric or 0
        min_qty = prod.wholesale_min_qty or "от 10 шт."

        row_cells = [
            make_cell(f"A{current_row}", prod.title, 4),  # Редактируемое наименование
            make_cell(f"B{current_row}", retail_price, 5, is_numeric=True),  # Розничная цена
            make_cell(f"C{current_row}", wholesale_price, 6, is_numeric=True),  # Оптовая цена
            make_cell(f"D{current_row}", min_qty, 7),  # Минимальный объем
            make_cell(f"E{current_row}", prod.id, 8, is_numeric=True),  # ID товара
        ]
        sheet_rows.append(f'<row r="{current_row}">{"".join(row_cells)}</row>')
        current_row += 1

    # Ширина колонок
    cols_xml = []
    for col_idx, (_, w) in enumerate(headers, start=1):
        cols_xml.append(f'<col min="{col_idx}" max="{col_idx}" width="{w}" customWidth="1"/>')

    # Лист данных без блокировок и защиты — полностью открыт для редактирования
    worksheet = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <cols>
    {"".join(cols_xml)}
  </cols>
  <sheetData>
    {"".join(sheet_rows)}
  </sheetData>
</worksheet>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/styles.xml", styles)
        zf.writestr("xl/worksheets/sheet1.xml", worksheet.encode("utf-8"))

    return buf.getvalue(), filename


def generate_empty_price_template_xlsx() -> tuple[bytes, str]:
    """Генерирует пустой шаблон прайс-листа с примерами строк."""
    from shop.models import Product
    sample_qs = Product.objects.all().order_by("order", "id")[:5]
    if not sample_qs.exists():
        sample_qs = None
    return export_catalog_prices_xlsx(queryset=sample_qs)


def _parse_xlsx_sheet(file_bytes: bytes) -> list[list[str]]:
    """
    Парсит строки из файла .xlsx с помощью встроенных модулей zipfile и xml.etree.ElementTree.
    Поддерживает UTF-8, разделяемые строки (sharedStrings), строчные значения (inlineStr) и числа.
    Работает быстро и без внешних зависимостей.
    """
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        # 1. Читаем sharedStrings.xml (если есть)
        shared_strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            try:
                tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for elem in tree.iter():
                    if elem.tag.endswith("si"):
                        t_parts = [t.text for t in elem.iter() if t.tag.endswith("t") and t.text]
                        shared_strings.append("".join(t_parts))
            except Exception as e:
                logger.warning("Ошибка чтения sharedStrings.xml: %s", e)

        # 2. Находим первый лист данных
        sheet_path = None
        for name in z.namelist():
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                sheet_path = name
                break
        if not sheet_path:
            raise ValueError("В архиве Excel не обнаружен файл листа данных (sheet*.xml).")

        tree = ET.fromstring(z.read(sheet_path))
        rows_data = []

        def col_letters_to_index(col_str: str) -> int:
            idx = 0
            for char in col_str.upper():
                if 'A' <= char <= 'Z':
                    idx = idx * 26 + (ord(char) - ord('A') + 1)
            return idx - 1  # 0-based

        for row_elem in tree.iter():
            if row_elem.tag.endswith("row"):
                cell_dict = {}
                max_col_idx = -1
                for c in row_elem:
                    if c.tag.endswith("c"):
                        r_coord = c.attrib.get("r", "")
                        col_letters = "".join(filter(str.isalpha, r_coord))
                        if not col_letters:
                            continue
                        col_idx = col_letters_to_index(col_letters)
                        max_col_idx = max(max_col_idx, col_idx)

                        t_type = c.attrib.get("t", "")
                        val = ""
                        if t_type == "inlineStr":
                            for is_el in c.iter():
                                if is_el.tag.endswith("t") and is_el.text:
                                    val += is_el.text
                        elif t_type == "s":
                            v_el = next((child for child in c if child.tag.endswith("v")), None)
                            if v_el is not None and v_el.text:
                                try:
                                    s_idx = int(v_el.text)
                                    if 0 <= s_idx < len(shared_strings):
                                        val = shared_strings[s_idx]
                                except (ValueError, IndexError):
                                    pass
                        else:
                            v_el = next((child for child in c if child.tag.endswith("v")), None)
                            if v_el is not None and v_el.text is not None:
                                val = v_el.text

                        cell_dict[col_idx] = val.strip()

                if max_col_idx >= 0:
                    row_list = [cell_dict.get(i, "") for i in range(max_col_idx + 1)]
                    if any(bool(item) for item in row_list):
                        rows_data.append(row_list)

        return rows_data


def _parse_csv_file(file_bytes: bytes) -> list[list[str]]:
    """Парсит CSV файл с автоматическим определением кодировки (UTF-8, UTF-8-SIG, CP1251)."""
    text = None
    for enc in ("utf-8-sig", "utf-8", "windows-1251", "cp1251", "latin-1"):
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        raise ValueError("Не удалось распознать кодировку текстового файла (рекомендуется UTF-8).")

    # Определяем разделитель (; или , или \t)
    sample = text[:2048]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    if sample.count("\t") > max(sample.count(";"), sample.count(",")):
        delimiter = "\t"

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[col.strip() for col in row] for row in reader if any(col.strip() for col in row)]


def read_price_list_file(file_bytes: bytes, filename: str = "") -> list[dict]:
    """
    Универсальное чтение загруженного файла прайс-листа (.xlsx или .csv).
    Определяет колонки таблицы по заголовкам:
    - Наименование товара (обязательно)
    - Цена для обычных пользователей (розница)
    - Цена оптом
    - Количество для покупки оптом
    - ID товара (опционально, если есть)
    
    Возвращает список словарей:
    [
        {
            "row_num": 6,
            "title": "Сыр Российский",
            "retail_price_raw": "450",
            "wholesale_price_raw": "340",
            "wholesale_min_qty_raw": "от 10 шт.",
            "product_id": 12 (или None)
        }, ...
    ]
    """
    is_xlsx = filename.lower().endswith(".xlsx") or file_bytes.startswith(b"PK\x03\x04")
    if is_xlsx:
        rows = _parse_xlsx_sheet(file_bytes)
    else:
        rows = _parse_csv_file(file_bytes)

    if not rows:
        raise ValueError("Загруженный файл пуст или не содержит строк с данными.")

    # Поиск строки заголовков таблицы
    header_row_idx = None
    col_mapping = {}

    for idx, row in enumerate(rows):
        # Строка заголовка таблицы обязательно содержит несколько непустых ячеек (минимум 2)
        non_empty = [str(c).strip() for c in row if str(c).strip()]
        if len(non_empty) < 2:
            continue

        row_lower = [str(c).lower().strip() for c in row]
        # Проверяем, есть ли в строке ключевые слова шапки
        has_title = any("наименован" in c or "имя товар" in c or c in ("товар", "продукт") for c in row_lower)
        has_price = any("цена" in c or "розниц" in c or "стоимость" in c for c in row_lower)
        
        if has_title and has_price:
            header_row_idx = idx
            for c_idx, col_name in enumerate(row_lower):
                if ("наименован" in col_name or "имя товар" in col_name or col_name in ("товар", "продукт")) and "title" not in col_mapping:
                    col_mapping["title"] = c_idx
                elif ("обычн" in col_name or "розниц" in col_name or "для обычных" in col_name) and "retail" not in col_mapping:
                    col_mapping["retail"] = c_idx
                elif "опт" in col_name and "колич" not in col_name and "объем" not in col_name and "wholesale" not in col_mapping:
                    col_mapping["wholesale"] = c_idx
                elif ("колич" in col_name or "объем" in col_name or "мин" in col_name or "заказ" in col_name) and "qty" not in col_mapping:
                    col_mapping["qty"] = c_idx
                elif ("id" in col_name or "код" in col_name) and "id" not in col_mapping:
                    col_mapping["id"] = c_idx
            break

    # Если явных заголовков не найдено, предполагаем стандартную очередность колонок
    if header_row_idx is None:
        header_row_idx = -1
        # 4 колонки: Title, Retail, Wholesale, Qty
        col_mapping = {
            "title": 0,
            "retail": 1,
            "wholesale": 2,
            "qty": 3,
        }
        # Если есть 5-я колонка, возможно это ID
        if len(rows[0]) > 4:
            col_mapping["id"] = 4

    # Дополнительная проверка, если розничная цена не определилась, но колонка с "цена" есть
    if "retail" not in col_mapping:
        for c_idx, col_name in enumerate(rows[header_row_idx] if header_row_idx >= 0 else []):
            cl = str(col_name).lower()
            if "цена" in cl and c_idx != col_mapping.get("wholesale"):
                col_mapping["retail"] = c_idx
                break

    if "title" not in col_mapping:
        col_mapping["title"] = 0
    if "retail" not in col_mapping:
        col_mapping["retail"] = 1 if len(rows[0]) > 1 else None
    if "wholesale" not in col_mapping:
        col_mapping["wholesale"] = 2 if len(rows[0]) > 2 else None
    if "qty" not in col_mapping:
        col_mapping["qty"] = 3 if len(rows[0]) > 3 else None

    parsed_items = []
    for r_idx in range(header_row_idx + 1, len(rows)):
        row = rows[r_idx]
        if not row:
            continue

        title_idx = col_mapping.get("title")
        raw_title = str(row[title_idx]).strip() if title_idx is not None and title_idx < len(row) else ""

        # Пропускаем служебные строки (ИТОГО, УСЛОВИЯ, шапку)
        lower_t = raw_title.lower()
        if (
            not raw_title 
            or lower_t.startswith("итого") 
            or lower_t.startswith("условия") 
            or "внимание" in lower_t
            or lower_t.startswith("наименование") 
            or lower_t.startswith("имя товар")
        ):
            continue

        retail_idx = col_mapping.get("retail")
        raw_retail = str(row[retail_idx]).strip() if retail_idx is not None and retail_idx < len(row) else ""

        ws_idx = col_mapping.get("wholesale")
        raw_ws = str(row[ws_idx]).strip() if ws_idx is not None and ws_idx < len(row) else ""

        qty_idx = col_mapping.get("qty")
        raw_qty = str(row[qty_idx]).strip() if qty_idx is not None and qty_idx < len(row) else ""

        id_idx = col_mapping.get("id")
        raw_id = str(row[id_idx]).strip() if id_idx is not None and id_idx < len(row) else ""

        prod_id = None
        if raw_id and raw_id.isdigit():
            prod_id = int(raw_id)

        parsed_items.append({
            "row_num": r_idx + 1,
            "title": raw_title,
            "retail_price_raw": raw_retail,
            "wholesale_price_raw": raw_ws,
            "wholesale_min_qty_raw": raw_qty,
            "product_id": prod_id,
        })

    return parsed_items


def import_catalog_prices(items: list[dict], dry_run: bool = False) -> dict:
    """
    Применяет обновленные данные (цены, условия и наименования) к товарам каталога.
    
    Правила:
    - Товар ищется по product_id (если указан), либо по точному/нормализованному наименованию.
    - При наличии product_id разрешено редактирование наименования товара (title).
    - Новые строки без ID и с новым наименованием создаются как новые товары в каталоге.
    - Обновляются: title, price_numeric, price_display, wholesale_price_numeric, wholesale_price_display, wholesale_min_qty.
    - При dry_run=True база данных не модифицируется, формируется подробный отчет.
    
    Возвращает словарь с подробными результатами и статистикой.
    """
    from shop.models import Category, Product

    results = {
        "success": True,
        "dry_run": dry_run,
        "total_rows": len(items),
        "updated_count": 0,
        "unchanged_count": 0,
        "error_count": 0,
        "items": [],
    }

    all_products = list(Product.objects.all())
    id_map = {p.id: p for p in all_products}
    title_map = {p.title.strip().lower(): p for p in all_products}
    default_cat = Category.objects.filter(is_active=True).first()

    with transaction.atomic():
        for item in items:
            raw_title = item["title"]
            clean_title = raw_title.strip()
            title_key = clean_title.lower()
            prod_id = item.get("product_id")

            # 1. Поиск существующего товара
            product = None
            if prod_id and prod_id in id_map:
                product = id_map[prod_id]
            elif title_key in title_map:
                product = title_map[title_key]
            else:
                relaxed_key = re.sub(r'["«»„“\s]', '', title_key)
                for existing_key, p_obj in title_map.items():
                    if re.sub(r'["«»„“\s]', '', existing_key) == relaxed_key:
                        product = p_obj
                        break

            # 2. Очистка и получение новых значений цен
            new_retail_num = _clean_price_value(item["retail_price_raw"])
            new_wholesale_num = _clean_price_value(item["wholesale_price_raw"])
            new_min_qty = _clean_qty_value(item["wholesale_min_qty_raw"])

            # 3. Обработка случая, когда товар не найден
            if not product:
                # Если указан конкретный числовой ID, но такого товара в базе нет — ошибка
                if prod_id:
                    results["error_count"] += 1
                    results["items"].append({
                        "row_num": item["row_num"],
                        "title": raw_title,
                        "status": "error",
                        "status_label": "Товар не найден",
                        "message": f"Товар с указанным ID {prod_id} отсутствует в базе данных.",
                        "old_retail": "—",
                        "new_retail": item["retail_price_raw"],
                        "old_wholesale": "—",
                        "new_wholesale": item["wholesale_price_raw"],
                        "old_qty": "—",
                        "new_qty": item["wholesale_min_qty_raw"],
                    })
                    continue

                # Если ID нет и наименование не пустое — создаем новый товар
                if clean_title:
                    from news.models import transliterate_to_slug
                    base_slug = transliterate_to_slug(clean_title) or f"prod-{int(timezone.now().timestamp())}"
                    slug = base_slug[:180]
                    counter = 1
                    while Product.objects.filter(slug=slug).exists():
                        slug = f"{base_slug[:170]}-{counter}"
                        counter += 1

                    new_retail_display = f"{new_retail_num} ₽" if new_retail_num > 0 else "По запросу"
                    new_wholesale_display = f"{new_wholesale_num} ₽" if new_wholesale_num > 0 else "По запросу"
                    qty_to_save = new_min_qty or "от 10 шт."

                    created_id = None
                    if not dry_run:
                        new_p = Product.objects.create(
                            category=default_cat,
                            title=clean_title,
                            slug=slug,
                            price_numeric=new_retail_num,
                            price_display=new_retail_display,
                            wholesale_price_numeric=new_wholesale_num,
                            wholesale_price_display=new_wholesale_display,
                            wholesale_min_qty=qty_to_save,
                            is_active=True,
                        )
                        created_id = new_p.id
                        id_map[new_p.id] = new_p
                        title_map[clean_title.lower()] = new_p

                    results["updated_count"] += 1
                    results["items"].append({
                        "row_num": item["row_num"],
                        "product_id": created_id or "новый",
                        "title": clean_title,
                        "status": "created",
                        "status_label": "Создан новый товар" if not dry_run else "Будет создан",
                        "message": f"Новый товар добавлен в каталог{' (категория: ' + default_cat.name + ')' if default_cat else ''}",
                        "old_retail": "—",
                        "new_retail": new_retail_display,
                        "old_wholesale": "—",
                        "new_wholesale": new_wholesale_display,
                        "old_qty": "—",
                        "new_qty": qty_to_save,
                    })
                    continue
                else:
                    results["error_count"] += 1
                    results["items"].append({
                        "row_num": item["row_num"],
                        "title": "—",
                        "status": "error",
                        "status_label": "Пустая строка",
                        "message": "В строке не указано наименование товара.",
                        "old_retail": "—",
                        "new_retail": item["retail_price_raw"],
                        "old_wholesale": "—",
                        "new_wholesale": item["wholesale_price_raw"],
                        "old_qty": "—",
                        "new_qty": item["wholesale_min_qty_raw"],
                    })
                    continue

            # 4. Товар найден — проверка изменений
            if not new_min_qty:
                new_min_qty = product.wholesale_min_qty or "от 10 шт."

            old_title = product.title
            old_retail_num = product.price_numeric
            old_wholesale_num = product.wholesale_price_numeric
            old_min_qty = product.wholesale_min_qty

            title_changed = bool(clean_title and clean_title != old_title)
            retail_changed = (new_retail_num != old_retail_num)
            wholesale_changed = (new_wholesale_num != old_wholesale_num)
            qty_changed = (new_min_qty != old_min_qty)

            has_changes = title_changed or retail_changed or wholesale_changed or qty_changed

            if has_changes:
                new_retail_display = f"{new_retail_num} ₽" if new_retail_num > 0 else "По запросу"
                new_wholesale_display = f"{new_wholesale_num} ₽" if new_wholesale_num > 0 else "По запросу"

                update_fields = [
                    "price_numeric", 
                    "price_display", 
                    "wholesale_price_numeric", 
                    "wholesale_price_display", 
                    "wholesale_min_qty"
                ]

                if title_changed:
                    product.title = clean_title
                    update_fields.append("title")

                product.price_numeric = new_retail_num
                product.price_display = new_retail_display
                product.wholesale_price_numeric = new_wholesale_num
                product.wholesale_price_display = new_wholesale_display
                product.wholesale_min_qty = new_min_qty

                if not dry_run:
                    product.save(update_fields=update_fields)

                change_desc_parts = []
                if title_changed:
                    change_desc_parts.append(f'наименование: «{old_title}» ➔ «{clean_title}»')
                if retail_changed:
                    change_desc_parts.append("розничная цена")
                if wholesale_changed:
                    change_desc_parts.append("оптовая цена")
                if qty_changed:
                    change_desc_parts.append("объем опта")

                msg = "Обновлено: " + ", ".join(change_desc_parts) if change_desc_parts else "Данные обновлены"
                if dry_run:
                    msg = "Будет обновлено: " + ", ".join(change_desc_parts)

                results["updated_count"] += 1
                results["items"].append({
                    "row_num": item["row_num"],
                    "product_id": product.id,
                    "title": product.title,
                    "status": "updated",
                    "status_label": "Обновлен" if not dry_run else "Будет обновлен",
                    "message": msg,
                    "old_retail": f"{old_retail_num} ₽" if old_retail_num else "По запросу",
                    "new_retail": f"{new_retail_num} ₽" if new_retail_num else "По запросу",
                    "old_wholesale": f"{old_wholesale_num} ₽" if old_wholesale_num else "По запросу",
                    "new_wholesale": f"{new_wholesale_num} ₽" if new_wholesale_num else "По запросу",
                    "old_qty": old_min_qty or "—",
                    "new_qty": new_min_qty,
                })
            else:
                results["unchanged_count"] += 1
                results["items"].append({
                    "row_num": item["row_num"],
                    "product_id": product.id,
                    "title": product.title,
                    "status": "unchanged",
                    "status_label": "Без изменений",
                    "message": "Значения совпадают с базой данных",
                    "old_retail": f"{old_retail_num} ₽" if old_retail_num else "По запросу",
                    "new_retail": f"{new_retail_num} ₽" if new_retail_num else "По запросу",
                    "old_wholesale": f"{old_wholesale_num} ₽" if old_wholesale_num else "По запросу",
                    "new_wholesale": f"{new_wholesale_num} ₽" if new_wholesale_num else "По запросу",
                    "old_qty": old_min_qty or "—",
                    "new_qty": new_min_qty,
                })

        if dry_run:
            transaction.set_rollback(True)

    return results
