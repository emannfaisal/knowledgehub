from langchain_community.document_loaders import PyPDFLoader ,TextLoader,Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from django.contrib.auth.decorators import login_required
from embeddings.models import DocumentChunk
from embeddings.services.vector_store_service import get_vector_store, invalidate_vector_store_cache
import logging
import os

logger = logging.getLogger(__name__)

def load_document(file_path):
    if file_path.endswith('.pdf'):
        loader = PyPDFLoader(file_path)
    elif file_path.endswith('.txt'):
        loader = TextLoader(file_path)
    elif file_path.endswith('.docx'):
        loader = Docx2txtLoader(file_path)
    else:
        raise ValueError("Unsupported file type")
    
    return loader.load()

def ingest_documents(document):
    """Ingest document into vector store. Skips if already embedded."""
    from django.utils import timezone
    
    # Skip if already embedded
    if document.is_embedded:
        print(f"Document {document.id} already embedded. Skipping.")
        return
    
    # Skip if chunks already exist in database
    if document.chunks.exists():
        print(f"Document {document.id} already has chunks. Marking as embedded.")
        document.is_embedded = True
        document.embedded_at = timezone.now()
        document.save()
        return
    
    try:
        docs=load_document(document.file.path) 
        # 1. CLEAN THE TEXT: Remove the extra spaces if the PDF loader failed
        for doc in docs:
            # Simple heuristic: if every other char is a space, join them
            if " " in doc.page_content and len(doc.page_content) > 100:
                # This is a safety net for the specific issue in your logs
                import re
                doc.page_content = re.sub(r'(?<=[a-zA-Z])\s(?=[a-zA-Z]\s)', '', doc.page_content)
        splitter=RecursiveCharacterTextSplitter(chunk_size=600,chunk_overlap=120,separators=["\n\n", "\n", " ", ""])
        chunks=splitter.split_documents(docs)

        vectorstore=get_vector_store()
        langchain_chunks=[]
        
        # Get user from document's folder
        user = document.folder.owner
        
        for i,chunk in enumerate(chunks):
            DocumentChunk.objects.create(
                user=user,
                document=document,
                chunk_index=i,
                content=chunk.page_content
            )
            chunk.metadata.update({
                "document_id":str(document.id),
                "chunk_index":i,
                "folder_id":str(document.folder.id),
                "user_id":str(user.id)
            })
            langchain_chunks.append(chunk)
        
        vectorstore.add_documents(langchain_chunks)
        vectorstore.persist()
        invalidate_vector_store_cache()
        
        # Mark as successfully embedded
        document.is_embedded = True
        document.embedded_at = timezone.now()
        document.save()
        print(f"Successfully embedded document {document.id}")
        
    except Exception as e:
        print(f"Error embedding document {document.id}: {str(e)}")


def delete_document_embeddings(document_id):
    vectorstore = get_vector_store()
    where_filter = {"document_id": str(document_id)}

    try:
        vectorstore.delete(where=where_filter)
        vectorstore.persist()
    except TypeError:
        vectorstore._collection.delete(where=where_filter)
        vectorstore.persist()
    except Exception as e:
        logger.warning("Failed to delete Chroma embeddings for document %s: %s", document_id, str(e))
        return

    invalidate_vector_store_cache()