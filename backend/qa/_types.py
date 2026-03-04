"""
AWM Institute of Technology — Q&A Type Definitions
===================================================

Each category data file exports three constants:

ANSWERS : dict[str, str]
    Maps answer IDs to response text.
    Convention: '{category}-{topic}' e.g. 'general-hello'

SUGGESTIONS : list[dict]
    Each dict has:
        text     : str       — display text shown in autocomplete
        keywords : list[str] — words that trigger this suggestion

QA_ENTRIES : list[dict]
    Each dict has:
        keywords : list[str] — words the user might type
        answer   : str       — key into ANSWERS (for single-turn)
    OR (for multi-turn):
        keywords : list[str]
        followUp : dict
            question : str
            options  : list[dict]
                label    : str
                keywords : list[str]
                answerId : str   — key into ANSWERS
"""
