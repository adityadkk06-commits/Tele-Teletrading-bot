import os
from typing import Optional
from collections import defaultdict

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

SYSTEM_PROMPT = """You are a helpful AI assistant connected via Telegram. 
You are concise, friendly, and informative. 
Keep your responses clear and easy to read on a mobile device.
Use plain text — avoid heavy markdown since Telegram may not render it."""

MAX_HISTORY = 20


class Agent:
    def __init__(self):
        self.histories: dict[int, list[dict]] = defaultdict(list)
        self.client: Optional[object] = None
        self.model = "gpt-4o-mini"

        if OPENAI_AVAILABLE:
            api_key = os.environ.get("OPENAI_API_KEY")
            if api_key:
                self.client = OpenAI(api_key=api_key)

    def clear_history(self, user_id: int) -> None:
        self.histories[user_id] = []

    def respond(self, user_id: int, message: str) -> str:
        history = self.histories[user_id]
        history.append({"role": "user", "content": message})

        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]
            self.histories[user_id] = history

        if self.client:
            return self._openai_respond(user_id, history)
        else:
            return self._echo_respond(message)

    def _openai_respond(self, user_id: int, history: list[dict]) -> str:
        try:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            reply = completion.choices[0].message.content
            self.histories[user_id].append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            return f"Sorry, I encountered an error: {str(e)}"

    def _echo_respond(self, message: str) -> str:
        return (
            f"You said: {message}\n\n"
            "Note: No OpenAI API key is configured. "
            "Set OPENAI_API_KEY to enable AI responses."
        )
