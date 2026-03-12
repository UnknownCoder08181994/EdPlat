"""Prompt template for the task description reformatter.

Used when creating a new task -- rewrites rough user descriptions
into clear, scoped project briefs for the SDD agent pipeline.

Strategy: two-shot few-shot examples teach the model the desired
output FORMAT without contaminating the user's actual idea. The
examples are intentionally in different domains than what users
typically ask for, so the model pattern-matches on structure, not
content.

Key design principles:
  1. PRESERVE the user's intent -- never replace their idea
  2. Output what the REQUIREMENTS step needs: what the app does,
     who it's for, key features, constraints. NOT function signatures.
  3. Scale detail by complexity tier
  4. Only fall back to prebuilt specs for truly empty/gibberish input
"""

import random


# ── Vague-input detection ───────────────────────────────────────────
# Only triggers for truly useless input -- not "short but specific"
_TRULY_VAGUE = [
    'something cool', 'something useful', 'something interesting',
    'code for me', 'program for me', 'script for me',
    'idk', 'anything', 'whatever', 'surprise me',
]


def is_vague_input(details: str) -> bool:
    """Return True only if the input is genuinely unusable.

    This is much stricter than before. "Build a task manager" is NOT
    vague -- it has a clear intent. Only truly empty or gibberish
    inputs trigger the prebuilt fallback.
    """
    low = details.lower().strip()
    words = low.split()

    # Fewer than 3 words with no real nouns = useless
    if len(words) < 3:
        return True

    # Matches a truly vague phrase with nothing else useful
    if any(v in low for v in _TRULY_VAGUE) and len(words) < 8:
        return True

    return False


# ── Pre-built specs by complexity tier ──────────────────────────────
# These ONLY fire for truly vague input. They are diverse: CLI, web,
# games, data tools -- not just Python CLI scripts.

_PREBUILT_BASIC = [
    (
        "Build a password generator that creates random passwords of a "
        "user-specified length. It should support options for including "
        "uppercase, lowercase, digits, and special characters. Run it "
        "from the command line."
    ),
    (
        "Build a simple quiz game that asks the player multiple-choice "
        "questions, tracks their score, and shows results at the end. "
        "Load questions from a JSON file."
    ),
    (
        "Build a unit converter that handles common conversions: "
        "temperature (Celsius/Fahrenheit/Kelvin), distance (miles/km), "
        "and weight (lbs/kg). Run it from the command line."
    ),
    (
        "Build a Markdown-to-HTML converter that reads a .md file and "
        "outputs a styled HTML page. Support headings, bold, italic, "
        "links, and code blocks."
    ),
    (
        "Build a personal diary application that lets users write, "
        "list, and search daily entries. Store entries as text files "
        "organized by date."
    ),
]

_PREBUILT_INTERMEDIATE = [
    (
        "Build a Flask web application that serves as a bookmark manager. "
        "Users can add URLs with tags and descriptions, browse bookmarks by "
        "tag, search across all bookmarks, and delete entries. Store data in "
        "a SQLite database. The UI should be a clean, responsive HTML page "
        "with a form for adding bookmarks and a filterable list view."
    ),
    (
        "Build a file organizer tool that watches a directory and "
        "automatically sorts files into categorized subfolders based on "
        "file extension (images, documents, code, archives, etc). Include "
        "a dry-run mode that previews changes without moving anything, and "
        "handle edge cases like duplicate filenames and permission errors."
    ),
    (
        "Build a weather dashboard that fetches forecast data from a "
        "public API and displays current conditions plus a 5-day outlook. "
        "The user enters a city name and sees temperature, humidity, wind "
        "speed, and conditions. Include error handling for invalid cities "
        "and network failures."
    ),
    (
        "Build a command-line expense tracker that lets users log expenses "
        "with amount, category, and date, then view summaries grouped by "
        "category or month. Store data in a JSON file. Include a budget "
        "warning feature that alerts when spending in a category exceeds "
        "a configurable limit."
    ),
]

_PREBUILT_ADVANCED = [
    (
        "Build a project management web application using Flask with a "
        "kanban-style board. Users can create projects, add tasks with "
        "titles and descriptions, drag tasks between columns (To Do, In "
        "Progress, Done), and assign priority levels. Store all data in "
        "SQLite. The frontend should use vanilla JavaScript for the drag-"
        "and-drop interface. Include user authentication with login/logout "
        "and per-user project isolation."
    ),
    (
        "Build a REST API for a recipe sharing platform. Users can create "
        "accounts, post recipes with ingredients and step-by-step "
        "instructions, search recipes by ingredient or cuisine type, and "
        "rate other users' recipes. Use Flask with SQLite. Include input "
        "validation, pagination for search results, and proper error "
        "responses. Serve a simple HTML frontend that consumes the API."
    ),
]

_PREBUILT_EXPERT = [
    (
        "Build a real-time chat application with rooms and direct messaging. "
        "Use Flask with Flask-SocketIO for WebSocket communication. Users "
        "should be able to create an account, join chat rooms, send messages "
        "that appear instantly for all participants, and send private "
        "messages to specific users. Store message history and user data in "
        "SQLite. The frontend should be a responsive single-page interface "
        "showing the room list, active users, and a message feed. Include "
        "typing indicators, message timestamps, and basic moderation "
        "(kick/ban from rooms)."
    ),
    (
        "Build a personal finance dashboard web application. Users can "
        "connect bank transaction data via CSV import, categorize "
        "transactions automatically using keyword rules, view spending "
        "breakdown charts by category and time period, set monthly budgets "
        "per category with visual progress bars, and export reports. Use "
        "Flask with SQLite for the backend and Chart.js for visualizations. "
        "Include user authentication and per-user data isolation."
    ),
]


def get_prebuilt_spec(*, complexity: int) -> str:
    """Return a random pre-written spec for the given complexity tier."""
    if complexity <= 3:
        return random.choice(_PREBUILT_BASIC)
    elif complexity <= 5:
        return random.choice(_PREBUILT_INTERMEDIATE)
    elif complexity <= 7:
        return random.choice(_PREBUILT_ADVANCED)
    else:
        return random.choice(_PREBUILT_EXPERT)


def build(*, complexity: int) -> tuple:
    """Return (system_content, user_preamble, shot_a_input, shot_a_output) for the reformat LLM call.

    The few-shot examples teach the model the desired OUTPUT FORMAT
    without influencing the user's actual project idea. Examples are
    deliberately in different domains so the model learns structure,
    not content.

    Args:
        complexity: 1-10 score from the UI slider.

    Returns:
        Tuple of (system_content, user_preamble, shot_a_input, shot_a_output)
        for the multi-turn LLM conversation.
    """
    # ── Tier definitions ────────────────────────────────────────────
    # Each tier has TWO few-shot examples. shot_a is used in the
    # assistant turn for pattern-matching. shot_b is available for
    # the routes to add as a second example turn if desired.

    if complexity <= 3:
        level = "basic"

        shot_a_input = "i want to track my daily water intake"
        shot_a_output = (
            "Build a daily water intake tracker. The user can log glasses "
            "of water throughout the day, see their running total, and get "
            "a reminder if they haven't logged anything in the last 2 hours. "
            "Show a simple daily summary at the end of the day."
        )

        shot_b_input = "something to help me study"
        shot_b_output = (
            "Build a flashcard study tool. The user can create decks of "
            "question-and-answer cards, quiz themselves with randomized "
            "order, and track which cards they get right or wrong. Show "
            "a score summary after each session."
        )

    elif complexity <= 5:
        level = "intermediate"

        shot_a_input = "i need something to manage my recipes"
        shot_a_output = (
            "Build a recipe management application where users can add "
            "recipes with a title, ingredient list, and step-by-step "
            "cooking instructions. Users should be able to browse all "
            "recipes, search by ingredient or name, and tag recipes with "
            "categories like 'breakfast', 'dinner', or 'dessert'. Include "
            "a feature to scale ingredient quantities up or down based on "
            "serving size. Store recipe data persistently so it survives "
            "restarts. Handle edge cases like duplicate recipe names and "
            "missing required fields."
        )

        shot_b_input = "make an app for my book collection"
        shot_b_output = (
            "Build a personal library manager where users can catalog their "
            "books with title, author, genre, and reading status (unread, "
            "reading, finished). Users should be able to search and filter "
            "their collection, mark books as favorites, and see reading "
            "statistics like total books read per month. Include the ability "
            "to import book data from a CSV file and export the full catalog. "
            "Store all data persistently and handle duplicates gracefully."
        )

    elif complexity <= 7:
        level = "advanced"

        shot_a_input = "build me a tool for my team's standups"
        shot_a_output = (
            "Build a team standup web application where team members can "
            "post daily updates with three sections: what they did yesterday, "
            "what they plan to do today, and any blockers. The app should "
            "display a timeline view showing all team members' updates for "
            "a given day, with the ability to browse past days. Include user "
            "accounts so each person logs in and sees their team's board. "
            "Add a summary feature that aggregates blockers across the team "
            "and highlights anyone who missed their update. Use a database "
            "for persistence and serve a clean web interface. Handle timezone "
            "differences so 'today' is correct for each user."
        )

        shot_b_input = "i want to track bugs in my projects"
        shot_b_output = (
            "Build a bug tracker web application where users can create "
            "projects, report bugs with title, description, severity level, "
            "and steps to reproduce, and track bug status through a workflow "
            "(Open, In Progress, Resolved, Closed). Each project has its own "
            "bug list with filtering by severity and status. Include a "
            "dashboard showing open bug counts per project, recent activity, "
            "and overdue items. Support assigning bugs to team members and "
            "adding comments to bug reports. Use a database for storage and "
            "serve a responsive web interface. Handle permission levels so "
            "project owners can manage their team's access."
        )

    else:
        level = "expert"

        shot_a_input = "build a platform for online courses"
        shot_a_output = (
            "Build an online course platform web application where "
            "instructors can create courses with modules and lessons, "
            "upload content for each lesson, and organize the curriculum "
            "in a structured order. Students can browse available courses, "
            "enroll, and track their progress through each course with a "
            "visual progress bar. Include a quiz system where instructors "
            "can add multiple-choice questions at the end of each module, "
            "and students see their scores and can retake quizzes. The "
            "platform needs user authentication with two roles (instructor "
            "and student), a dashboard for each role showing relevant "
            "information, and a discussion forum per course where students "
            "and instructors can interact. Store all data in a relational "
            "database. The frontend should be a responsive web interface "
            "that works on desktop and mobile. Handle concurrent enrollments, "
            "large file uploads, and proper access control so students can "
            "only view courses they are enrolled in."
        )

        shot_b_input = "i want a project planning tool"
        shot_b_output = (
            "Build a project planning and collaboration web application "
            "where teams can create projects with milestones and tasks, "
            "assign tasks to team members with due dates and priority "
            "levels, and track progress on a kanban board with customizable "
            "columns. Include a Gantt chart view that visualizes task "
            "dependencies and timelines, and a calendar view showing "
            "upcoming deadlines. Teams should have a shared activity feed "
            "showing recent changes, and each task should support comments, "
            "file attachments, and checklists. The platform needs user "
            "authentication with roles (admin, member, viewer), email "
            "notifications for assignment changes and approaching deadlines, "
            "and a reporting dashboard showing team velocity, overdue tasks, "
            "and completion rates. Store data in a relational database and "
            "serve a responsive web interface. Handle concurrent edits to "
            "the same task and timezone-aware deadline tracking."
        )

    # ── Build prompt (scales by tier) ──────────────────────────────
    if complexity <= 3:
        system_content = (
            "You rewrite rough task descriptions into clear project briefs. "
            "Use only plain ASCII text. Output 2-4 sentences describing WHAT "
            "to build and the key user-facing features. Do NOT include "
            "function names, library choices, file structures, or error "
            "handling details -- those decisions come later. Just describe "
            "the project at a high level, like explaining it to someone who "
            "will design the technical approach themselves.\n"
        )
        user_preamble = (
            f"Rewrite this task as a clear BASIC ({complexity}/10) project brief. "
            f"2-4 sentences. Describe WHAT to build and key features only:\n\n"
        )
    else:
        system_content = (
            "You rewrite rough task descriptions into clear, well-structured "
            "project briefs. Use only plain ASCII text. Output plain prose "
            "paragraphs describing: what the application does, who uses it, "
            "the key features and user flows, what data it manages, and any "
            "important constraints or requirements. Do NOT include function "
            "signatures, specific library choices, file structures, class "
            "names, or error handling details -- those decisions happen in "
            "later design phases. Describe the project like a product brief "
            "that a developer will use to design the architecture themselves. "
            "NEVER use code blocks, markdown, tables, or bullet lists.\n"
        )
        user_preamble = (
            f"Rewrite this task as a clear {level.upper()} ({complexity}/10) "
            f"project brief. Describe what to build, key features, and "
            f"constraints. Plain prose paragraphs only:\n\n"
        )

    return system_content, user_preamble, shot_a_input, shot_a_output
