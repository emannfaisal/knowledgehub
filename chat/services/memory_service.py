from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_core.chat_history import BaseChatMessageHistory

from chat.models import ChatMessage, ChatSession
from typing import List


class DjangoChatHistory(BaseChatMessageHistory):
    """Custom chat history implementation using Django ORM"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
    
    @property
    def messages(self) -> List[BaseMessage]:
        """Get all messages from database"""
        messages = ChatMessage.objects.filter(session__id=self.session_id).order_by('created_at')
        result = []
        for msg in messages:
            if msg.role == 'human':
                result.append(HumanMessage(content=msg.content))
            else:
                result.append(AIMessage(content=msg.content))
        return result
    
    def add_message(self, message: BaseMessage) -> None:
        """Add a message to the chat history"""
        if isinstance(message, HumanMessage):
            role = 'human'
        elif isinstance(message, AIMessage):
            role = 'ai'
        else:
            raise ValueError(f"Unsupported message type: {type(message)}")
        
        ChatMessage.objects.create(
            session_id=self.session_id,
            role=role,
            content=message.content
        )
    
    def clear(self) -> None:
        """Clear all messages for this session"""
        ChatMessage.objects.filter(session__id=self.session_id).delete()


class ConversationMemory:
    """Simple wrapper to maintain API compatibility"""
    def __init__(self, chat_memory):
        self.chat_memory = chat_memory


def get_conversation_memory(session_id):
    """Get conversation memory for a session"""
    history = DjangoChatHistory(session_id=str(session_id))
    return ConversationMemory(chat_memory=history)




