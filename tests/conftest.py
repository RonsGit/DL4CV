import pytest
import os

@pytest.fixture(scope="session")
def html_dir():
    # Return absolute path to html_output
    path = os.path.abspath("html_output")
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    return path
