from django.shortcuts import render
from embeddings.services.retreival_service import retrieve_user_context
from django.http import JsonResponse
import json
from django.views.decorators.http import require_http_methods
from .services.llm_service import llm
from django.contrib.auth.decorators import login_required
from .services.memory_service import get_conversation_memory
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from .models import ChatSession
from django.shortcuts import get_object_or_404

@login_required
@require_http_methods(["GET", "POST"])
def chat_sessions(request):
    """
    GET: List all chat sessions for the user
    POST: Create a new chat session
    """
    if request.method == "GET":
        sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
        session_list = [
            {
                "id": str(session.id),
                "created_at": session.created_at.isoformat()
            }
            for session in sessions
        ]
        return JsonResponse({"sessions": session_list})
    
    elif request.method == "POST":
        session = ChatSession.objects.create(user=request.user)
        return JsonResponse({
            "id": str(session.id),
            "created_at": session.created_at.isoformat()
        }, status=201)


@login_required
@require_http_methods(["GET", "DELETE"])
def chat_session_detail(request, session_id):
    """
    GET: Get session details and message history
    DELETE: Delete a chat session
    """
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)

    if request.method == "DELETE":
        session.delete()
        return JsonResponse({"message": "Session deleted"})

    memory = get_conversation_memory(session_id=session_id)
    
    messages = []
    for msg in memory.chat_memory.messages:
        messages.append({
            "role": "user" if isinstance(msg, HumanMessage) else "assistant",
            "content": msg.content
        })
    
    return JsonResponse({
        "id": str(session.id),
        "created_at": session.created_at.isoformat(),
        "messages": messages
    })


@login_required
@require_http_methods(["POST"])
def send_message(request, session_id):
    """
    POST: Send a message and get AI response
    """
    try:
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
        
        if not user_message:
            return JsonResponse({"error": "Message cannot be empty"}, status=400)
        
        # Retrieve relevant context from user's documents
        context_chunks = retrieve_user_context(
            query=user_message,
            user_id=request.user.id,
            top_k=3
        )
        
        # Get conversation memory
        memory = get_conversation_memory(session_id=session_id)
        history = memory.chat_memory.messages
        
        # Format context
        context_text = "\n\n".join([
            f"Source: {chunk.get('document_id', 'Unknown')}\n{chunk.get('text', '')}"
            for chunk in context_chunks
        ])
        
        # Prepare messages for LLM
        system_prompt = f"""You are a helpful assistant. Use the provided context to answer questions.
If the context doesn't contain relevant information, say so clearly.

Context:
{context_text}"""
        
        # Build messages in chronological order: system, history, then current message
        messages = [SystemMessage(content=system_prompt)]
        messages.extend(history)
        messages.append(HumanMessage(content=user_message))
        
        # Get LLM response
        response = llm.invoke(messages)
        
        # Store messages in memory using langchain interface
        memory.chat_memory.add_message(HumanMessage(content=user_message))
        memory.chat_memory.add_message(AIMessage(content=response.content))
        
        return JsonResponse({
            "role": "assistant",
            "content": response.content,
            "sources": context_chunks
        })
        
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)