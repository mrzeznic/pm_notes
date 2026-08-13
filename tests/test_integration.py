import pytest
from pathlib import Path
from services.project_service import ProjectService
from services.markdown_parser import MarkdownParser
from services.ai_engine import AIEngine

@pytest.mark.asyncio
async def test_end_to_end_ai_integration(tmp_path, mocker):
    # 2. Create a real project and file
    proj = ProjectService.create_new_project(tmp_path, "Integration_Test_Project")
    
    initial_content = """# Integration_Test_Project
## Summary
A test project.
## Tasks
- [ ] Task A #p1
"""
    proj.path.write_text(initial_content)
    
    # 3. Parse the file via MarkdownParser
    content = proj.path.read_text(encoding="utf-8")
    tasks = MarkdownParser.parse_tasks(content)
    
    assert len(tasks) == 1
    assert tasks[0].clean_text == "Task A"
    
    # 4. Mock the AI endpoint and pass the data to AIEngine
    config = {"MODEL_PREFS": {"Tech Plan": "local"}}
    fake_ai_response = """
- [ ] Subtask 1 #p1
- [ ] Subtask 2 #p2
"""
    mocker.patch.object(AIEngine, 'run_prompt', return_value=fake_ai_response)
    
    subtasks = await AIEngine.decompose_task(tasks[0].clean_text, tasks[0].desc, proj.name, config)
    
    assert len(subtasks) == 2
    assert "- [ ] Subtask 1 #p1" in subtasks[0]

    
    # 5. Clean up happens automatically with pytest tmp_path
