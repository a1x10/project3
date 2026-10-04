from __future__ import annotations

import pytest

from config import ConfigError


def test_defaults(make_settings, tmp_path):
    s = make_settings(tmp_path, APP_START_CMD="npm start", HEALTH_URL="http://localhost:3000/health", AI_PROVIDER="")
    assert s.managed and s.has_probe
    assert s.admin_ids == frozenset({1001}) and s.alert_chat_id == 1001
    assert s.app_port == 3000 and not s.app_port_explicit  # порт взят из HEALTH_URL
    assert s.ai_provider == "anthropic" and s.ai_model == "claude-opus-5-5" and s.ai_effort == "high"
    assert s.shell_enabled and not s.git_push


def test_explicit_port_and_openai(make_settings, tmp_path):
    s = make_settings(
        tmp_path, APP_RESTART_CMD="pm2 restart app", HEALTH_CMD="true", APP_PORT="8080",
        AI_PROVIDER="openai", OPENAI_API_KEY="sk-x", ADMIN_IDS="1, 2;3",
    )
    assert not s.managed and s.app_port == 8080 and s.app_port_explicit
    assert s.ai_api_key == "sk-x" and s.ai_model == "gpt-4o-mini" and s.ai_effort is None
    assert s.admin_ids == frozenset({1, 2, 3})


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"TELEGRAM_BOT_TOKEN": ""}, "TELEGRAM_BOT_TOKEN"),
        ({"ADMIN_IDS": ""}, "ADMIN_IDS"),
        ({"ADMIN_IDS": "@me"}, "не числовой"),
        ({"APP_START_CMD": "npm start", "APP_RESTART_CMD": "pm2 restart app"}, "ровно одно"),
        ({}, "ровно одно"),
        ({"APP_RESTART_CMD": "pm2 restart app"}, "HEALTH_URL или HEALTH_CMD"),
        ({"APP_START_CMD": "x", "HEALTH_URL": "localhost:3000"}, "HEALTH_URL"),
        ({"APP_START_CMD": "x", "HEALTH_URL": "tcp://127.0.0.1"}, "порт"),
        ({"APP_START_CMD": "x", "AI_PROVIDER": "gpt"}, "AI_PROVIDER"),
        ({"APP_START_CMD": "x", "AI_EFFORT": "ultra"}, "AI_EFFORT"),
        ({"APP_START_CMD": "x", "CHECK_INTERVAL": "often"}, "CHECK_INTERVAL"),
        ({"APP_START_CMD": "x", "GIT_PUSH": "maybe"}, "GIT_PUSH"),
    ],
)
def test_invalid_settings(make_settings, tmp_path, env, message):
    with pytest.raises(ConfigError, match=message):
        make_settings(tmp_path, **env)


def test_missing_app_dir(make_settings, tmp_path):
    with pytest.raises(ConfigError, match="APP_DIR"):
        make_settings(tmp_path / "nope", APP_START_CMD="x")
