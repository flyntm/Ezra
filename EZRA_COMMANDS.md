# Ezra Voice Command Reference

Start each interaction with **"Ezra"** or **"Hey Ezra."** You can say the
command immediately after the wake phrase or wait for Ezra to begin listening.

## Local commands

| Say | Result |
| --- | --- |
| "What time is it?" | Speaks the current local time. |
| "Set volume to 1" through "Set volume to 10" | Sets speaker volume from 10% to 100%. Number words also work. |
| "Start the presentation" / "Start presentation" | Opens slide 1 and speaks its script. |
| "Start the presentation on slide 5" / "Start the presentation with slide 5" | Opens at a requested slide and speaks its script. Digits or number words from 1–100 are supported. |
| "Next slide" | Moves forward and speaks the matching script. |
| "Previous slide" / "Back" | Moves backward without reading the script. Answer slides remain revealed. |
| "Reveal the answer" / "Show us the answers" | Reveals and speaks the response for the discussion slide. |
| "Display the answers" | Reveals the response without reading its script. |
| "Go to slide 4" / "Go to slide number four" | Jumps directly to a numbered slide without reading its script. Numbers 1–100 may be digits or words. |
| "Please tell us about this slide" | Reads the script for the currently displayed slide. |
| "Stop the presentation" | Closes the active slideshow. |
| "Rehearse the presentation" | Prints a full rehearsal without opening slides or using TTS. |
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
- PowerPoint slides are converted locally to HTML and displayed in Chromium;
  the original deck is not modified.
