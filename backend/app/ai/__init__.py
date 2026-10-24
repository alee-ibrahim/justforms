"""AI assistant (DESIGN section 12): provider adapters, schema tools and the tool loop.

The model never writes code or schema JSON directly: it calls tools (``app.ai.tools``) that
change an in-memory copy of the draft, and every change is validated by the form schema.
The result is a suggestion the person applies (or discards) in the builder.
"""
