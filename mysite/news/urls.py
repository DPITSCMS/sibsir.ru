from django.urls import path
from . import views

app_name = "news"

urlpatterns = [
    path("", views.news_list_view, name="news_list"),
    path("add/", views.news_create_view, name="news_create"),
    path("<slug:slug>/edit/", views.news_edit_view, name="news_edit"),
    path("<slug:slug>/", views.news_detail_view, name="news_detail"),
]
