from types import SimpleNamespace

import pytest

from dashboard.api_client import DashboardApiError
from dashboard.auth import configure_operator_identity


class StopExecution(Exception):
    pass


class FakeSidebar:
    def __init__(self, *, logout_clicked=False):
        self.logout_clicked = logout_clicked
        self.captions = []
        self.writes = []

    def caption(self, value):
        self.captions.append(value)

    def write(self, value):
        self.writes.append(value)

    def markdown(self, value):
        return value

    def button(self, label):
        assert label == "Logout"
        return self.logout_clicked


class FakeStreamlit:
    def __init__(self, user, *, login_clicked=False, logout_clicked=False):
        self.user = user
        self.login_clicked = login_clicked
        self.sidebar = FakeSidebar(logout_clicked=logout_clicked)
        self.login_calls = 0
        self.logout_calls = 0
        self.markdown_calls = []
        self.title_calls = []

    def markdown(self, value):
        self.markdown_calls.append(value)

    def title(self, value):
        self.title_calls.append(value)

    def button(self, label, *, type=None):
        assert label == "Sign in with Google"
        assert type == "primary"
        return self.login_clicked

    def login(self):
        self.login_calls += 1

    def logout(self):
        self.logout_calls += 1

    def stop(self):
        raise StopExecution

    def error(self, value):
        raise AssertionError(value)


class FakeClient:
    def __init__(self, *, operator=None, error=None):
        self.operator = operator
        self.error = error
        self.token = None

    def set_operator_access_token(self, token):
        self.token = token

    def get_current_operator(self):
        if self.error:
            raise self.error
        return self.operator


def test_unauthenticated_shadow_mode_shows_google_login_and_stops(monkeypatch):
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "shadow")
    st = FakeStreamlit(SimpleNamespace(is_logged_in=False), login_clicked=True)

    with pytest.raises(StopExecution):
        configure_operator_identity(st, FakeClient())

    assert st.markdown_calls == ["PUBBA POWER"]
    assert st.title_calls == ["Sign in to PUBBA Power"]
    assert st.login_calls == 1


def test_authenticated_user_continues_in_shadow_mode_with_sidebar_identity(monkeypatch):
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "shadow")
    user = {
        "is_logged_in": True,
        "name": "Jane Operator",
        "email": "jane@pubba.test",
        "tokens": {"id": "verified-id-token"},
    }
    user = SimpleNamespace(**user)
    client = FakeClient(error=DashboardApiError("Not onboarded", code="operator_not_found"))
    st = FakeStreamlit(user)

    assert configure_operator_identity(st, client) is None
    assert client.token == "verified-id-token"
    assert st.sidebar.writes == ["Jane Operator"]
    assert "Operator identity · Access denied" in st.sidebar.captions


def test_logout_calls_streamlit_logout_and_stops():
    user = SimpleNamespace(
        is_logged_in=True,
        name="Jane Operator",
        tokens={"id": "verified-id-token"},
    )
    st = FakeStreamlit(user, logout_clicked=True)

    with pytest.raises(StopExecution):
        configure_operator_identity(st, FakeClient())

    assert st.logout_calls == 1
