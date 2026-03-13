from django.shortcuts import render,get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from .models import Folder, Document
from embeddings.services.ingest_service import ingest_documents
import threading

@login_required
def knowledge_view(request):
    """Render the knowledge management page"""
    return render(request, "dashboard/knowledge.html")

@login_required
@require_http_methods(["GET", "POST"])
def  folder_list_create(request):
    if request.method == "GET":
        folders = Folder.objects.filter(owner=request.user)
        folder_list = [{"id": str(folder.id), "name": folder.name} for folder in folders]
        return JsonResponse({"folders": folder_list})

    elif request.method == "POST":
        name = request.POST.get("name")
        if not name:
            return JsonResponse({"error": "Folder name is required."}, status=400)
        folder = Folder.objects.create(owner=request.user, name=name)
        return JsonResponse({"id": str(folder.id), "name": folder.name}, status=201)
    
@login_required
@require_http_methods(["GET", "DELETE","PUT"])
def folder_detail(request, folder_id):
    folder = get_object_or_404(Folder, id=folder_id, owner=request.user)
    if request.method == "GET":
        documents = folder.documents.all()
        document_list = [{"id": str(doc.id), "name": doc.name} for doc in documents]
        return JsonResponse({"id": str(folder.id), "name": folder.name, "documents": document_list})

    elif request.method == "DELETE":
        folder.delete()
        return JsonResponse({"message": "Folder deleted successfully."}, status=204)
    
    elif request.method == "PUT":
        name = request.POST.get("name")
        if not name:
            return JsonResponse({"error": "Folder name is required."}, status=400)
        
        folder.name = name
        folder.save()
        return JsonResponse({"id": str(folder.id), "name": folder.name})
    
@login_required
@require_http_methods(["POST"])
def document_upload(request, folder_id):
    folder = get_object_or_404(Folder, id=folder_id, owner=request.user)

    file = request.FILES.get("file")
    if not file:
        return JsonResponse({"error": "File is required"}, status=400)

    document = Document.objects.create(
        folder=folder,
        name=file.name,
        file=file
    )    
    # Background ingestion into vector database
    threading.Thread(
        target=ingest_documents,
        args=(document,),
        daemon=True
    ).start()

    return JsonResponse({
        "id": str(document.id),
        "name": document.name,
        "file": document.file.url
    })

@login_required
@require_http_methods(["DELETE"])
def document_delete(request, document_id):
    document = get_object_or_404(Document, id=document_id, folder__owner=request.user)
    document.delete()
    return JsonResponse({"message": "Document deleted"})