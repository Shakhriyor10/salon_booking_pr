from django.urls import path
from . import views
from . import telegram_api
from .views import StylistDetailView, StylistListView, ServiceListView, AppointmentCreateView, dashboard_view, \
    dashboard_ajax, ReportView, my_appointments, cancel_appointment, ManualAppointmentCreateView, \
    get_stylists_by_service, get_available_times, StylistManualAppointmentCreateView, get_available_times_for_stylist, \
    stylist_reports, SalonDetailView, HomePageView, CategoryServicesView, autocomplete_search, service_booking, \
    stylist_dayoff_view, delete_review, toggle_favorite_salon

urlpatterns = [
    # path('', ServiceListView.as_view(), name='home'),
    path('', HomePageView.as_view(), name='home'),
    path('add-salon/', views.salon_application, name='salon_application'),
    path('<int:pk>-<slug:slug>/', SalonDetailView.as_view(), name='salon_detail'),
    path('<int:pk>/products/add-to-cart/', views.add_product_to_cart, name='add_product_to_cart'),
    path('<int:pk>/products/cart-item/', views.update_product_cart_item, name='update_product_cart_item'),
    path('<int:pk>/products/checkout/', views.checkout_salon_products, name='checkout_salon_products'),
    path('my-product-orders/', views.my_product_orders, name='my_product_orders'),
    path('my-product-orders/<int:pk>/cancel/', views.cancel_product_order, name='cancel_product_order'),
    path('salon/product-orders/', views.salon_product_orders_admin, name='salon_product_orders_admin'),
    path('stylists/', StylistListView.as_view(), name='stylists'),
    path('stylist/<int:stylist_id>/', StylistDetailView.as_view(), name='stylist_detail'),
    path('make-appointment/', AppointmentCreateView.as_view(), name='make_appointment'),
    path('booking/', service_booking, name='service_booking'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('dashboard/ajax/', views.dashboard_ajax, name='dashboard_ajax'),
    path('dashboard/updates/', views.dashboard_updates, name='dashboard_updates'),
    path('appointments/overdue/complete/', views.complete_overdue_appointments, name='complete_overdue_appointments'),
    path("appointment/<int:pk>/action/", views.AppointmentActionView.as_view(), name="appointment_action"),
    path("reports/", ReportView.as_view(), name="reports"),
    path("my-appointments/", my_appointments, name="my_appointments"),
    path("cancel-appointment/<int:appointment_id>/", cancel_appointment, name="cancel_appointment"),
    # path('category/<int:category_id>/', views.services_by_category, name='services_by_category'),
    path("stylist/dashboard/", views.stylist_dashboard, name="stylist_dashboard"),
    path("stylist/dashboard/ajax/", views.stylist_dashboard_ajax, name="stylist_dashboard_ajax"),
    path("stylist/dashboard/updates/", views.stylist_dashboard_updates, name="stylist_dashboard_updates"),
    path("appointment/<int:appointment_id>/update-status/", views.appointment_update_status,
         name="appointment_update_status"),
    path("appointment/<int:appointment_id>/payment-action/", views.appointment_payment_action,
         name="appointment_payment_action"),
    path('manual-appointment/', ManualAppointmentCreateView.as_view(), name='manual_appointment'),
    path('get-stylists-by-service/', get_stylists_by_service, name='get_stylists_by_service'),
    path('get-available-times/', get_available_times, name='get_available_times'),
    path('stylist/appointment/', StylistManualAppointmentCreateView.as_view(), name='stylist_manual_appointment'),
    path('ajax/get_available_times/', get_available_times_for_stylist, name='get_available_times'),
    path('stylist/reports/', views.stylist_reports, name='stylist_reports'),
    path('category/<int:pk>/', CategoryServicesView.as_view(), name='category_services'),
    # path('services/search/', ServiceSearchView.as_view(), name='service_search')
    path('autocomplete/', views.autocomplete_search, name='autocomplete_search'),
    path('stylist/dayoff/', views.stylist_dayoff_view, name='stylist_dayoff'),
    path('delete-dayoff/<int:pk>/', views.delete_dayoff, name='delete_dayoff'),
    path('reviews/<int:pk>/delete/', delete_review, name='delete_review'),
    path('stylist/ajax/<int:stylist_id>/', views.ajax_stylist_data, name='ajax_stylist_data'),
    path('stylist/ajax/price/', views.ajax_update_price, name='ajax_update_price'),
    path('favorites/toggle/', toggle_favorite_salon, name='toggle_favorite'),
    # Telegram WebApp API
    path('telegram/api/bootstrap/', telegram_api.telegram_bootstrap, name='telegram_bootstrap'),
    path('telegram/api/salons/<int:salon_id>/', telegram_api.telegram_salon_detail, name='telegram_salon_detail'),
    path('telegram/api/available-times/', telegram_api.telegram_available_times, name='telegram_available_times'),
    path('telegram/api/appointments/', telegram_api.telegram_create_appointment, name='telegram_create_appointment'),
]