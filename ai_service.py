# legacy ai advice function — uses cached guardian thread instead of creating new ones

import os
from backboard_service import chat_with_ai

# provides a quick one-line insight for the dashboard (reuses guardian thread)
def get_ai_advice(user_id, spending_profile, balance, stress):
    prompt = (
        f"You are Zenith, an AI wellness guardian — like JARVIS, calm and conversational. "
        f"The user has a '{spending_profile}' spending profile, ${balance} balance, "
        f"and stress level {stress}/10. "
        f"Give one short, friendly sentence of advice for their financial and mental well-being. "
        f"No markdown, no bold, no lists — just natural speech."
    )
    
    return chat_with_ai(user_id, "guardian", prompt, None)
