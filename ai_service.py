# legacy ai advice function (kept for the dashboard insight card)

import os
import requests

# provides a quick one-line insight for the dashboard
def get_ai_advice(spending_profile, balance, stress):
    api_key = os.getenv("BACKBOARD_API_KEY")
    base_url = os.getenv("BACKBOARD_BASE_URL", "https://app.backboard.io/api")

    prompt = (
        f"You are Zenith, an AI wellness guardian. "
        f"The user has a '{spending_profile}' spending profile, ${balance} balance, "
        f"and stress level {stress}/10. "
        f"Provide one short sentence of actionable advice protecting their financial and mental well-being."
    )

    # fallback if no api key
    if not api_key:
        return f"Zenith AI: With stress at {stress}/10, consider a mindful pause before financial decisions today."

    try:
        # create a quick one-off thread for the insight
        headers = {"X-API-Key": api_key}

        # use the guardian assistant if it exists
        from database import get_db_connection
        conn = get_db_connection()
        row = conn.execute("SELECT assistant_id FROM ai_assistants WHERE name = 'guardian'").fetchone()
        conn.close()

        if row:
            # create a temporary thread
            res = requests.post(
                f"{base_url}/assistants/{row['assistant_id']}/threads",
                json={},
                headers=headers,
                timeout=10,
            )
            thread_id = res.json().get("thread_id") or res.json().get("id")

            if thread_id:
                res = requests.post(
                    f"{base_url}/threads/{thread_id}/messages",
                    headers=headers,
                    data={"content": prompt, "stream": "false"},
                    timeout=15,
                )
                return res.json().get("content", prompt)

        # fallback response
        return f"Zenith AI: With stress at {stress}/10, consider a mindful pause before financial decisions today."

    except Exception:
        return f"Zenith AI: With stress at {stress}/10, consider a mindful pause before financial decisions today."
