from routers import upload


def test_process_uploaded_file_normalizes_flac_content_with_mp3_suffix(tmp_path):
    import soundfile as sf

    path = tmp_path / "wrong-suffix.mp3"
    sf.write(path, [0.0] * 8000, 8000, format="FLAC")

    assert upload._get_duration(path) == 1

    result = upload._process_uploaded_file_sync(path, path.name)
    normalized = tmp_path / "wrong-suffix.flac"

    assert result["final_suffix"] == ".flac"
    assert result["duration"] == 1
    assert result["audio_hash"] is not None
    assert normalized.exists()
    assert not path.exists()


def test_compute_audio_hash_rejects_flac_md5_mismatch(monkeypatch, tmp_path):
    path = tmp_path / "bad.flac"
    path.write_bytes(b"fake")
    monkeypatch.setattr(upload, "_read_flac_md5", lambda _path: b"\x01" * 16)
    monkeypatch.setattr(upload, "_compute_soundfile_pcm_md5", lambda _path: b"\x02" * 16)

    assert upload._compute_audio_hash(path) is None


def test_compute_audio_hash_accepts_verified_flac_md5(monkeypatch, tmp_path):
    path = tmp_path / "ok.flac"
    path.write_bytes(b"fake")
    expected = b"\x03" * 16
    monkeypatch.setattr(upload, "_read_flac_md5", lambda _path: expected)
    monkeypatch.setattr(upload, "_compute_soundfile_pcm_md5", lambda _path: expected)

    assert upload._compute_audio_hash(path) == expected
