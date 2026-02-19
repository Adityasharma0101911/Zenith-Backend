# this sends secure data to the ai for analysis

# import requests to make http calls to the ai provider
import requests

# import os to read the api key from environment variables
import os

# this builds advice based on the user spending profile and stress
def get_ai_advice(spending_profile, balance, stress):
    # get the ai api key from the environment
    api_key = os.getenv("AI_API_KEY")

    # get the ai api url from the environment or use a placeholder
    api_url = os.getenv("AI_API_URL", "https://api.openai.com/v1/chat/completions")

    # build the prompt with universal spending profile instead of cultural types
    prompt = (
        f"You are Zenith, an enterprise-grade AI guardian. "
        f"The user has a '{spending_profile}' spending profile, has ${balance}, and stress level {stress}/10. "
        f"Provide one short sentence of actionable advice protecting their financial and mental well-being."
    )

    # if there is no api key, return a fallback message
    if not api_key:
        return f"Zenith AI: With a stress level of {stress}/10, consider taking a mindful pause before any financial decisions today."

    # try to call the ai api
    try:
        # send the prompt to the ai provider
        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
            },
            timeout=10,
        )

        # parse the ai response
        data = response.json()

        # return the ai's text
        return data["choices"][0]["message"]["content"].strip()

    except Exception as e:
        # if the ai call fails, return a fallback message
        return f"Zenith AI: With a stress level of {stress}/10, consider taking a mindful pause before any financial decisions today."
