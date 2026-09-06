"""Process lifecycle helpers used when Ezra runs under systemd."""

import signal

import state


def startup_announcement(resuming_presentation=False):
    """Return the recovery greeting when startup will restore a presentation."""
    return "I'm back!" if resuming_presentation else "Ezra ready!"


def handle_shutdown_signal(signum, _frame):
    """Turn systemd's stop request into Ezra's normal cleanup path."""

    signal_name = signal.Signals(signum).name
    print(f"\n🛑 Received {signal_name}; stopping Ezra safely...")
    state.shutting_down = True
    raise KeyboardInterrupt


def install_shutdown_signal_handlers():
    """Handle service stops and terminal interrupts consistently."""

    signal.signal(signal.SIGTERM, handle_shutdown_signal)
