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
