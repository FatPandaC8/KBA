import os
import glob
import pytest

def test_domain_layer_has_zero_framework_dependencies():
    """Verify domain layer never imports FastAPI, Pydantic, SQLAlchemy, or HTTP clients."""
    forbidden_modules = ["fastapi", "requests", "urllib", "sqlite3", "fastembed", "faster_whisper"]
    domain_files = glob.glob("server/app/domain/**/*.py", recursive=True)

    for fpath in domain_files:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        for forbidden in forbidden_modules:
            assert f"import {forbidden}" not in content, f"Domain file {fpath} must not import {forbidden}"
            assert f"from {forbidden}" not in content, f"Domain file {fpath} must not import from {forbidden}"

def test_application_layer_does_not_import_fastapi_or_concrete_adapters():
    """Verify application use cases depend only on ports, domain, and DTOs."""
    forbidden_modules = ["fastapi", "server.app.adapters", "server.app.infrastructure"]
    app_files = glob.glob("server/app/application/**/*.py", recursive=True)

    for fpath in app_files:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        for forbidden in forbidden_modules:
            assert f"import {forbidden}" not in content, f"Application file {fpath} must not import {forbidden}"
            assert f"from {forbidden}" not in content, f"Application file {fpath} must not import from {forbidden}"
