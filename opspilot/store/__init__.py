"""Data access: small modules of hand-written SQL, one per table group.

Every function takes an open SQLAlchemy Connection so callers control the
transaction boundary (one business operation = one transaction).
"""
