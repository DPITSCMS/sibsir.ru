"""
URL configuration for mysite project.
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static

from main.views import tinymce_image_upload
from main.seo_views import (
    robots_txt_view,
    sitemap_xml_view,
    sitemap_html_view,
    favicon_view,
    yandex_verification_view,
)
from main.feeds import LatestEntriesFeed, NewsFeed, ArticlesFeed

urlpatterns = [
    path('favicon.ico', favicon_view, name='favicon'),
    path('robots.txt', robots_txt_view, name='robots_txt'),
    path('sitemap.xml', sitemap_xml_view, name='sitemap_xml'),
    path('sitemap/', sitemap_html_view, name='sitemap_html'),
    path('rss/', LatestEntriesFeed(), name='rss_feed'),
    path('feed/', LatestEntriesFeed(), name='feed_alias'),
    path('rss/news/', NewsFeed(), name='news_rss_feed'),
    path('rss/articles/', ArticlesFeed(), name='articles_rss_feed'),
    path('yandex_2481be1b37f5b18c.html', yandex_verification_view, name='yandex_verification_file'),
    re_path(r'^(?P<filename>yandex_[a-zA-Z0-9]+\.html)$', yandex_verification_view, name='yandex_verification_any'),
    path('admin/', admin.site.urls),
    path('tinymce/', include('tinymce.urls')),
    path('admin-tinymce-upload/', tinymce_image_upload, name='tinymce_image_upload'),
    path('shop/', include('shop.urls')),
    path('accounts/', include('accounts.urls')),
    path('news/', include('news.urls')),
    path('', include('main.urls')),
]

from django.contrib.staticfiles.urls import staticfiles_urlpatterns

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    if hasattr(settings, 'MEDIA_ROOT'):
        urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
