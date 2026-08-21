"""Compatibility imports for the renamed generic presentation controller.

New code should import :mod:`presentations.lesson_presentation`.
"""

from .lesson_presentation import *  # noqa: F401,F403
from .lesson_presentation import LessonPresentationSession


# Preserve the former public class name for external scripts during migration.
ActsLessonOneSession = LessonPresentationSession
