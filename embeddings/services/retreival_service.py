from .vector_store_service import get_vector_store

def retrieve_user_context(query,user_id,top_k=3):
    vector_store=get_vector_store()
    results=vector_store.similarity_search(query, k=top_k, filter={"user_id": str(user_id)})
    context=[]
    for doc in results:
        context.append({"text":doc.page_content,
                        "document_id":doc.metadata.get("document_id"),
                        "folder_id":doc.metadata.get("folder_id"),
                        "chunk_index":doc.metadata.get("chunk_index")})
    return context
        

