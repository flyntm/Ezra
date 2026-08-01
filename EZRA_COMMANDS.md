# Ezra Voice Command Reference

Start each interaction with **"Ezra"** or **"Hey Ezra."** You can say the
command immediately after the wake phrase or wait for Ezra to begin listening.

## Local commands

| Say | Result |
| --- | --- |
| "What time is it?" | Speaks the current local time. |
| "Set volume to 1" through "Set volume to 10" | Sets speaker volume from 10% to 100%. Number words also work. |
| "Quit," "exit," or "stop" | Exits the Ezra program. |
| "Quit program," "exit program," or "stop program" | Exits the Ezra program. |
| "Shutdown," "shut down," or "power off" | Exits Ezra and attempts to power off the computer. |

## Stop Ezra while speaking

Say **"Ezra stop"** while Ezra is talking to interrupt the current spoken
response. Ezra will say "Stopped." This does not exit the program.

## Weather

Examples:

- "What's the weather?"
- "What's the weather in Dallas?"
- "What is the temperature?"
- "Will it rain?"
- "What is the forecast?"
- "Will it snow?"

Without a named city, Ezra uses the default weather location configured in
`config.py`.

## News

Examples:

- "What's the news?"
- "Read the headlines."
- "What are the current events?"
- "What's happening?"

## General questions and conversation

Anything that is not a local, weather, or news command is sent to Ezra's AI.
Examples:

- "Tell me a joke."
- "Explain why the sky is blue."
- "Give me an idea for dinner."
- "What can we talk about?"
- "Tell me a short story."

Ezra keeps a short conversation history, so follow-up questions can refer to
the recent discussion.

## Sleep and waking

Ezra enters sleep mode after the inactivity period configured by
`SLEEP_TIMEOUT` in `config.py`. Say **"Ezra"** or **"Hey Ezra"** to wake it
again.

## Notes

- Weather and news require an internet connection.
- General AI questions require an internet connection and a working OpenAI API
  key.
- Volume control and system shutdown depend on the operating system commands
  being available and permitted.
