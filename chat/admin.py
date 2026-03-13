from django.contrib import admin

# Register your models here.
from .models import ChatSession,ChatMessage
# Register your models here.
admin.site.register(ChatSession)
admin.site.register(ChatMessage)
