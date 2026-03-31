"""Compatibility shim: module moved to backend.database.

Expose the backend module object directly so attribute updates like
`database.DB_PATH = ...` keep working as before.
"""
import sys
from backend import database as _database_module

sys.modules[__name__] = _database_module
