# Ezra automatic startup

Ezra runs as a systemd user service so it starts inside the same Raspberry Pi
desktop session that provides PipeWire audio and the Wayland display.

## One-time Pi setup

1. Enable desktop autologin for the `flyntm` account:

   ```bash
   sudo raspi-config
   ```

   Choose **System Options**, **Boot / Auto Login**, then **Desktop Autologin**.

2. From the Ezra project directory, install and start the service:

   ```bash
   chmod +x install_service.sh
   ./install_service.sh
   ```

3. Confirm that Ezra is running:

   ```bash
   systemctl --user status ezra
   ```

4. Reboot the Pi and confirm that Ezra announces it is ready without a Mac
   connection:

   ```bash
   sudo reboot
   ```

## Operation and troubleshooting

Follow Ezra's live output:

```bash
journalctl --user-unit=ezra.service -f
```

Restart or stop Ezra:

```bash
systemctl --user restart ezra
systemctl --user stop ezra
```

Start Ezra again or disable automatic startup:

```bash
systemctl --user start ezra
systemctl --user disable --now ezra
```

The service retries five seconds after an unexpected exit. A normal service
stop sends `SIGTERM`, which Ezra handles through its existing robot cleanup
path before exiting.

The service also uses a 30-second health watchdog. Ezra withholds its heartbeat
if microphone callbacks stop, command processing remains stuck for five
minutes, or the presentation browser exits. Systemd then restarts Ezra, and an
active presentation is silently restored at its last displayed slide.

If the microphone, speaker, or display is unavailable after boot, inspect the
journal first. Also confirm the Pi reached the desktop and that `flyntm` was
logged in automatically.
