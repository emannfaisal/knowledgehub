from django.urls import path
from .views import folder_list_create, folder_detail, document_upload, document_delete, knowledge_view

urlpatterns = [
    # Knowledge page
    path("", knowledge_view, name="knowledge-home"),
    
    # folders
    path("folders/", folder_list_create, name="folder-list-create"),
    path("folders/<uuid:folder_id>/", folder_detail, name="folder-detail"),
    # documents
    path("folders/<uuid:folder_id>/documents/", document_upload, name="document-upload"),
    path("documents/<uuid:document_id>/", document_delete, name="document-delete"),
]
