from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

client = OpenAI()

def ask_ezra(user_input):
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=f"""
You are Ezra, a friendly and wise robotic assistant.
Keep responses short, conversational, and helpful.

User: {user_input}
"""
    )

    return response.output_text


def speak(text):
    # simple TTS using espeak
    os.system(f'espeak "{text}"')


def main():
    print("Ezra is ready. Type 'quit' to exit.\n")

    while True:
        user_input = input("You: ")

        if user_input.lower() == "quit":
            break

        reply = ask_ezra(user_input)

        print(f"Ezra: {reply}")
        speak(reply)


if __name__ == "__main__":
    main()
