"""Reusable presentation content and delivery helpers for Ezra."""

from .common import (
    is_introduction_request,
    is_name_origin_request,
    present_introduction,
    present_name_origin,
)
from .acts_lesson_one import (
    handle_active_command as handle_presentation_command,
    is_rehearsal_request,
    is_start_request as is_presentation_request,
    requested_start_slide,
    start_presentation,
)

__all__ = [
    "handle_presentation_command",
    "is_introduction_request",
    "is_name_origin_request",
    "is_presentation_request",
    "is_rehearsal_request",
    "requested_start_slide",
    "present_introduction",
    "present_name_origin",
    "start_presentation",
]
