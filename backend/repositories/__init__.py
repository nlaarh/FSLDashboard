"""Repositories — database access layer.

All database reads/writes go through these modules.
Routers import from here, never from database.py or pg_pool directly.
"""

# Will be populated as agents create each repository module
