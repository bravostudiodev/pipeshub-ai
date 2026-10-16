from app.utils.storage_download import is_inline_file


def test_explicit_header_wins_over_content_disposition():
    assert is_inline_file({"X-Storage-Delivery": "inline"})
    assert not is_inline_file({"X-Storage-Delivery": "signed-url", "Content-Disposition": "attachment"})


def test_legacy_server_falls_back_to_content_disposition():
    assert is_inline_file({"Content-Disposition": "attachment; filename=a.json"})
    assert not is_inline_file({"Content-Type": "application/json"})
