"""Deterministic stub LLM engine.

Replaces the GPU-based Qwen2.5-3B-Instruct engine with a deterministic
text generator that produces contextual responses. No GPU or model files
needed — perfect for development, testing, and demos.

Interface matches the real engine exactly:
- get_llm_engine() → singleton LLMEngine
- engine.stream_chat(messages, max_new_tokens, temperature, cancel_event) → generator[str]
- engine.count_tokens(messages) → int
- LLMEngine.force_cancel() → class method
"""

import json
import time
import re
import threading

# Module-level cancel event for force_cancel()
_global_cancel_event = threading.Event()

# Singleton instance
_engine_instance = None
_engine_lock = threading.Lock()


def get_llm_engine():
    """Return the singleton LLMEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = LLMEngine()
    return _engine_instance


class LLMEngine:
    """Deterministic stub that mimics real LLM streaming behavior."""

    def __init__(self):
        self._cancel_event = None

    @classmethod
    def force_cancel(cls):
        """Force-cancel any in-flight generation. Returns True if signalled."""
        _global_cancel_event.set()
        # Wait briefly for acknowledgment
        time.sleep(0.1)
        _global_cancel_event.clear()
        return True

    def count_tokens(self, messages):
        """Estimate token count from messages (heuristic: ~4 chars per token)."""
        total_chars = sum(len(m.get('content', '')) for m in messages)
        return total_chars // 4

    def stream_chat(self, messages, max_new_tokens=4096, temperature=0.7, cancel_event=None):
        """Stream response tokens word-by-word with realistic delays.

        Examines the conversation to produce contextual responses:
        - For step chats: generates valid <tool_code> blocks with WriteFile
        - For tool results: responds with acknowledgment or [STEP_COMPLETE]
        - For general chat: produces a helpful conversational response
        """
        self._cancel_event = cancel_event

        # Find the last user message (skip tool results for context)
        last_user_msg = ""
        last_is_tool_result = False
        step_id = None

        for msg in reversed(messages):
            if msg['role'] == 'user':
                content = msg['content']
                if content.startswith('Tool Result:'):
                    last_is_tool_result = True
                    last_user_msg = content
                    break
                else:
                    last_user_msg = content
                    break

        # Extract step_id from system prompt
        system_msg = messages[0]['content'] if messages and messages[0]['role'] == 'system' else ''
        step_match = re.search(r'## Current Step:\s*(.+)', system_msg)
        if step_match:
            step_name = step_match.group(1).strip()
            step_id = step_name.lower().replace(' ', '-')
        # Determine task details from system prompt
        task_match = re.search(r'## Task\n(.*?)(?:\n##|\Z)', system_msg, re.DOTALL)
        task_details = task_match.group(1).strip() if task_match else "the requested feature"

        # Generate response based on context
        response = self._generate_response(
            step_id, last_user_msg, last_is_tool_result, task_details, system_msg
        )

        # Stream word-by-word with realistic delays
        words = response.split(' ')
        for i, word in enumerate(words):
            # Check cancellation
            if cancel_event and cancel_event.is_set():
                return
            if _global_cancel_event.is_set():
                return

            token = word if i == 0 else ' ' + word
            yield token
            time.sleep(0.04)  # 40ms per word — feels natural

    def _generate_response(self, step_id, last_msg, is_tool_result, task_details, system_msg):
        """Generate a contextual response based on the current step and message."""
        # If last message was a successful tool result, check if we should complete
        if is_tool_result and 'Successfully wrote' in last_msg:
            return (
                "The file has been saved successfully. I've completed all the work "
                "for this step.\n\n[STEP_COMPLETE]"
            )

        # If last message was a tool result (file listing, read, etc.), continue working
        if is_tool_result and not 'Successfully wrote' in last_msg:
            return self._generate_tool_followup(step_id, last_msg, task_details)

        # If this is a stall nudge, generate a tool call
        if 'Continue working' in last_msg and 'Use tools' in last_msg:
            return self._generate_for_step(step_id, task_details)

        # Generate based on step type
        if step_id:
            return self._generate_for_step(step_id, task_details)

        # General chat (no step context)
        return (
            f"I'd be happy to help you with that! Let me think about the best approach.\n\n"
            f"Based on what you've described, here's my analysis:\n\n"
            f"1. **Understanding**: I've reviewed your request and identified the key requirements.\n"
            f"2. **Approach**: I recommend starting with the core functionality and iterating from there.\n"
            f"3. **Next Steps**: Let me know if you'd like me to elaborate on any specific aspect.\n\n"
            f"Would you like me to dive deeper into any of these areas?"
        )

    def _generate_for_step(self, step_id, task_details):
        """Generate a response appropriate for the current workflow step."""
        short_desc = task_details[:200] if len(task_details) > 200 else task_details
        if step_id == 'requirements':
            content = self._build_requirements_doc(short_desc)
            return (
                f"Let me analyze the task description to create a comprehensive Product Requirements Document. "
                f"The task is: {short_desc}. I need to identify the core requirements, define user stories, "
                f"and establish clear acceptance criteria. Let me think about what users would expect "
                f"from this feature and what edge cases we need to handle.\n\n"
                + self._build_tool_call("WriteFile", {"path": "requirements.md", "content": content})
            )

        elif step_id == 'technical-specification':
            content = self._build_spec_doc(short_desc)
            return (
                f"I've reviewed the requirements document and now I need to design the technical architecture. "
                f"For {short_desc}, I need to consider the technology stack, data models, API design, "
                f"and how the components will interact. Let me create a detailed technical specification "
                f"that covers all the implementation details.\n\n"
                + self._build_tool_call("WriteFile", {"path": "spec.md", "content": content})
            )

        elif step_id == 'planning':
            content = self._build_planning_doc(short_desc)
            return (
                f"I've reviewed the requirements and technical specification. Now I need to break down "
                f"the implementation into concrete, actionable tasks. Each task should be small enough to "
                f"complete in a focused session but large enough to represent a meaningful unit of work. "
                f"Let me create the implementation plan.\n\n"
                + self._build_tool_call("WriteFile", {"path": "implementation-plan.md", "content": content})
            )

        else:
            # Implementation step — go straight to writing main.py
            content = self._build_implementation(short_desc)
            return (
                f"I've reviewed the requirements, technical specification, and implementation plan. "
                f"Now I'll create the main application file for: {short_desc}\n\n"
                + self._build_tool_call("WriteFile", {"path": "main.py", "content": content})
            )

    def _generate_tool_followup(self, step_id, tool_result, task_details):
        """Generate a follow-up after receiving a tool result."""
        short_desc = task_details[:200] if len(task_details) > 200 else task_details

        # Check if the tool result indicates an error
        is_error = 'Error' in tool_result and 'Successfully' not in tool_result

        # SDD steps: if error, retry the correct artifact file
        if step_id == 'requirements':
            if is_error:
                content = self._build_requirements_doc(short_desc)
                return (
                    f"The previous attempt had an error. Let me retry writing the requirements document "
                    f"with the correct filename and format.\n\n"
                    + self._build_tool_call("WriteFile", {"path": "requirements.md", "content": content})
                )
            return (
                f"I've reviewed the workspace contents and completed my analysis. "
                f"All the necessary work for this step has been done.\n\n[STEP_COMPLETE]"
            )

        elif step_id == 'technical-specification':
            if is_error:
                content = self._build_spec_doc(short_desc)
                return (
                    f"The previous attempt had an error. Let me retry writing the technical specification.\n\n"
                    + self._build_tool_call("WriteFile", {"path": "spec.md", "content": content})
                )
            return (
                f"I've completed my analysis. All work for this step is done.\n\n[STEP_COMPLETE]"
            )

        elif step_id == 'planning':
            if is_error:
                content = self._build_planning_doc(short_desc)
                return (
                    f"The previous attempt had an error. Let me retry writing the implementation plan.\n\n"
                    + self._build_tool_call("WriteFile", {"path": "implementation-plan.md", "content": content})
                )
            return (
                f"I've completed the planning step.\n\n[STEP_COMPLETE]"
            )

        else:
            # Implementation step — create main.py with task-relevant code
            content = self._build_implementation(short_desc)
            return (
                f"I can see the workspace contents. Now I understand the project structure. "
                f"Based on the implementation plan, I'll create the main application file "
                f"for: {short_desc}\n\n"
                + self._build_tool_call("WriteFile", {"path": "main.py", "content": content})
            )

    def _build_requirements_doc(self, task_desc):
        return (
            f"# Product Requirements Document\n\n"
            f"## Overview\n"
            f"{task_desc}\n\n"
            f"## User Stories\n\n"
            f"### US-1: Core Functionality\n"
            f"As a user, I want the system to address: {task_desc} — so that the core goal is met.\n\n"
            f"### US-2: Output Quality\n"
            f"As a user, I want the output to be well-structured and relevant to my request.\n\n"
            f"### US-3: Error Handling\n"
            f"As a user, I want clear error messages so that I understand what went wrong and how to fix it.\n\n"
            f"## Acceptance Criteria\n\n"
            f"1. The program correctly addresses the task: {task_desc}\n"
            f"2. Output is clear, readable, and well-formatted\n"
            f"3. The program runs without errors on Python 3.10+\n"
            f"4. Edge cases are handled gracefully\n\n"
            f"## Assumptions\n\n"
            f"- Python 3.10+ standard library\n"
            f"- Command-line interface for interaction\n"
            f"- No external dependencies required\n"
        )

    def _build_spec_doc(self, task_desc):
        return (
            f"# Technical Specification\n\n"
            f"## Overview\n"
            f"Technical design for: {task_desc}\n\n"
            f"## Technology Stack\n"
            f"- **Language**: Python 3.10+\n"
            f"- **Dependencies**: Standard library only\n"
            f"- **Testing**: Manual verification via command line\n\n"
            f"## Architecture\n\n"
            f"### Project Structure\n"
            f"```\n"
            f"main.py          # Application entry point\n"
            f"```\n\n"
            f"### Module Design\n"
            f"The application is implemented as a single Python script (`main.py`) "
            f"that addresses the task: {task_desc}\n\n"
            f"### Key Functions\n"
            f"| Function | Purpose |\n"
            f"|----------|----------|\n"
            f"| main() | Entry point — orchestrates the program flow |\n"
            f"| process() | Core logic for handling the task |\n"
            f"| display_output() | Formats and presents results to the user |\n\n"
            f"## Design Decisions\n"
            f"- Single-file architecture for simplicity\n"
            f"- No external dependencies — uses only the Python standard library\n"
            f"- Clean separation of concerns via functions\n"
        )

    def _build_planning_doc(self, task_desc):
        return (
            f"# Implementation Plan\n\n"
            f"## Overview\n"
            f"Implementation plan for: {task_desc}\n\n"
            f"## Tasks\n\n"
            f"### Task 1: Core Logic\n"
            f"- [ ] Create main.py with entry point\n"
            f"- [ ] Implement the core logic for: {task_desc}\n"
            f"- [ ] Add helper functions as needed\n\n"
            f"### Task 2: Output & Formatting\n"
            f"- [ ] Format output to be clear and readable\n"
            f"- [ ] Add appropriate headers and labels\n"
            f"- [ ] Ensure output matches the task requirements\n\n"
            f"### Task 3: Error Handling & Polish\n"
            f"- [ ] Add input validation where applicable\n"
            f"- [ ] Handle edge cases gracefully\n"
            f"- [ ] Verify the program runs end-to-end without errors\n"
        )

    def _build_implementation(self, task_desc):
        # Build a simple, task-relevant Python script
        safe_desc = task_desc.replace('"', '\\"').replace("'", "\\'")
        return (
            f"#!/usr/bin/env python3\n"
            f'"""Application: {safe_desc}"""\n\n'
            f"import sys\n\n\n"
            f"def process(task_input):\n"
            f'    """Core logic for: {safe_desc}"""\n'
            f"    result = []\n"
            f'    result.append(f"Processing: {{task_input}}")\n'
            f'    result.append("")\n'
            f'    result.append("--- Output ---")\n'
            f'    result.append(f"Task: {safe_desc}")\n'
            f'    result.append("Status: Complete")\n'
            f'    result.append(f"Input received: {{task_input}}")\n'
            f"    return result\n\n\n"
            f"def display_output(lines):\n"
            f'    """Format and display results."""\n'
            f"    for line in lines:\n"
            f"        print(line)\n\n\n"
            f"def main():\n"
            f'    """Entry point."""\n'
            f'    print(f"=== {safe_desc} ===")\n'
            f"    print()\n"
            f'    task_input = input("Enter your input: ") if len(sys.argv) < 2 else sys.argv[1]\n'
            f"    results = process(task_input)\n"
            f"    display_output(results)\n"
            f"    print()\n"
            f'    print("Done!")\n\n\n'
            f'if __name__ == "__main__":\n'
            f"    main()\n"
        )

    def _build_tool_call(self, name, arguments):
        """Build a <tool_code> block with properly serialized JSON.

        Uses json.dumps to ensure all string values are correctly escaped,
        avoiding the double-escaping bugs that manual escaping can cause.
        """
        tool_obj = {"name": name, "arguments": arguments}
        return f"<tool_code>\n{json.dumps(tool_obj)}\n</tool_code>"
