#!/usr/bin/env python3
"""Generate EZRA_COMMANDS.md from Ezra's maintained command catalog."""

from pathlib import Path
import textwrap


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "EZRA_COMMANDS.md"


PRESENTATION_COMMANDS = (
    ("Introduce yourself", "Reads Ezra's introduction.", "Yes", ""),
    (
        "Tell us who you are / Tell everyone who you are",
        "Reads Ezra's introduction.",
        "Yes", "",
    ),
    (
        "Where does your name come from? / Where did your name come from? / How did you get your name? / Tell me where your name comes from / Why are you named Ezra?",
        "Explains how Ezra got his name.",
        "Yes", "",
    ),
    (
        "Start the presentation / Begin the presentation / Open the presentation / Run the presentation / Present the Acts lesson",
        "Opens the Acts presentation at slide 1.",
        "Yes", "",
    ),
    (
        "Start the presentation on slide 5",
        "Opens the presentation at the requested slide.",
        "Yes", "",
    ),
    ("Next slide / Forward", "Moves to the next slide.", "Yes", "Right / Down"),
    ("Previous slide / Back", "Moves to the previous slide.", "No", "Left / Up"),
    (
        "Go to slide 4 / Show us slide 4 of the presentation / Display slide 4 / Show the fourth slide",
        "Displays a numbered slide.",
        "No*", "Number + Enter",
    ),
    (
        "Show question 2 / Go to question 2 / Display question 2",
        "Displays the requested question slide.",
        "No*", "",
    ),
    (
        "Reveal the answer / Show the answers / Reveal the responses / Show the response",
        "Reveals the answer slide.",
        "Yes", "",
    ),
    (
        "Display the answers / Display the responses",
        "Reveals the answers without reading them.",
        "No*", "",
    ),
    (
        "Tell us about this slide / Explain this slide",
        "Reads the script for the displayed slide.",
        "Yes", "Enter",
    ),
    (
        "Stop the presentation / End the presentation / Close the presentation / Quit the presentation",
        "Closes the presentation.",
        "No", "",
    ),
    (
        "Rehearse the presentation / Preview the presentation / Test the presentation",
        "Prints a complete rehearsal without slides or speech.",
        "No", "",
    ),
    (
        "Tell us more",
        "Continues the previous sourced answer with the next relevant point.",
        "Yes", "",
    ),
    (
        "Give us your own broader explanation of ...",
        "Bypasses study-book and Scripture retrieval for a brief general explanation.",
        "Yes", "",
    ),
    (
        "Outside of Scripture, what ...?",
        "Requests Ezra's own broader, non-scriptural explanation.",
        "Yes", "",
    ),
    ("—", "Skips the narration currently playing.", "No", "Space / Escape"),
)

BIBLE_COMMANDS = (
    ("John 3:16", "Reads one verse."),
    ("Read John chapter 3", "Reads a chapter, subject to the spoken-verse limit."),
    ("Romans 8:28 through 30", "Reads a range of verses."),
    ("First Peter 2 verse 9", "Understands numbered Bible books."),
    ("Now read verse 10", "Continues using the most recently requested Bible book."),
)

OTHER_COMMANDS = (
    (
        "Say good night to everyone",
        "Wishes the audience good night with a closing joke and a smile.",
    ),
    ("What time is it?", "Speaks the current local time."),
    ("Set volume to 1–10", "Sets speaker volume from 10% to 100%."),
    ("What's the weather?", "Reports weather for the configured location."),
    ("What's the weather in Dallas?", "Reports weather for a named location."),
    (
        "What is the forecast? / Will it rain? / What is the temperature? / Will it snow?",
        "Reports relevant forecast details.",
    ),
    (
        "What's the news? / Read the headlines / What are the current events? / What's happening?",
        "Reports current news headlines.",
    ),
    ("Ezra, stop", "Interrupts Ezra while he is speaking."),
    (
        "Quit / Exit / Quit program / Exit program / Stop program",
        "Exits the Ezra application.",
    ),
    (
        "Shutdown / Shut down / Power off / Poweroff",
        "Exits Ezra and attempts to power off the Pi.",
    ),
    (
        "Any general question",
        "Uses Ezra's AI; recent conversation can provide follow-up context.",
    ),
)


def _table(headers, rows):
    """Render stable-width columns with alternatives on continuation rows."""
    widths = {
        2: (38, 70),
        3: (52, 70, 9),
        4: (44, 48, 9, 17),
    }[len(headers)]

    def formatted_row(values):
        return "| " + " | ".join(
            str(value).ljust(widths[index])
            for index, value in enumerate(values)
        ) + " |"

    lines = [
        formatted_row(headers),
        formatted_row(tuple("-" * width for width in widths)),
    ]
    for row in rows:
        commands = str(row[0]).split(" / ")
        descriptions = textwrap.wrap(
            str(row[1]),
            width=widths[1],
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]
        continuation_count = max(len(commands), len(descriptions))
        for index in range(continuation_count):
            command = commands[index] if index < len(commands) else ""
            if index > 0 and command:
                command = f"    {command}"
            description = descriptions[index] if index < len(descriptions) else ""
            trailing = row[2:] if index == 0 else tuple("" for _item in row[2:])
            lines.append(formatted_row((command, description, *trailing)))
    return "\n".join(lines)


def render_reference():
    return f"""# Ezra Command Reference

<!-- Generated by tools/build_command_reference.py. Do not edit by hand. -->

Begin a conversation with **“Ezra”** or **“Hey Ezra.”** In general mode, after
each answer Ezra listens for a follow-up for **5 seconds** by default, with
**two mouth LEDs lit**. In presentation mode, follow-up listening is disabled;
say the wake word for each new question or command.
Ask another question without repeating her name. Silence, **“that's all,”**
or **“never mind”** returns her to waiting for the wake word. Each follow-up
opens a new listening window after the answer. Interrupting an AI answer
returns her to standby.

Set `ENABLE_FOLLOW_UP_LISTENING` or `FOLLOW_UP_LISTEN_SECONDS` in `config.py`
to disable follow-ups or adjust the window. The examples below show natural
phrases; minor wording variations are accepted.

Ezra's primary user's name is saved in `PRIMARY_USER_NAME` in `config.py`.
It survives restarts and is available to both online and offline AI answers.
Ask **“Ezra, what's my name?”** To change or remove the saved name, edit that
setting (use an empty string to remove it) and restart Ezra.

## Presentation commands

{_table(("Command", "What it does", "Narrates?", "Presentation keys"), PRESENTATION_COMMANDS)}

\\* Add **“and explain”** to a non-narrating slide, question, or answer-display
command to read the script after displaying it. For example: **“Go to slide 4
and explain.”** These variations are not listed separately.

If a valid presentation command is given before the presentation is running,
Ezra starts the presentation silently and immediately performs that command.

## Bible commands

{_table(("Command", "What it does"), BIBLE_COMMANDS)}

Ezra uses the NIV when it is available online and the local World English Bible
when offline. A Bible passage can also be displayed while Ezra reads it.

## Other commands

{_table(("Command", "What it does"), OTHER_COMMANDS)}

## Pi terminal presentation controls

Pi desktop recovery shortcuts work globally without opening a terminal:

| Shortcut     | What it does                                                   |
| ------------ | -------------------------------------------------------------- |
| Ctrl+Alt+R   | Clears a failed state and performs a normal Ezra restart.      |
| Ctrl+Alt+P   | Restarts after preserving the active presentation for restore. |

If Ezra becomes unresponsive during a presentation, press **Ctrl+Alt+T** on
the Pi keyboard to open a terminal. These are terminal shortcuts, not spoken
commands:

| Shortcut       | What it does                                      |
| -------------- | ------------------------------------------------- |
| `ezra-stop`    | Stops Ezra and leaves it stopped.                  |
| `ezra-start`   | Starts Ezra after an intentional stop.             |
| `ezra-restart` | Stops and starts the Ezra application.             |
| `ezra-reboot`  | Reboots the entire Pi; it may request the password. |

After `ezra-reboot`, Ezra should start automatically when the Pi returns to
its desktop session. **Ctrl+C** only stops Ezra when it was launched directly
from that same terminal. If the terminal is following Ezra's system log,
**Ctrl+C** stops only the log viewer.

## Notes

- Lesson questions search every `.jsonl` file in `presentations/`; added or
  modified files are detected automatically.
- Sourced answers identify the study book or Scripture. PowerPoint speaker
  notes are used for slide narration only and are not question-answer sources.
- Ezra initially gives the most relevant sourced point in no more than two
  short sentences. If more relevant material remains, Ezra says **“There is
  more.”** Say **“Ezra, tell us more”** to continue the original answer.
- Requests for Ezra's own broader explanation bypass lesson and Scripture
  retrieval and are identified as Ezra's own explanation.
- Weather, news, and online AI responses require an internet connection.
- When offline, general questions use Ezra's local AI if it is available.
- Say **“Ezra, stop”** during speech to interrupt the response; this does not
  exit the application.
- Ezra enters sleep mode after the configured inactivity period. Say **“Ezra”**
  or **“Hey Ezra”** to wake him.
- Volume control and system shutdown depend on operating-system permissions.
"""


def main():
    OUTPUT_PATH.write_text(render_reference(), encoding="utf-8")
    print(f"Updated {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()
