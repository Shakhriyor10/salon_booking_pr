# users/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/',    views.login_view,    name='login'),
    path('logout/',   views.logout_view,   name='logout'),
    path('salon-admin/apply/', views.salon_admin_application_view, name='salon_admin_apply'),
]
