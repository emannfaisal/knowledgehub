from functools import lru_cache
import os

from django.conf import settings
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

CHROMA_PATH = os.path.join(settings.BASE_DIR, "chroma_db")


@lru_cache(maxsize=1)
def get_vector_store():
    return Chroma(
        persist_directory=CHROMA_PATH,
        embedding_function=embedding_model,
    )


def invalidate_vector_store_cache():
    get_vector_store.cache_clear()