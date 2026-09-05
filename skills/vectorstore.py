"""
Vector storage for Collig skills, on native ``chromadb``.

Replaces ``langchain-chroma`` + ``langchain-openai``'s ``OpenAIEmbeddings``
with a thin layer over ``chromadb.PersistentClient`` and the ``openai`` SDK,
keeping the five operations the skills actually used: construct, add, search,
delete, and direct access to the underlying collection.

On-disk compatibility is deliberate -- collection names, persist directories
and embedding models are unchanged, so the existing databases under
``~/.collig`` keep working. Embeddings are always passed to Chroma
explicitly (``query_embeddings=`` / ``embeddings=``), exactly as
langchain-chroma did, so the collections stay embedding-function-less and
Chroma never tries to download a local model.

Note this lives in ``skills/`` rather than ``core/`` on purpose: importing
``core.anything`` runs ``core/__init__.py``, which pulls in prompt_toolkit.
"""
import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

import chromadb

# The default OpenAI embedding model, and the one every existing Collig
# collection was built with. 1536 dimensions.
DEFAULT_EMBEDDING_MODEL = "text-embedding-ada-002"

# DashScope's OpenAI-compatible endpoints, by configured region.
DASHSCOPE_ENDPOINTS = {
    "china": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "international": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
}
DASHSCOPE_EMBEDDING_MODEL = "text-embedding-v2"

# text-embedding-ada-002 accepts 8191 tokens; DashScope's v2 is shorter still.
# Long inputs (mostly emails) are truncated rather than rejected.
_MAX_TOKENS = 6000

# DashScope caps an embedding request at 25 inputs; OpenAI allows far more,
# so the smaller limit is used for both.
_BATCH_SIZE = 20


@dataclass
class Document:
    """A stored document. Mirrors ``langchain_core.documents.Document``."""

    page_content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None


class Embedder:
    """
    Embeddings via any OpenAI-compatible endpoint.

    Replaces ``langchain_openai.OpenAIEmbeddings`` with the same two methods
    the skills call, plus the token-aware truncation LangChain did for us.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_EMBEDDING_MODEL,
                 base_url: Optional[str] = None):
        from openai import OpenAI

        self.model = model
        self.base_url = base_url
        self._client = OpenAI(api_key=api_key, base_url=base_url) if base_url \
            else OpenAI(api_key=api_key)

    def _truncate(self, text: str) -> str:
        """Cut `text` down to _MAX_TOKENS, so the API never rejects it."""
        try:
            import tiktoken
            try:
                enc = tiktoken.encoding_for_model(self.model)
            except KeyError:
                enc = tiktoken.get_encoding("cl100k_base")
            tokens = enc.encode(text, disallowed_special=())
            if len(tokens) <= _MAX_TOKENS:
                return text
            return enc.decode(tokens[:_MAX_TOKENS])
        except Exception:
            # No tiktoken, or an encoding failure: fall back to a character
            # budget at a conservative ~3 characters per token.
            limit = _MAX_TOKENS * 3
            return text if len(text) <= limit else text[:limit]

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        """Embed a batch of texts, in request-sized chunks."""
        prepared = [self._truncate(t or " ") for t in texts]
        vectors: List[List[float]] = []
        for start in range(0, len(prepared), _BATCH_SIZE):
            batch = prepared[start:start + _BATCH_SIZE]
            response = self._client.embeddings.create(model=self.model, input=batch)
            # The API may return items out of order; `index` is authoritative.
            for item in sorted(response.data, key=lambda d: d.index):
                vectors.append(list(item.embedding))
        return vectors

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query string."""
        return self.embed_documents([text])[0]


# chromadb complains if the same path is opened by two clients with different
# settings, and opening one is not free -- so keep one per directory.
_clients: Dict[str, Any] = {}
_clients_lock = threading.Lock()


def _get_client(persist_directory: str):
    path = os.path.abspath(os.path.expanduser(persist_directory))
    with _clients_lock:
        client = _clients.get(path)
        if client is None:
            os.makedirs(path, exist_ok=True)
            client = chromadb.PersistentClient(path=path)
            _clients[path] = client
        return client


class CollectionStore:
    """
    One Chroma collection, with the slice of the LangChain API Collig used.

    ``add_documents`` / ``similarity_search`` / ``delete`` behave as before.
    ``_collection`` is the raw ``chromadb`` collection, so the call sites that
    reached through LangChain to ``.get()`` and ``.update()`` keep working.
    """

    def __init__(self, persist_directory: str, collection_name: str,
                 embeddings: Embedder):
        self.persist_directory = os.path.abspath(os.path.expanduser(persist_directory))
        self.collection_name = collection_name
        self.embeddings = embeddings
        # embedding_function=None keeps the collection vector-only: Chroma
        # stores no embedder of its own and never tries to fetch a model.
        self._collection = _get_client(self.persist_directory).get_or_create_collection(
            name=collection_name,
            embedding_function=None,
        )

    def add_documents(self, documents: Sequence[Document],
                      ids: Optional[Sequence[str]] = None) -> List[str]:
        """Embed and store documents. Returns the stored IDs."""
        if not documents:
            return []

        texts = [doc.page_content for doc in documents]
        doc_ids = list(ids) if ids else [
            doc.id or str(uuid.uuid4()) for doc in documents
        ]
        # Chroma rejects None values and empty metadata dicts.
        metadatas = [
            {k: v for k, v in (doc.metadata or {}).items() if v is not None} or {"_": ""}
            for doc in documents
        ]

        # cast() only quiets chromadb's invariant list annotations.
        self._collection.upsert(
            ids=doc_ids,
            documents=texts,
            metadatas=cast(Any, metadatas),
            embeddings=cast(Any, self.embeddings.embed_documents(texts)),
        )
        return doc_ids

    def similarity_search(self, query: str, k: int = 4,
                          filter: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Return the `k` documents most similar to `query`."""
        results = self._collection.query(
            query_embeddings=[self.embeddings.embed_query(query)],
            n_results=k,
            where=filter,
            include=["documents", "metadatas"],
        )

        # query() returns one list per query embedding; there is only ever one.
        docs = (results.get("documents") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        ids = (results.get("ids") or [[]])[0]

        return [
            Document(page_content=doc or "", metadata=dict(meta or {}), id=doc_id)
            for doc, meta, doc_id in zip(docs, metas, ids)
        ]

    def update_documents(self, ids: Sequence[str],
                         documents: Optional[Sequence[str]] = None,
                         metadatas: Optional[Sequence[Dict[str, Any]]] = None) -> None:
        """
        Update stored records, re-embedding any changed text.

        Updating the text through ``_collection.update()`` alone would leave
        the old vector in place, so edited records would still be found by
        their previous wording.
        """
        kwargs: Dict[str, Any] = {"ids": list(ids)}
        if documents is not None:
            kwargs["documents"] = list(documents)
            kwargs["embeddings"] = self.embeddings.embed_documents(documents)
        if metadatas is not None:
            kwargs["metadatas"] = [
                {k: v for k, v in (m or {}).items() if v is not None} or {"_": ""}
                for m in metadatas
            ]
        self._collection.update(**kwargs)

    def delete(self, ids: Sequence[str]) -> None:
        """Delete records by ID."""
        if ids:
            self._collection.delete(ids=list(ids))

    def count(self) -> int:
        """Number of stored records."""
        return self._collection.count()


def default_data_dir(name: str) -> str:
    """
    The standard persist directory for a store: ``~/.collig/data/<name>``.

    Mirrors ``core.paths.get_skill_data_dir``, which skills cannot import
    without dragging in prompt_toolkit via ``core/__init__.py``.
    """
    return os.path.join(os.path.expanduser("~"), ".collig", "data", name)


# Probe result per (key, endpoint). Five skills resolve an embedder during
# startup; without this each one paid a separate network round trip to find
# out the same thing, which is several seconds on a key that has no embedding
# entitlement and answers with an error.
_dashscope_probe: Dict[Tuple[str, str], bool] = {}
_dashscope_probe_lock = threading.Lock()


def _dashscope_reachable(api_key: str, base_url: str) -> bool:
    """Whether DashScope will serve embeddings for this key, probed once."""
    cache_key = (api_key, base_url)
    with _dashscope_probe_lock:
        if cache_key in _dashscope_probe:
            return _dashscope_probe[cache_key]
        try:
            Embedder(api_key, DASHSCOPE_EMBEDDING_MODEL, base_url).embed_query("test")
            ok = True
        except Exception as e:
            print(f"DashScope embeddings unavailable ({e}), using OpenAI instead")
            ok = False
        _dashscope_probe[cache_key] = ok
        return ok


def resolve_embedder(config: Dict[str, Any],
                     force_openai: bool = False) -> Optional[Embedder]:
    """
    Build the Embedder for the configured provider, or None if no key is set.

    Every provider other than DashScope embeds through OpenAI, which is what
    the existing collections were built with. DashScope embeds through its
    OpenAI-compatible endpoint, falling back to OpenAI if that endpoint is
    unreachable and an OpenAI key is available.

    ``force_openai`` pins a collection to OpenAI regardless of provider. A
    collection's vectors are only comparable with others from the same model,
    so a store that has always embedded through OpenAI must keep doing so even
    when the chat provider is DashScope.
    """
    config = config or {}
    provider = config.get("LLM_PROVIDER", "openai")

    if provider == "dashscope" and not force_openai:
        api_key = config.get("DASHSCOPE_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        region = config.get("DASHSCOPE_ENDPOINT", "china")
        base_url = DASHSCOPE_ENDPOINTS.get(region, DASHSCOPE_ENDPOINTS["china"])
        if api_key and _dashscope_reachable(api_key, base_url):
            return Embedder(api_key, DASHSCOPE_EMBEDDING_MODEL, base_url)

    api_key = config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return Embedder(api_key, DEFAULT_EMBEDDING_MODEL)


def open_store(config: Dict[str, Any], persist_directory: str,
               collection_name: str, label: str = "store",
               force_openai: bool = False) -> Optional[CollectionStore]:
    """
    Open a collection for the configured provider.

    Returns None (rather than raising) when there is no usable API key or the
    store cannot be opened, matching how the skills already degrade.
    """
    try:
        embedder = resolve_embedder(config, force_openai=force_openai)
        if embedder is None:
            return None
        return CollectionStore(persist_directory, collection_name, embedder)
    except Exception as e:
        print(f"Failed to initialize {label} storage: {e}")
        return None
