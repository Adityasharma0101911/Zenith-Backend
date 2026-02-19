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

# system prompts for each ai section
SYSTEM_PROMPTS = {
    "scholar": (
        "You are Zenith Scholar, an intellectual AI tutor. "
        "You help students study effectively, break down complex concepts, "
        "create study plans, and provide learning strategies. "
        "You are encouraging, structured, and use clear explanations with examples. "
        "Always provide actionable steps. Use bullet points and numbered lists when helpful. "
        "Keep responses concise but thorough."
    ),
    "guardian": (
        "You are Zenith Guardian, a financial wellness AI advisor. "
        "You help users manage money wisely, create budgets, understand spending patterns, "
        "and make smart financial decisions. "
        "You are protective, thoughtful, and always prioritize financial health. "
        "Provide specific actionable advice. Be reassuring when users are stressed about money. "
        "Keep responses concise and practical."
    ),
    "vitals": (
        "You are Zenith Vitals, a physical health and wellness AI coach. "
        "You help users improve exercise habits, sleep quality, nutrition, "
        "and overall physical wellness. "
        "You are motivating, knowledgeable, and provide evidence-based recommendations. "
        "Adapt suggestions to the user's fitness level and health goals. "
        "Keep responses encouraging and actionable."
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
                "system_prompt": SYSTEM_PROMPTS.get(section, "You are a helpful AI assistant."),
            },
            headers=get_headers(),
            timeout=15,
        )
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
        print(f"[AI] send_message status={res.status_code}")
        data = res.json()
        # try multiple possible response fields
        return data.get("content") or data.get("message") or data.get("response") or data.get("text") or "Sorry, I couldn't process that right now."
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

# main function to chat with the ai for a given section
def chat_with_ai(user_id, section, message, survey_data=None):
    thread_id, initialized = get_or_create_thread(user_id, section)

    if not thread_id:
        return "Sorry, the AI service is currently unavailable."

    # send user context as first message if thread is new
    if not initialized and survey_data:
        context = build_context_message(section, survey_data)
        if context:
            send_message(
                thread_id,
                f"[User Profile] {context}. Remember this about me for all our conversations.",
            )
            # mark thread as initialized
            conn = get_db_connection()
            conn.execute(
                "UPDATE user_threads SET initialized = 1 WHERE user_id = ? AND assistant_name = ?",
                (user_id, section),
            )
            conn.commit()
            conn.close()

    # send the actual user message
    return send_message(thread_id, message)
