from django.urls import path

from . import views

app_name = 'support'

urlpatterns = [
    path('widget/state/', views.widget_state, name='widget_state'),
    path('widget/send/', views.widget_send, name='widget_send'),
    path('inbox/', views.SupportInboxView.as_view(), name='inbox'),
    path('inbox/threads/', views.threads_list, name='threads_list'),
    path('inbox/threads/<uuid:thread_id>/messages/', views.thread_messages, name='thread_messages'),
    path('inbox/threads/<uuid:thread_id>/send/', views.staff_send, name='staff_send'),
]
