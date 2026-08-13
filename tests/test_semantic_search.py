import pytest
from pathlib import Path
from services.semantic_search import SemanticSearch
from models.task import Task

@pytest.fixture
def semantic_search(tmp_path):
    # Use a temporary directory for ChromaDB
    db_path = tmp_path / "chromadb"
    search_service = SemanticSearch(persist_dir=str(db_path))
    return search_service

def test_semantic_search_indexing_and_querying(semantic_search):
    # Given a list of tasks
    tasks = [
        Task(
            id="task-1",
            line_start=1,
            line_end=1,
            clean_text="Implement Stripe payment gateway",
            raw_text="- [ ] Implement Stripe payment gateway",
            is_done=False,
            desc="Need to handle credit card payments"
        ),
        Task(
            id="task-2",
            line_start=2,
            line_end=2,
            clean_text="Refactor the authentication logic",
            raw_text="- [ ] Refactor the authentication logic",
            is_done=False,
            desc="JWT tokens are expiring too soon"
        )
    ]
    
    # When we index them
    semantic_search.index_tasks(tasks)
    
    # And we perform a semantic search
    # Searching for 'money' should semantically match the Stripe payment task
    results = semantic_search.search("money processing")
    
    # Then it should return the closest match
    assert len(results) > 0
    assert results[0] == "task-1"

def test_semantic_search_ignores_private_tasks(semantic_search):
    tasks = [
        Task(
            id="task-safe",
            line_start=1,
            line_end=1,
            clean_text="Public task",
            raw_text="- [ ] Public task",
            is_done=False
        ),
        Task(
            id="task-secret",
            line_start=2,
            line_end=2,
            clean_text="Secret task",
            raw_text="- [ ] Secret task #private",
            is_done=False
        )
    ]
    
    semantic_search.index_tasks(tasks)
    
    results = semantic_search.search("task")
    assert "task-safe" in results
    assert "task-secret" not in results
