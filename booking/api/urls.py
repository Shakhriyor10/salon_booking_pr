from django.urls import path

from booking.api.views import (
    AppointmentListCreateView,
    AvailableSlotsView,
    CityListView,
    CustomObtainAuthToken,
    RegistrationView,
    SalonListView,
    SalonServiceListView,
    StylistListView,
)

urlpatterns = [
    path("auth/register/", RegistrationView.as_view(), name="api-register"),
    path("auth/token/", CustomObtainAuthToken.as_view(), name="api-token"),
    path("cities/", CityListView.as_view(), name="api-cities"),
    path("salons/", SalonListView.as_view(), name="api-salons"),
    path("salons/<int:pk>/services/", SalonServiceListView.as_view(), name="api-salon-services"),
    path("stylists/", StylistListView.as_view(), name="api-stylists"),
    path("stylists/<int:stylist_id>/slots/", AvailableSlotsView.as_view(), name="api-available-slots"),
    path("appointments/", AppointmentListCreateView.as_view(), name="api-appointments"),
]
