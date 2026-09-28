# Look-at-me activation — September 8, 2026

The look-at-me implementation is present in the working tree and was activated
by restarting `ezra.service` on the Pi at 10:21 CDT. The service reported
`Ezra ready`; startup confirmed ReSpeaker VAD, servo/mouth hardware, and head
centering.

Supported requests: “look at me,” “look here,” “look over here,” and “face me,”
including polite forms and Presentation mode. Missing command direction asks
the speaker to repeat. Capture clears the previous target and records the new
qualified target before automatic tracking, preventing stale or doubled turns.
Servo limits and scripted center holds remain enforced.

Validation: `ezra311-env/bin/python -m unittest discover -s tests` passed all
199 tests; `git diff --check` passed. Tests cover command routing, Presentation
mode, missing direction, avoiding a repeated correction, and servo limits.

Physical speaker-direction acceptance is still awaiting an observer: speak
“Ezra, look at me” from each side in General and Presentation modes and confirm
the head faces the speaker. Successful startup and automated tests do not
establish this acoustic/physical result.

The restart loaded the current working tree, which also contains earlier repair
changes. No commit or push was made, and the installed service unit was not
modified by this activation.
