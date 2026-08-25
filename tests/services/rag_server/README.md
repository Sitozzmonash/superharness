# Mock RAG service

`RAGHandler` is a real `ThreadingHTTPServer` handler implementing `POST /retrieve`.
It uses deterministic token overlap, enforces `top_n`, supports optional bearer auth,
and exposes `/test/empty`, `/test/slow`, `/test/error`, and `/test/malformed` modes.
