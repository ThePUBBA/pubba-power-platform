from scripts.diagnose_supabase_env import key_format


def test_key_format_reports_only_the_credential_shape():
    assert key_format("sb_secret_example") == "supabase_secret"
    assert key_format("aaa.bbb.ccc") == "jwt"
    assert key_format("short-or-placeholder") == "unknown"
