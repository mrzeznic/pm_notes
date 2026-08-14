import pytest
from services.ai_engine import AIEngine

@pytest.mark.asyncio
async def test_run_local_success(mocker):
    config = {"LOCAL_MODEL": "test-model"}
    
    # Mock the _http_post_json method
    mock_post = mocker.patch.object(
        AIEngine, '_http_post_json', 
        return_value=(200, '{"response": "Here is your plan."}')
    )
    
    result = await AIEngine.run_local("Make a plan", config)
    assert result == "Here is your plan."
    mock_post.assert_called_once()

@pytest.mark.asyncio
async def test_decompose_task(mocker):
    config = {"MODEL_PREFS": {"Tech Plan": "local"}}
    
    fake_response = """
- [ ] Task 1 #p1
- [ ] Task 2 #p2
  Some description
"""
    mocker.patch.object(AIEngine, 'run_prompt', return_value=fake_response)
    
    tasks = await AIEngine.decompose_task("Parent Task", "Context", "Project1", config)
    assert len(tasks) == 2
    assert "- [ ] Task 1 #p1" in tasks[0]
    assert "- [ ] Task 2 #p2" in tasks[1]
    assert "Some description" in tasks[1]

def test_filter_private_project_level():
    content = """# My Project
## Summary
#private
Some secret stuff
## Tasks
- [ ] Regular task
"""
    filtered = AIEngine.filter_private_content(content)
    assert filtered == ""

def test_filter_private_task_level():
    content = """# My Project
## Tasks
- [ ] Safe task
- [ ] Secret task #private
  Some secret description
- [ ] Another safe task
"""
    filtered = AIEngine.filter_private_content(content)
    assert "Safe task" in filtered
    assert "Another safe task" in filtered
    assert "Secret task" not in filtered
    assert "Some secret description" not in filtered

@pytest.mark.asyncio
async def test_run_copilot_http_success(mocker):
    config = {"GITHUB_TOKEN": "dummy_token"}
    
    # Mock AsyncOpenAI if it's used
    mock_openai = mocker.patch('services.ai_engine.AsyncOpenAI')
    mock_client = mock_openai.return_value
    
    # AsyncMock for the awaited method
    mock_create = mocker.AsyncMock()
    mock_create.return_value.choices = [
        mocker.Mock(message=mocker.Mock(content="Cloud response"))
    ]
    mock_client.chat.completions.create = mock_create
    
    # Also mock HTTP response just in case AsyncOpenAI is None
    mocker.patch.object(
        AIEngine, '_http_post_json',
        return_value=(200, '{"choices": [{"message": {"content": "Cloud response"}}]}')
    )
    
    result = await AIEngine.run_copilot("Prompt", config)
    assert result == "Cloud response"

@pytest.mark.asyncio
async def test_run_copilot_cli_fallback(mocker):
    config = {"GITHUB_TOKEN": "dummy_token", "GLOBAL_MODEL_CMD": "echo 'CLI fallback'"}
    
    # Mock AsyncOpenAI to raise Exception
    mock_openai = mocker.patch('services.ai_engine.AsyncOpenAI')
    mock_client = mock_openai.return_value
    
    mock_create = mocker.AsyncMock()
    mock_create.side_effect = Exception("API Error")
    mock_client.chat.completions.create = mock_create
    
    # Mock HTTP response to fail
    mocker.patch.object(
        AIEngine, '_http_post_json',
        return_value=(500, 'Internal Server Error')
    )
    
    result = await AIEngine.run_copilot("Prompt", config)
    assert "CLI fallback" in result
