import uuid
from django.db import models
from django.contrib.auth.models import User
from knowledge.models import Folder, Document

class DocumentChunk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="document_chunks"
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="chunks"
    )

    chunk_index=models.IntegerField()
    
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ('document', 'chunk_index')
