import pytest
from ui.styles import get_project_color

def test_get_project_color_consistency():
    # It must return the exact same color for the same project name
    color1 = get_project_color("Demo_Project")
    color2 = get_project_color("Demo_Project")
    assert color1 == color2

def test_get_project_color_variance():
    # Different project names should generally return different colors 
    # (though collisions are possible, these two should differ)
    color1 = get_project_color("Frontend")
    color2 = get_project_color("Backend")
    assert color1 != color2
