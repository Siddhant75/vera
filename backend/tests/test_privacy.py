from app.privacy import safe_query, scan_for_secrets


def test_secrets_detected():
    text = "key sk-abc12345 here\nAKIAIOSFODNN7EXAMPLE\npassword: hunter2\n-----BEGIN RSA KEY\n4111111111111111"
    found = scan_for_secrets(text)
    assert "api-key" in found
    assert "password" in found
    assert "private-key" in found
    assert "card-number" in found


def test_clean_text_no_warnings():
    assert scan_for_secrets("our team runs kubernetes on three clusters") == []


def test_safe_query_blocks_note_ngram():
    notes = ["our internal SLA is 45 minutes for the p99 inference latency budget"]
    leaky = "what is the standard internal SLA is 45 minutes for p99 latency"
    assert safe_query(leaky, notes, fallback="fallback-query") == "fallback-query"


def test_safe_query_passes_unrelated():
    notes = ["our internal SLA is 45 minutes for the p99 inference latency budget"]
    assert safe_query("kubernetes vs serverless cold start", notes, fallback="fb") == "kubernetes vs serverless cold start"


def test_safe_query_empty_notes_passthrough():
    assert safe_query("anything at all", [], fallback="fb") == "anything at all"
