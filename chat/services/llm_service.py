from langchain_ollama import ChatOllama
from django.conf import settings

llm = ChatOllama(
	model=settings.OLLAMA_MODEL,
	base_url=settings.OLLAMA_BASE_URL,
	temperature=0.3,
)

