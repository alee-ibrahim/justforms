"""Insights and "Ask your submissions" (DESIGN 15.4, 12.6).

- ``catalogue``: the questions of a form across all its published versions (field keys,
  merged options, repeaters and version field mappings).
- ``dsl``: a small JSON query language over submissions, compiled to parameterised SQL over
  the JSONB answers. Insights and the AI's ``query_submissions`` tool both run on it, so the
  page and the AI count the same way.
- ``summary``: the per-question summaries of the Insights page.
- ``ask``: the AI tool loop that answers questions about the submissions.
"""
