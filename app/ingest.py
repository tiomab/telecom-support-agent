"""Build the vector index: python -m app.ingest"""

from app import rag

if __name__ == "__main__":
    n = rag.build_index()
    print(f"Indexed {n} chunks into Chroma.")
