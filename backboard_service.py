# handles all backboard.io ai api communication

import requests
import os
from database import get_db_connection

# base url read at call time so env vars are loaded
def get_base_url():
    return os.getenv("BACKBOARD_BASE_URL", "https://app.backboard.io/api")

# returns auth headers for backboard
def get_headers():
    return {"X-API-Key": os.getenv("BACKBOARD_API_KEY")}

# system prompts for each ai section — jarvis-style: conversational, no markdown
SYSTEM_PROMPTS = {
    "scholar": (
        "You are Zenith Scholar, an intelligent AI tutor inspired by JARVIS from Iron Man. "
        "Speak in a warm, conversational tone — like a brilliant friend explaining things over coffee. "
        "Never use markdown formatting (no **, no ##, no bullet points, no numbered lists). "
        "Write in flowing natural paragraphs. Be concise — 2 to 4 sentences per response unless more is needed. "
        "Give clear, actionable advice woven naturally into your speech. "
        "You're encouraging and sharp, not robotic."
    ),
    "guardian": (
        "You are Zenith Guardian, a financial wellness AI advisor inspired by JARVIS from Iron Man. "
        "Speak in a calm, reassuring, conversational tone — like a trusted advisor who genuinely cares. "
        "Never use markdown formatting (no **, no ##, no bullet points, no numbered lists). "
        "Write in flowing natural paragraphs. Be concise — 2 to 4 sentences per response unless more is needed. "
        "Weave specific financial advice naturally into your speech. "
        "Be protective and thoughtful, not preachy."
    ),
    "vitals": (
        "You are Zenith Vitals, a health and wellness AI coach inspired by JARVIS from Iron Man. "
        "Speak in a motivating, conversational tone — like a knowledgeable trainer who knows you well. "
        "Never use markdown formatting (no **, no ##, no bullet points, no numbered lists). "
        "Write in flowing natural paragraphs. Be concise — 2 to 4 sentences per response unless more is needed. "
        "Give evidence-based advice woven naturally into your speech. "
        "Be encouraging and real, not clinical."
    ),
}

# friendly names for each assistant
ASSISTANT_NAMES = {
    "scholar": "Zenith Scholar",
    "guardian": "Zenith Guardian",
    "vitals": "Zenith Vitals",
}

# gets existing assistant or creates a new one on backboard
def get_or_create_assistant(section):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT assistant_id FROM ai_assistants WHERE name = ?", (section,)
    ).fetchone()
    conn.close()

    if row:
        return row["assistant_id"]

    # create a new assistant via backboard api (db closed during http call)
    try:
        res = requests.post(
            f"{get_base_url()}/assistants",
            json={
                "name": ASSISTANT_NAMES.get(section, section),
                "model": "gpt-4o",
                "system_prompt": SYSTEM_PROMPTS.get(section, "You are a helpful AI assistant."),
            },
            headers=get_headers(),
            timeout=15,
        )
        print(f"[AI] create_assistant status={res.status_code} body={res.text[:200]}")
        data = res.json()
        assistant_id = data.get("assistant_id") or data.get("id")

        if assistant_id:
            conn2 = get_db_connection()
            conn2.execute(
                "INSERT OR REPLACE INTO ai_assistants (name, assistant_id) VALUES (?, ?)",
                (section, assistant_id),
            )
            conn2.commit()
            conn2.close()
            return assistant_id
    except Exception as e:
        print(f"Error creating assistant: {e}")

    return None

# gets existing thread or creates a new one for user+section
def get_or_create_thread(user_id, section):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT thread_id, initialized FROM user_threads WHERE user_id = ? AND assistant_name = ?",
        (user_id, section),
    ).fetchone()
    conn.close()

    if row:
        return row["thread_id"], bool(row["initialized"])

    # get or create the assistant first
    assistant_id = get_or_create_assistant(section)
    if not assistant_id:
        return None, False

    # create a thread under the assistant (db closed during http call)
    try:
        res = requests.post(
            f"{get_base_url()}/assistants/{assistant_id}/threads",
            json={},
            headers=get_headers(),
            timeout=15,
        )
        print(f"[AI] create_thread status={res.status_code} body={res.text[:200]}")
        data = res.json()
        thread_id = data.get("thread_id") or data.get("id")

        if thread_id:
            conn2 = get_db_connection()
            conn2.execute(
                "INSERT OR REPLACE INTO user_threads (user_id, assistant_name, thread_id, initialized) VALUES (?, ?, ?, 0)",
                (user_id, section, thread_id),
            )
            conn2.commit()
            conn2.close()
            return thread_id, False
    except Exception as e:
        print(f"Error creating thread: {e}")

    return None, False

# sends a message to a thread and returns the ai response
def send_message(thread_id, content):
    try:
        res = requests.post(
            f"{get_base_url()}/threads/{thread_id}/messages",
            headers=get_headers(),
            json={"content": content, "stream": False},
            timeout=30,
        )
        print(f"[AI] send_message status={res.status_code} body={res.text[:300]}")
        if res.status_code != 200:
            return "Sorry, the AI returned an error. Please try again."
        data = res.json()
        # try multiple possible response fields
        raw = data.get("content") or data.get("message") or data.get("response") or data.get("text") or "Sorry, I couldn't process that right now."
        # strip any markdown formatting the model sneaks in
        import re
        cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', raw)   # bold
        cleaned = re.sub(r'__(.+?)__', r'\1', cleaned)     # bold alt
        cleaned = re.sub(r'\*(.+?)\*', r'\1', cleaned)     # italic
        cleaned = re.sub(r'^#{1,6}\s+', '', cleaned, flags=re.MULTILINE)  # headings
        cleaned = re.sub(r'^[\-\*]\s+', '', cleaned, flags=re.MULTILINE)  # bullet points
        return cleaned
    except Exception as e:
        print(f"Error sending message: {e}")
        return "Sorry, the AI is temporarily unavailable. Please try again."

# builds a context string from the user's survey data for the ai
def build_context_message(section, survey_data):
    if not survey_data:
        return ""

    parts = [f"User: {survey_data.get('name', 'User')}"]
    age = survey_data.get("age_range", "")
    if age:
        parts.append(f"Age: {age}")
    occ = survey_data.get("occupation", "")
    if occ:
        parts.append(f"Occupation: {occ}")

    # add section-specific context
    if section == "scholar":
        parts.append(f"Education: {survey_data.get('education_level', 'N/A')}")
        subjects = survey_data.get("subjects", [])
        if subjects:
            parts.append(f"Interests: {', '.join(subjects)}")
        parts.append(f"Learning style: {survey_data.get('learning_style', 'N/A')}")
        goals = survey_data.get("study_goals", [])
        if goals:
            parts.append(f"Study goals: {', '.join(goals)}")

    elif section == "guardian":
        parts.append(f"Spending profile: {survey_data.get('spending_profile', 'N/A')}")
        parts.append(f"Income: {survey_data.get('income_range', 'N/A')}")
        parts.append(f"Savings: {survey_data.get('savings', 'N/A')}")
        goals = survey_data.get("financial_goals", [])
        if goals:
            parts.append(f"Financial goals: {', '.join(goals)}")
        parts.append(f"Balance: ${survey_data.get('balance', 0)}")

    elif section == "vitals":
        parts.append(f"Exercise: {survey_data.get('exercise_frequency', 'N/A')}")
        parts.append(f"Sleep: {survey_data.get('sleep_quality', 'N/A')}")
        parts.append(f"Diet: {survey_data.get('diet_quality', 'N/A')}")
        goals = survey_data.get("health_goals", [])
        if goals:
            parts.append(f"Health goals: {', '.join(goals)}")
        parts.append(f"Stress: {survey_data.get('stress_level', 'N/A')}/10")

    return " | ".join(parts)

# clears cached assistant and thread data so they get recreated with fresh settings
def reset_ai_cache():
    conn = get_db_connection()
    conn.execute("DELETE FROM ai_assistants")
    conn.execute("DELETE FROM user_threads")
    conn.commit()
    conn.close()
    print("[AI] cleared assistant and thread cache")

# main function to chat with the ai for a given section
def chat_with_ai(user_id, section, message, survey_data=None):
    thread_id, initialized = get_or_create_thread(user_id, section)

    if not thread_id:
        return "Sorry, the AI service is currently unavailable."

    # send user context as first message if thread is new (one-time cost)
    if not initialized and survey_data:
        context = build_context_message(section, survey_data)
        if context:
            send_message(
                thread_id,
                f"[User Profile] {context}. Remember this about me for all our conversations.",
            )
            # mark thread as initialized so we never resend context
            conn = get_db_connection()
            conn.execute(
                "UPDATE user_threads SET initialized = 1 WHERE user_id = ? AND assistant_name = ?",
                (user_id, section),
            )
            conn.commit()
            conn.close()

    # send the actual user message (no aggressive retry to save tokens)
    result = send_message(thread_id, message)
    return result
