import json

import numpy as np

from Test_files.diagnostics.xvf3800_mount_test import (
    audio_metrics,
    circular_mean_degrees,
    existing_configuration_sessions,
    numbered_configuration_name,
    safe_name,
    summarize_control,
    write_all_results,
)


def test_safe_name_is_suitable_for_session_directory():
    assert safe_name("Foam mount / v2") == "Foam_mount_v2"


def test_audio_metrics_reports_known_rms():
    audio = np.array([[0.5, 0.5], [-0.5, -0.5]], dtype=np.float32)
    metrics = audio_metrics(audio)
    assert metrics["rms_dbfs"] == -6.02
    assert metrics["peak_dbfs"] == -6.02
    assert metrics["clipped_samples"] == 0


def test_circular_mean_wraps_through_zero():
    angle = circular_mean_degrees([359, 1])
    assert angle is not None
    assert min(abs(angle), abs(angle - 360)) < 0.01


def test_control_summary_uses_only_speech_doa():
    result = summarize_control([
        {"doa_degrees": 10, "speech": True, "speech_energy": [2, 4]},
        {"doa_degrees": 20, "speech": True, "speech_energy": [4, 6]},
        {"doa_degrees": 200, "speech": False, "speech_energy": [0, 0]},
    ])
    assert result["speech_fraction"] == 0.667
    assert result["mean_doa_degrees"] == 15.0
    assert result["mean_speech_energy"] == [2.0, 3.33]


def test_all_results_combines_sessions(tmp_path):
    session_dir = tmp_path / "20260810_baseline"
    session_dir.mkdir()
    (session_dir / "session.json").write_text(json.dumps({
        "metadata": {
            "configuration": "baseline",
            "created": "2026-08-10T12:00:00-05:00",
            "distance_metres": 1.0,
        },
        "trials": [{
            "name": "quiet",
            "rms_dbfs": -50.0,
            "mean_speech_energy": [1.0, 2.0, 3.0, 4.0],
        }],
    }), encoding="utf-8")

    output = write_all_results(tmp_path)
    text = output.read_text(encoding="utf-8-sig")
    assert "configuration,session_created" in text
    assert "baseline" in text
    assert "1.0,2.0,3.0,4.0" in text


def test_duplicate_configuration_gets_next_available_number(tmp_path):
    for folder, configuration in (
        ("first", "mount"),
        ("second", "mount_2"),
    ):
        session_dir = tmp_path / folder
        session_dir.mkdir()
        (session_dir / "session.json").write_text(json.dumps({
            "metadata": {"configuration": configuration},
            "trials": [],
        }), encoding="utf-8")

    assert existing_configuration_sessions(tmp_path, "mount") == [tmp_path / "first"]
    assert numbered_configuration_name(tmp_path, "mount") == "mount_3"
