# UI Changelog
# =============
# Check here BEFORE making CSS changes to avoid redoing work.
# Update this file AFTER every styling change.

---

## Files That Must Be Edited Together
- `frontend/static/css/chat/input.css` (source)
- `frontend/static/css/main.built.css` (bundled — what the browser loads)
- After changes, rebuild: `powershell -File frontend/static/css/build_css.ps1`

---

## Chat Input Area — Current Values

| Element | Property | Value |
|---------|----------|-------|
| .chat-input-area | padding | 0.74vw 1.35vw 0.34vw |
| .chat-glow-line | height | 0.08vw |
| .chat-input-wrapper | max-width | 35vw |
| .chat-input-wrapper | border-radius | 0.6vw |
| .chat-input-wrapper | padding | 0.16vw 0.16vw 0.16vw 0.95vw |
| .chat-input-wrapper | gap | 0.6vw |
| .chat-input | font-size | 0.7vw |
| .chat-input | padding | 0.32vw 0 |
| .chat-send-btn | width/height | 1.76vw |
| .chat-send-btn | border-radius | 0.47vw |
| .chat-send-btn svg | width/height | 0.78vw |
| .chat-disclaimer | font-size | 0.54vw |
| .chat-disclaimer | margin-top | 0.47vw |
| .autocomplete-item | padding | 0.54vw 0.95vw |
| .autocomplete-item | gap | 0.54vw |
| .autocomplete-item | border-radius | 0.54vw |
| .autocomplete-icon | width/height | 0.85vw |
| .autocomplete-text | font-size | 0.74vw |

---

## Change Log

### Session 1 (Feb 2026)
1. Shrunk entire input area ~75% from original
2. Shrunk input box height, send icon, autocomplete popup further ~80%
3. Increased space between glow line and input box (top padding 0.18→0.55vw)
4. Scaled everything up ~15%
5. Scaled everything up 35% (near-original proportions)
6. Increased glow line height (0.04→0.08vw)
