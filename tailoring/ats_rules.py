"""ATS-compliance rules — the same constraints are used as prompt instructions
for the LLM (so the *content* it writes fits the format) and as the layout
rules docx_export.py follows (so the *document structure* enforces them too,
regardless of what the model produces).
"""

FORMATTING_RULES_PROMPT = """
Formatting constraints for everything you write (this content will be placed
into a single-column Word document using real paragraph heading styles):
- Plain prose and bullet points only. Never describe or imply tables, columns,
  text boxes, images, icons, or star/rating graphics — these are frequently
  dropped or garbled by ATS parsers.
- No unusual Unicode characters (no emoji, no fancy bullet glyphs, no
  ligatures). Use a plain hyphen or period for bullets.
- Keep bullets concrete and evidence-based (what you did, what changed,
  ideally a number) rather than generic adjectives.
- Write in UK English.
""".strip()

CV_SECTION_ORDER = [
    "Personal Details",
    "Personal Statement",
    "Employment History",
    "Education & Qualifications",
    "Professional Registration",
    "Skills",
    "Training & CPD",
    "References",
]

FONT_NAME = "Calibri"
FONT_SIZE_PT = 11
HEADING_FONT_SIZE_PT = 13
