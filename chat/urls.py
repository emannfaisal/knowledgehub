from django.urls import path
from .views import chat_sessions, chat_session_detail, send_message

urlpatterns = [
    # Chat sessions
    path('sessions/', chat_sessions, name='chat-sessions'),
    path('sessions/<uuid:session_id>/', chat_session_detail, name='chat-session-detail'),
    path('sessions/<uuid:session_id>/message/', send_message, name='send-message'),
]
