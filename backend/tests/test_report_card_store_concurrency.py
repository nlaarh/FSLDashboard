"""Two requests saving the same day file at the same time must not trip over each other's temp file."""

import threading

import report_card_store as store


def test_parallel_saves_of_the_same_file_do_not_fail(monkeypatch, tmp_path):
    monkeypatch.setenv('REPORT_CARD_STORE_DIR', str(tmp_path))
    errors = []

    def save():
        try:
            for _ in range(50):
                store.save_segments('0HhPb00000007qGKAQ', '2026-10-02', {'rules_version': 'x', 'rows': list(range(500))})
        except Exception as e:      # noqa: BLE001 - the test records any failure
            errors.append(e)

    threads = [threading.Thread(target=save) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert errors == []
