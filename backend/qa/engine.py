"""
AWM Institute of Technology — Q&A Matching Engine
==================================================
Ported from the original JavaScript matching logic.
"""

import re
from backend.qa import (
    answer_bank, suggestion_bank, qa_bank,
    module_banks, video_bank, next_questions_bank,
    answer_module_map,
)


def normalize(query: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not query:
        return ''
    text = query.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def _score_keywords(normalized_query: str, keywords: list[str]) -> int:
    """Score how well a query matches a keyword list."""
    words = normalized_query.split()
    score = 0
    for kw in keywords:
        kw_lower = kw.lower()
        # Exact phrase match (highest value) — word-start boundary check
        if re.search(r'\b' + re.escape(kw_lower), normalized_query):
            score += 10
        # Individual word match
        for w in words:
            if w == kw_lower:
                score += 5
            elif kw_lower.startswith(w) or w.startswith(kw_lower):
                score += 2
    return score


def _build_answer(aid: str, text: str, module_slug: str | None = None) -> dict:
    """Build an answer response, attaching video metadata if available."""
    result = {'type': 'answer', 'answerId': aid, 'text': text}
    # Standalone chat: attach module reference so the frontend can render a link
    if not module_slug and aid in answer_module_map:
        mod = answer_module_map[aid]
        result['moduleRef'] = {
            'name': mod['name'],
            'url': '/modules/' + mod['slug'],
        }
    # Check module-scoped videos first, then global
    video = None
    if module_slug and module_slug in module_banks:
        video = module_banks[module_slug].get('videos', {}).get(aid)
    if not video:
        video = video_bank.get(aid)
    if video:
        result['video'] = video
    # Attach suggested next questions
    nq = None
    if module_slug and module_slug in module_banks:
        nq = module_banks[module_slug].get('next_questions', {}).get(aid)
    if not nq:
        nq = next_questions_bank.get(aid)
    if nq:
        result['nextQuestions'] = nq
    return result


def resolve_query(query: str, pending_follow_up: dict | None = None,
                  module_slug: str | None = None) -> dict:
    """
    Main entry point.  Returns a dict with either:
      { 'type': 'answer', 'answerId': str, 'text': str }
      { 'type': 'followUp', 'question': str, 'options': list }
      { 'type': 'noMatch' }

    When module_slug is provided, resolves against that module's
    scoped banks instead of the global banks.
    """
    nq = normalize(query)
    if not nq:
        return {'type': 'noMatch'}

    # Select banks based on scope
    if module_slug and module_slug in module_banks:
        banks = module_banks[module_slug]
        active_answers = banks['answers']
        active_qa = banks['qa_entries']
    else:
        active_answers = answer_bank
        active_qa = qa_bank

    # If there's a pending follow-up, try to match against its options first
    if pending_follow_up:
        options = pending_follow_up.get('options', [])
        best_opt = None
        best_score = 0
        for opt in options:
            s = _score_keywords(nq, opt.get('keywords', []))
            if s > best_score:
                best_score = s
                best_opt = opt
        if best_opt and best_score >= 5:
            aid = best_opt.get('answerId', '')
            text = active_answers.get(aid, '')
            if text:
                return _build_answer(aid, text, module_slug)

    # Score against QA entries (scoped or global)
    best_entry = None
    best_score = 0
    for entry in active_qa:
        s = _score_keywords(nq, entry.get('keywords', []))
        if s > best_score:
            best_score = s
            best_entry = entry

    if best_entry and best_score >= 5:
        # Check if it's a follow-up entry
        if 'followUp' in best_entry:
            fu = best_entry['followUp']
            return {
                'type': 'followUp',
                'question': fu['question'],
                'options': fu['options'],
            }
        # Single-turn answer
        aid = best_entry.get('answer', '')
        text = active_answers.get(aid, '')
        if text:
            return _build_answer(aid, text, module_slug)

    return {'type': 'noMatch'}


def resolve_by_answer_id(answer_id: str) -> dict:
    """Direct lookup for follow-up button clicks."""
    text = answer_bank.get(answer_id, '')
    if text:
        return _build_answer(answer_id, text)
    return {'type': 'noMatch'}


def get_autocomplete(query: str, limit: int = 5,
                     module_slug: str | None = None) -> list[dict]:
    """Return top matching suggestions for autocomplete."""
    nq = normalize(query)
    if not nq:
        return []

    if module_slug and module_slug in module_banks:
        active_suggestions = module_banks[module_slug]['suggestions']
    else:
        active_suggestions = suggestion_bank

    scored = []
    for suggestion in active_suggestions:
        s = _score_keywords(nq, suggestion.get('keywords', []))
        if s > 0:
            scored.append((s, suggestion))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:limit]]
