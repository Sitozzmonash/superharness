# Mock RAG Service Specification

The test RAG service simulates the user's future external knowledge service. It must be a real HTTP server, not an in-process shortcut.

## 1. Implementation

Recommended: FastAPI or a minimal ASGI app.

Location:

```text
tests/services/rag_server/
├─ app.py
├─ corpus.json
├─ README.md
└─ __init__.py
```

## 2. Endpoint

```http
POST /retrieve
Content-Type: application/json
Authorization: Bearer <optional-test-token>
```

Request:

```json
{
  "query": "What is the release policy?",
  "top_n": 3
}
```

Simple response:

```json
{
  "results": [
    "Document chunk A",
    "Document chunk B",
    "Document chunk C"
  ]
}
```

Rich response mode:

```json
{
  "results": [
    {
      "text": "Document chunk A",
      "score": 0.98,
      "source": "policy.md",
      "metadata": {"section": "release"}
    }
  ]
}
```

## 3. Retrieval behavior

Use a deterministic lightweight scorer (token overlap/BM25/simple TF-IDF is fine) against a small corpus. The purpose is transport/contract testing, not benchmarking retrieval science.

Top-N must actually affect returned count/order.

## 4. Test routes/modes

Support deterministic failure simulation through separate endpoints or request flags:

- normal
- empty
- slow
- unauthorized
- 500
- malformed payload

Example:
```text
/retrieve
/test/slow
/test/error
/test/malformed
```

## 5. Adapter acceptance

`HTTPRAGProvider` must:
- construct request correctly;
- apply auth header;
- normalize simple/rich responses;
- enforce timeout;
- honor cancellation;
- retry only configured transient failures;
- raise typed `RAGError`;
- emit RAG events/traces;
- redact auth.

## 6. Final chain test

A known answer must exist only in mock RAG corpus. Ask Agent the question and verify:
1. RAG called;
2. correct evidence returned;
3. context contains normalized documents;
4. model answer includes expected fact;
5. trace contains retrieval metadata.

This proves the feature is actually usable.
