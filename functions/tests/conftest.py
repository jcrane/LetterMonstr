import os
import sys
from pathlib import Path

import pytest

FUNCTIONS_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = FUNCTIONS_DIR.parent

if str(FUNCTIONS_DIR) not in sys.path:
    sys.path.insert(0, str(FUNCTIONS_DIR))


@pytest.fixture()
def mock_content_config():
    return {
        "max_links_per_email": 5,
        "max_link_depth": 1,
        "user_agent": "TestAgent/1.0",
        "request_timeout": 10,
        "ad_keywords": ["sponsored", "advertisement"],
    }


@pytest.fixture()
def project_root():
    return PROJECT_ROOT
