from django.urls import path
from . import views
from .views import StylistDetailView, StylistListView, ServiceListView, AppointmentCreateView, dashboard_view, \
    dashboard_ajax, ReportView, my_appointments, cancel_appointment, ManualAppointmentCreateView, \
    get_stylists_by_service, get_available_times, StylistManualAppointmentCreateView, get_available_times_for_stylist, \
    stylist_reports, SalonDetailView, HomePageView, CategoryServicesView, autocomplete_search, service_booking, \
    stylist_dayoff_view

urlpatterns = [
    # path('', ServiceListView.as_view(), name='home'),
    path('', HomePageView.as_view(), name='home'),
    path('<int:pk>-<slug:slug>/', SalonDetailView.as_view(), name='salon_detail'),
    path('stylists/', StylistListView.as_view(), name='stylists'),
    path('stylist/<int:stylist_id>/', StylistDetailView.as_view(), name='stylist_detail'),
    path('make-appointment/', AppointmentCreateView.as_view(), name='make_appointment'),
    path('booking/', service_booking, name='service_booking'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('dashboard/ajax/', views.dashboard_ajax, name='dashboard_ajax'),
    path('dashboard/updates/', views.dashboard_updates, name='dashboard_updates'),
    path("appointment/<int:pk>/action/", views.AppointmentActionView.as_view(), name="appointment_action"),
    path("reports/", ReportView.as_view(), name="reports"),
    path("my-appointments/", my_appointments, name="my_appointments"),
    path("cancel-appointment/<int:appointment_id>/", cancel_appointment, name="cancel_appointment"),
    # path('category/<int:category_id>/', views.services_by_category, name='services_by_category'),
    path("stylist/dashboard/", views.stylist_dashboard, name="stylist_dashboard"),
    path("appointment/<int:appointment_id>/update-status/", views.appointment_update_status,
         name="appointment_update_status"),
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

]
