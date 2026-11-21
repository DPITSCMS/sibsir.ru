import os
from pathlib import Path
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseRedirect, Http404, FileResponse, JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET

from .backup_manager import (
    create_backup,
    restore_backup,
    inspect_backup,
    cleanup_old_backups,
    list_existing_backups,
    get_system_stats,
    get_backup_dir,
    get_backup_manifest,
    BACKUP_SECTIONS,
)


def _check_superuser_permission(request):
    """Проверяет права суперпользователя для критических операций с бэкапами."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, "Доступ к резервному копированию и восстановлению разрешен только суперпользователям.")
        return False
    return True


@staff_member_required
def admin_backup_dashboard(request):
    """Главная страница управления резервными копиями в админ-панели."""
    if not _check_superuser_permission(request):
        return redirect("admin:index")

    stats = get_system_stats()
    backups = list_existing_backups()

    regular_backups = [b for b in backups if not b.get("is_safety_point")]
    safety_backups = [b for b in backups if b.get("is_safety_point")]

    context = {
        "title": "Резервное копирование и восстановление",
        "system_stats": stats,
        "backups": backups,
        "regular_backups": regular_backups,
        "safety_backups": safety_backups,
        "sections": BACKUP_SECTIONS,
        "backup_dir": str(get_backup_dir()),
        "has_permission": True,
    }
    return render(request, "admin/main/backup_dashboard.html", context)


@staff_member_required
@require_POST
def admin_backup_create(request):
    """Создание резервной копии через админку."""
    if not _check_superuser_permission(request):
        return redirect("admin:index")

    backup_type = request.POST.get("backup_type", "custom")
    download_immediately = request.POST.get("download_now") == "1"
    description = request.POST.get("description", "").strip()

    if backup_type == "quick_db":
        # Мгновенный бэкап: все секции, только БД
        sections = list(BACKUP_SECTIONS.keys())
        include_media = False
        if not description:
            description = "Быстрый дамп базы данных (без медиа)"
    elif backup_type == "full":
        # Полный бэкап: все секции + медиа
        sections = list(BACKUP_SECTIONS.keys())
        include_media = True
        if not description:
            description = "Полный бэкап (база данных + фотографии)"
    else:
        # Выборочный бэкап
        sections = request.POST.getlist("sections")
        if not sections:
            sections = list(BACKUP_SECTIONS.keys())
        include_media = request.POST.get("include_media") == "1"

    try:
        res = create_backup(
            sections=sections,
            include_media=include_media,
            description=description,
        )

        archive_path = Path(res["archive_path"])

        if download_immediately and archive_path.exists():
            return FileResponse(
                open(archive_path, "rb"),
                as_attachment=True,
                filename=res["archive_filename"],
            )

        messages.success(
            request,
            f"Резервная копия «{res['archive_filename']}» успешно создана за {res.get('duration_seconds', 0)}с! "
            f"Размер: {res['archive_size_mb']} MB, записей в БД: {res['total_db_records']}, "
            f"медиафайлов: {res['media_files_count']} ({res['media_total_mb']} MB). "
            f"Контрольная сумма SHA-256: {res.get('sha256', '')[:12]}..."
        )
    except Exception as e:
        messages.error(request, f"Ошибка при создании резервной копии: {e}")

    return redirect("main:admin_backup_dashboard")


@staff_member_required
@require_GET
def admin_backup_inspect(request, filename):
    """Инспекция содержимого архива перед восстановлением (JSON API или страница)."""
    if not _check_superuser_permission(request):
        return JsonResponse({"valid": False, "error": "Доступ запрещен"}, status=403)

    safe_filename = os.path.basename(filename)
    if not safe_filename.endswith(".zip"):
        return JsonResponse({"valid": False, "error": "Недопустимый формат файла"}, status=400)

    file_path = get_backup_dir() / safe_filename
    if not file_path.exists():
        return JsonResponse({"valid": False, "error": "Архив не найден на сервере"}, status=404)

    try:
        report = inspect_backup(file_path)
        return JsonResponse(report)
    except Exception as e:
        return JsonResponse({"valid": False, "error": str(e)}, status=500)


@staff_member_required
def admin_backup_download(request, filename):
    """Скачивание архива резервной копии."""
    if not _check_superuser_permission(request):
        return redirect("admin:index")

    safe_filename = os.path.basename(filename)
    if not safe_filename.endswith(".zip"):
        raise Http404("Недопустимый формат файла")

    file_path = get_backup_dir() / safe_filename
    if not file_path.exists():
        raise Http404("Файл резервной копии не найден")

    return FileResponse(
        open(file_path, "rb"),
        as_attachment=True,
        filename=safe_filename,
    )


@staff_member_required
@require_POST
def admin_backup_restore(request):
    """Восстановление данных и картинок из архива."""
    if not _check_superuser_permission(request):
        return redirect("admin:index")

    server_filename = request.POST.get("server_filename", "").strip()
    uploaded_file = request.FILES.get("backup_file")
    mode = request.POST.get("mode", "clean")  # 'clean', 'merge', 'snapshot'
    restore_media = request.POST.get("restore_media") == "1"
    create_safety = request.POST.get("create_safety_backup", "1") == "1"
    sections = request.POST.getlist("sections") or None

    target_source = None
    source_name = ""

    if uploaded_file:
        target_source = uploaded_file
        source_name = uploaded_file.name
    elif server_filename:
        safe_filename = os.path.basename(server_filename)
        fp = get_backup_dir() / safe_filename
        if not fp.exists():
            messages.error(request, f"Выбранный файл архива не найден на сервере: {safe_filename}")
            return redirect("main:admin_backup_dashboard")
        target_source = fp
        source_name = safe_filename
    else:
        messages.error(request, "Не указан источник для восстановления: выберите файл на сервере или загрузите архив.")
        return redirect("main:admin_backup_dashboard")

    try:
        res = restore_backup(
            archive_path_or_file=target_source,
            sections=sections,
            mode=mode,
            restore_media=restore_media,
            preserve_superusers=True,
            create_safety_backup=create_safety,
            dry_run=False,
        )

        safety_note = ""
        if res.get("safety_backup"):
            safety_note = f" (Создана автоматическая точка отката: «{res['safety_backup']}»)"

        mode_name = "Чистый деплой" if mode == "clean" else ("Прямой снимок SQLite" if mode == "snapshot" else "Слияние/Обновление")

        messages.success(
            request,
            f"Восстановление из «{source_name}» успешно завершено за {res.get('duration_seconds', 0)}с! "
            f"Режим: {mode_name}. "
            f"Восстановлено объектов БД: {res['restored_total_records']}, "
            f"фотографий и файлов: {res['restored_media_count']} ({res['restored_media_mb']} MB). "
            f"Кэш сайта очищен.{safety_note}"
        )
    except Exception as e:
        messages.error(request, f"Ошибка при восстановлении данных из «{source_name}»: {e}")

    return redirect("main:admin_backup_dashboard")


@staff_member_required
@require_POST
def admin_backup_cleanup(request):
    """Очистка устаревших архивов с сохранением последних N бэкапов."""
    if not _check_superuser_permission(request):
        return redirect("admin:index")

    try:
        keep_count = int(request.POST.get("keep_count", 10))
    except (ValueError, TypeError):
        keep_count = 10

    res = cleanup_old_backups(keep_count=keep_count, keep_safety_count=5)
    if res["deleted_count"] > 0:
        messages.success(
            request,
            f"Очистка завершена: удалено {res['deleted_count']} устаревших архивов, "
            f"освобождено {res['freed_mb']} MB места на сервере."
        )
    else:
        messages.info(request, "Хранилище в порядке: лишних устаревших архивов не найдено.")

    return redirect("main:admin_backup_dashboard")


@staff_member_required
@require_POST
def admin_backup_delete(request, filename):
    """Удаление резервной копии."""
    if not _check_superuser_permission(request):
        return redirect("admin:index")

    safe_filename = os.path.basename(filename)
    file_path = get_backup_dir() / safe_filename

    if file_path.exists() and safe_filename.endswith(".zip"):
        try:
            file_path.unlink()
            messages.success(request, f"Резервная копия «{safe_filename}» удалена.")
        except Exception as e:
            messages.error(request, f"Не удалось удалить файл: {e}")
    else:
        messages.error(request, "Файл не найден.")

    return redirect("main:admin_backup_dashboard")
