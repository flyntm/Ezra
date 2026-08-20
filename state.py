shutting_down = False

# Currently active aplay process for speech output.
tts_process = None

# True when mid-response stop listener is available.
mid_response_stop_ready = False

# Updated by network_status.py. Keep a separate known flag because False at
# process startup does not yet mean a connectivity check has failed.
internet_connected = False
internet_status_known = False
internet_last_checked_at = None
internet_last_error = ""
