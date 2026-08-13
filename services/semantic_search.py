import os
from pathlib import Path
from typing import List, Optional
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from models.task import Task
from core.logger import AILogger

class SemanticSearch:
    def __init__(self, persist_dir: Optional[str] = None):
        if not persist_dir:
            # Default to a .chroma directory in the user's home or project root
            persist_dir = str(Path.home() / ".tpm_data" / "chromadb")
            
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        
        AILogger.log(f"Initializing ChromaDB at {persist_dir}...", "info")
        try:
            self.client = chromadb.PersistentClient(path=persist_dir)
            # Use the default lightweight local embedding model (all-MiniLM-L6-v2)
            self.embed_fn = embedding_functions.DefaultEmbeddingFunction()
            
            self.collection = self.client.get_or_create_collection(
                name="pm_tasks",
                embedding_function=self.embed_fn
            )
            AILogger.log(f"Semantic Search ready. Loaded {self.collection.count()} tasks in DB.", "success")
        except Exception as e:
            AILogger.log(f"Failed to initialize ChromaDB: {e}", "error")
            self.collection = None

    def index_tasks(self, tasks: List[Task]):
        if not self.collection or not tasks:
            return
            
        ids = []
        documents = []
        metadatas = []
        
        for task in tasks:
            # We don't want to index private tasks in the searchable vector DB
            if "#private" in task.raw_text:
                continue
                
            ids.append(task.id)
            
            # Build a rich semantic document for the task
            project_name = task.project_path.parent.name if task.project_path else "Unknown"
            status = "Done" if task.is_done else task.kanban_status
            
            doc_str = f"Project: {project_name}. Task: {task.clean_text}. Status: {status}."
            if task.desc:
                doc_str += f" Description: {task.desc}"
            if task.blocked:
                doc_str += f" Blocked by: {task.blocked}"
            
            documents.append(doc_str)
            metadatas.append({
                "project": project_name,
                "is_done": task.is_done,
                "prio": task.prio
            })
            
        if ids:
            try:
                # Upsert updates existing tasks or adds new ones
                self.collection.upsert(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas
                )
                AILogger.log(f"Upserted {len(ids)} tasks to vector DB.", "info")
            except Exception as e:
                AILogger.log(f"Error upserting to ChromaDB: {e}", "error")

    def search(self, query: str, n_results: int = 15) -> List[str]:
        if not self.collection or not query.strip():
            return []
            
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=min(n_results, self.collection.count())
            )
            # results["ids"] is a list of lists, where the first list corresponds to the first query
            if results and "ids" in results and results["ids"]:
                return results["ids"][0]
        except Exception as e:
            AILogger.log(f"Semantic search failed: {e}", "error")
            
        return []
