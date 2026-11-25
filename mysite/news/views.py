from collections import defaultdict
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import F, Q
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from main.models import SiteSettings
from .models import News, RUSSIAN_MONTHS_NOMINATIVE, RUSSIAN_MONTHS_GENITIVE, RUSSIAN_WEEKDAYS
from .forms import NewsForm


def news_list_view(request):
    """
    Основной список новостей с многоуровневой группировкой по дате публикации:
    Год -> Месяц -> День (взято за основу).
    Поддерживает фильтрацию по году, месяцу, дню, точной дате, типу новости и поисковому запросу.
    """
    settings = SiteSettings.get_solo()
    base_qs = News.objects.filter(is_published=True)

    # Параметры фильтрации из GET
    query = request.GET.get("q", "").strip()
    selected_year = request.GET.get("year", "").strip()
    selected_month = request.GET.get("month", "").strip()
    selected_day = request.GET.get("day", "").strip()
    selected_date = request.GET.get("date", "").strip()
    selected_type = request.GET.get("type", "").strip()

    qs = base_qs

    if query:
        words = [w.lower() for w in query.split() if w]
        q_obj = Q()
        for w in words:
            q_obj &= (Q(title__icontains=w) | Q(snippet__icontains=w) | Q(content__icontains=w))
        qs = qs.filter(q_obj)

    if selected_type and selected_type != "all":
        qs = qs.filter(news_type=selected_type)

    if selected_date:
        try:
            # Формат YYYY-MM-DD
            parts = [int(p) for p in selected_date.split("-")]
            if len(parts) == 3:
                qs = qs.filter(
                    published_at__year=parts[0],
                    published_at__month=parts[1],
                    published_at__day=parts[2]
                )
        except (ValueError, TypeError):
            pass
    else:
        if selected_year and selected_year.isdigit():
            qs = qs.filter(published_at__year=int(selected_year))
        if selected_month and selected_month.isdigit():
            qs = qs.filter(published_at__month=int(selected_month))
        if selected_day and selected_day.isdigit():
            qs = qs.filter(published_at__day=int(selected_day))

    ordered_qs = qs.order_by("-published_at", "-id")
    paginator = Paginator(ordered_qs, 9)
    page_obj = paginator.get_page(request.GET.get("page"))
    elided_page_range = list(paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1))
    news_list = list(page_obj.object_list)

    query_params = request.GET.copy()
    query_params.pop("page", None)
    pagination_query = query_params.urlencode()

    # Сбор всех доступных годов и месяцев для быстрых фильтров на базе общего списка
    all_published_news = list(base_qs.order_by("-published_at"))
    years_counter = defaultdict(int)
    months_counter = defaultdict(int)

    for item in all_published_news:
        if item.published_at:
            y = item.published_at.year
            m = item.published_at.month
            years_counter[y] += 1
            months_counter[(y, m)] += 1

    available_years = [
        {"year": y, "count": years_counter[y], "is_active": str(y) == selected_year}
        for y in sorted(years_counter.keys(), reverse=True)
    ]

    available_months = []
    # Если выбран конкретный год, показываем месяцы для него, иначе для последнего активного года
    filter_year_int = int(selected_year) if (selected_year and selected_year.isdigit()) else (available_years[0]["year"] if available_years else timezone.now().year)
    for m in range(1, 13):
        cnt = months_counter.get((filter_year_int, m), 0)
        if cnt > 0 or str(filter_year_int) == selected_year:
            available_months.append({
                "month_num": m,
                "month_name": RUSSIAN_MONTHS_NOMINATIVE[m],
                "year": filter_year_int,
                "count": cnt,
                "is_active": str(m) == selected_month and str(filter_year_int) == selected_year,
            })

    # -------------------------------------------------------------
    # СТРУКТУРИРОВАННАЯ ГРУППИРОВКА: ГОД -> МЕСЯЦ -> ДЕНЬ
    # -------------------------------------------------------------
    grouped_years = []
    # Вспомогательные структуры
    # year -> month -> day -> [items]
    hierarchy = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for item in news_list:
        if not item.published_at:
            continue
        y = item.published_at.year
        m = item.published_at.month
        d = item.published_at.day
        hierarchy[y][m][d].append(item)

    for y in sorted(hierarchy.keys(), reverse=True):
        year_item = {
            "year": y,
            "year_title": f"{y} год",
            "count": sum(len(items) for m_dict in hierarchy[y].values() for items in m_dict.values()),
            "months": [],
        }
        for m in sorted(hierarchy[y].keys(), reverse=True):
            month_name = RUSSIAN_MONTHS_NOMINATIVE[m]
            month_item = {
                "month_num": m,
                "month_name": f"{month_name} {y}",
                "month_short": month_name,
                "count": sum(len(items) for items in hierarchy[y][m].values()),
                "days": [],
            }
            for d in sorted(hierarchy[y][m].keys(), reverse=True):
                items = hierarchy[y][m][d]
                first_date = items[0].published_at
                weekday = RUSSIAN_WEEKDAYS[first_date.weekday()]
                day_title = f"{d} {RUSSIAN_MONTHS_GENITIVE[m]} {y} г."
                day_item = {
                    "day_num": d,
                    "date_key": first_date.strftime("%Y-%m-%d"),
                    "day_title": day_title,
                    "weekday": weekday,
                    "count": len(items),
                    "items": items,
                }
                month_item["days"].append(day_item)
            year_item["months"].append(month_item)
        grouped_years.append(year_item)

    context = {
        "page_title": "Новости и события сыроварни «Сибсыр»",
        "page_description": "Все актуальные новости, поступления новинок сыров, акции и события производства ТМ «Сибсыр».",
        "page_keywords": "новости сибсыр, новинки сыра, акции на сыр омск, события сыроварни",
        "site_settings": settings,
        "brand_name": settings.brand_name,
        "brand_short_name": settings.brand_short_name,
        "news_list": news_list,
        "page_obj": page_obj,
        "elided_page_range": elided_page_range,
        "pagination_query": pagination_query,
        "grouped_years": grouped_years,
        "total_count": paginator.count,
        "all_count": base_qs.count(),
        "query": query,
        "selected_year": selected_year,
        "selected_month": selected_month,
        "selected_day": selected_day,
        "selected_date": selected_date,
        "selected_type": selected_type,
        "available_years": available_years,
        "available_months": available_months,
        "type_choices": News.TYPE_CHOICES,
    }
    return render(request, "news/news_list.html", context)


def news_detail_view(request, slug):
    """
    Детальная страница новости с полным текстом, иллюстрацией,
    датой публикации (день, месяц, год, время), блоком похожих новостей и ссылкой на правку.
    """
    settings = SiteSettings.get_solo()
    news = get_object_or_404(News, slug=slug, is_published=True)

    # Безопасный инкремент просмотров без вызова post_save сигналов
    News.objects.filter(pk=news.pk).update(views_count=F("views_count") + 1)
    news.views_count += 1

    # Другие новости этого же месяца или года для рекомендаций
    related_news = (
        News.objects.filter(is_published=True)
        .exclude(pk=news.pk)
        .filter(
            Q(published_at__year=news.published_at.year, published_at__month=news.published_at.month)
            | Q(news_type=news.news_type)
        )
        .order_by("-published_at")[:4]
    )

    canonical_url = request.build_absolute_uri(news.get_absolute_url())
    attached_products = list(news.related_products.filter(is_active=True).select_related("category"))
    attached_categories = list(news.related_categories.filter(is_active=True))

    context = {
        "page_title": news.meta_title or f"{news.title} — Новости сыроварни «Сибсыр»",
        "page_description": news.meta_description or news.snippet,
        "page_keywords": news.meta_keywords,
        "canonical_url": canonical_url,
        "site_settings": settings,
        "brand_name": settings.brand_name,
        "brand_short_name": settings.brand_short_name,
        "news": news,
        "related_news": related_news,
        "attached_products": attached_products,
        "attached_categories": attached_categories,
    }
    return render(request, "news/news_detail.html", context)


@staff_member_required
def news_create_view(request):
    """Создание новости через форму с интерактивным выбором даты."""
    settings = SiteSettings.get_solo()
    if request.method == "POST":
        form = NewsForm(request.POST, request.FILES)
        if form.is_valid():
            news = form.save()
            messages.success(request, f"Новость «{news.title}» успешно создана!")
            return redirect(news.get_absolute_url())
    else:
        form = NewsForm(initial={"published_at": timezone.now(), "is_published": True})

    context = {
        "page_title": "Добавление новости — Панель управления «Сибсыр»",
        "site_settings": settings,
        "form": form,
        "is_create": True,
    }
    return render(request, "news/news_form.html", context)


@staff_member_required
def news_edit_view(request, slug):
    """
    Редактирование новости через форму.
    При сохранении срабатывает сигнал post_save, который автоматически
    добавляет новость об этом редактировании (как требует ТЗ).
    """
    settings = SiteSettings.get_solo()
    news = get_object_or_404(News, slug=slug)

    if request.method == "POST":
        form = NewsForm(request.POST, request.FILES, instance=news)
        if form.is_valid():
            saved_news = form.save()
            messages.success(
                request,
                f"Новость «{saved_news.title}» сохранена. Создана автоматическая публикация об обновлении!"
            )
            return redirect(saved_news.get_absolute_url())
    else:
        form = NewsForm(instance=news)

    context = {
        "page_title": f"Редактирование новости: {news.title}",
        "site_settings": settings,
        "news": news,
        "form": form,
        "is_create": False,
    }
    return render(request, "news/news_form.html", context)
