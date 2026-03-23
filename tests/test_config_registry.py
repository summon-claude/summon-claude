"""Guard tests for ConfigOption registry — prevents drift with SummonConfig."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from summon_claude.config import (
    CONFIG_OPTIONS,
    SummonConfig,
    get_config_default,
    is_extra_installed,
)


@pytest.fixture(autouse=True)
def _clear_extra_installed_cache():
    """Prevent cross-test contamination from @functools.cache."""
    is_extra_installed.cache_clear()
    yield
    is_extra_installed.cache_clear()


class TestConfigOptionRegistryGuard:
    """Ensure CONFIG_OPTIONS stays in sync with SummonConfig.model_fields."""

    def test_every_config_field_has_option(self):
        """Every SummonConfig field must have a corresponding ConfigOption."""
        option_fields = {opt.field_name for opt in CONFIG_OPTIONS}
        # model_config is pydantic's SettingsConfigDict (ClassVar), not a user field
        model_fields = {f for f in SummonConfig.model_fields if f != "model_config"}
        missing = model_fields - option_fields
        assert not missing, f"SummonConfig fields without ConfigOption: {missing}"

    def test_every_option_maps_to_real_field(self):
        """Every ConfigOption.field_name must exist on SummonConfig."""
        for opt in CONFIG_OPTIONS:
            assert opt.field_name in SummonConfig.model_fields, (
                f"ConfigOption {opt.env_key!r} references non-existent field {opt.field_name!r}"
            )

    def test_env_key_format(self):
        """Every env_key must be SUMMON_ prefixed and match field_name."""
        for opt in CONFIG_OPTIONS:
            expected = f"SUMMON_{opt.field_name.upper()}"
            assert opt.env_key == expected, (
                f"ConfigOption {opt.field_name!r} env_key mismatch: {opt.env_key!r} != {expected!r}"
            )

    def test_required_options_match_required_fields(self):
        """Required ConfigOptions must match fields without defaults in SummonConfig."""
        required_option_fields = {opt.field_name for opt in CONFIG_OPTIONS if opt.required}
        required_model_fields = set()
        for name, info in SummonConfig.model_fields.items():
            if info.is_required():
                required_model_fields.add(name)
        assert required_option_fields == required_model_fields

    def test_secret_options_match_repr_false_fields(self):
        """Secret ConfigOptions should match fields with repr=False."""
        secret_fields = {opt.field_name for opt in CONFIG_OPTIONS if opt.input_type == "secret"}
        repr_false_fields = set()
        for name, info in SummonConfig.model_fields.items():
            if info.repr is False:
                repr_false_fields.add(name)
        assert secret_fields == repr_false_fields

    def test_defaults_from_registry_match_model(self):
        """get_config_default must return the same default as SummonConfig.model_fields."""
        for opt in CONFIG_OPTIONS:
            registry_default = get_config_default(opt)
            field_info = SummonConfig.model_fields[opt.field_name]
            model_default = field_info.default
            assert registry_default == model_default, (
                f"Default mismatch for {opt.field_name!r}: "
                f"registry={registry_default!r}, model={model_default!r}"
            )

    def test_input_types_are_valid(self):
        """All input_type values must be one of the known types."""
        valid_types = {"text", "secret", "choice", "flag", "int"}
        for opt in CONFIG_OPTIONS:
            assert opt.input_type in valid_types, (
                f"ConfigOption {opt.env_key!r} has invalid input_type: {opt.input_type!r}"
            )

    def test_choice_options_have_choices(self):
        """Choice-type options must have choices or choices_fn."""
        for opt in CONFIG_OPTIONS:
            if opt.input_type == "choice":
                assert opt.choices or opt.choices_fn, (
                    f"ConfigOption {opt.env_key!r} is 'choice' type but has no choices"
                )

    def test_field_validators_have_validate_fn(self):
        """Fields with @field_validator must have validate_fn on their ConfigOption.

        Without validate_fn, `config set` accepts invalid values — the pydantic
        validator only fires at SummonConfig construction time.
        Choice-type options are exempt (choices= enforces valid values).
        """
        validators = SummonConfig.__pydantic_decorators__.field_validators
        validated_fields: set[str] = set()
        for _name, dec in validators.items():
            validated_fields.update(dec.info.fields)

        for opt in CONFIG_OPTIONS:
            if opt.field_name not in validated_fields:
                continue
            # Choice-type options enforce valid values via choices=
            if opt.input_type == "choice":
                continue
            assert opt.validate_fn is not None, (
                f"ConfigOption {opt.env_key!r} has a @field_validator on SummonConfig"
                f" but no validate_fn — `config set` would accept invalid values"
            )


class TestConfigOptionVisibility:
    """Test visibility predicates for conditional options."""

    def test_scribe_options_hidden_when_disabled(self):
        """Scribe sub-options should not be visible when scribe_enabled is false."""
        cfg: dict[str, str] = {}
        for opt in CONFIG_OPTIONS:
            if (
                opt.group.startswith("Scribe")
                and opt.field_name != "scribe_enabled"
                and opt.visible is not None
            ):
                assert not opt.visible(cfg), (
                    f"ConfigOption {opt.env_key!r} should be hidden when scribe is disabled"
                )

    def test_scribe_options_visible_when_enabled(self):
        """Scribe core sub-options should be visible when scribe_enabled is true."""
        cfg = {"SUMMON_SCRIBE_ENABLED": "true"}
        scribe_core = [
            opt
            for opt in CONFIG_OPTIONS
            if opt.group == "Scribe" and opt.field_name != "scribe_enabled" and opt.visible
        ]
        for opt in scribe_core:
            assert opt.visible is not None and opt.visible(cfg), (
                f"ConfigOption {opt.env_key!r} should be visible when scribe is enabled"
            )

    def test_scribe_slack_options_need_both_flags_and_playwright(self):
        """Scribe Slack browser/channels need both flags plus playwright installed."""
        cfg_scribe_only = {"SUMMON_SCRIBE_ENABLED": "true"}
        cfg_both = {"SUMMON_SCRIBE_ENABLED": "true", "SUMMON_SCRIBE_SLACK_ENABLED": "true"}

        browser_opt = next(o for o in CONFIG_OPTIONS if o.field_name == "scribe_slack_browser")
        assert browser_opt.visible is not None
        assert not browser_opt.visible(cfg_scribe_only)
        # With playwright importable, both flags should make it visible
        with patch("summon_claude.config.is_extra_installed", return_value=True):
            assert browser_opt.visible(cfg_both)
        # Without playwright, still hidden even with both flags
        with patch("summon_claude.config.is_extra_installed", return_value=False):
            assert not browser_opt.visible(cfg_both)

    @pytest.mark.parametrize("bool_value", ["true", "1", "yes", "True", "YES"])
    def test_scribe_enabled_accepts_truthy_values(self, bool_value: str):
        """Visibility predicate should accept all truthy boolean strings."""
        cfg = {"SUMMON_SCRIBE_ENABLED": bool_value}
        scan_opt = next(o for o in CONFIG_OPTIONS if o.field_name == "scribe_scan_interval_minutes")
        assert scan_opt.visible is not None
        assert scan_opt.visible(cfg)


class TestVisibilityGracefulDegradation:
    """Visibility predicates degrade gracefully when optional extras missing."""

    def test_scribe_google_hidden_without_workspace_mcp(self):
        """scribe_google_services hidden when workspace_mcp not importable."""
        cfg = {"SUMMON_SCRIBE_ENABLED": "true"}
        google_opt = next(o for o in CONFIG_OPTIONS if o.field_name == "scribe_google_services")
        assert google_opt.visible is not None
        with patch("summon_claude.config.is_extra_installed", return_value=False):
            assert not google_opt.visible(cfg)

    def test_scribe_slack_browser_hidden_without_playwright(self):
        """scribe_slack_browser hidden when playwright not importable."""
        cfg = {"SUMMON_SCRIBE_ENABLED": "true", "SUMMON_SCRIBE_SLACK_ENABLED": "true"}
        browser_opt = next(o for o in CONFIG_OPTIONS if o.field_name == "scribe_slack_browser")
        assert browser_opt.visible is not None
        with patch("summon_claude.config.is_extra_installed", return_value=False):
            assert not browser_opt.visible(cfg)


class TestConfigShowIntegration:
    """Integration tests for config show output."""

    def test_config_show_outputs_all_visible_keys(self, tmp_path, capsys):
        """config show outputs all always-visible CONFIG_OPTIONS keys."""
        from summon_claude.cli.config import config_show

        config_file = tmp_path / "config.env"
        config_file.write_text("SUMMON_SLACK_BOT_TOKEN=xoxb-test\n")

        with patch("summon_claude.cli.config.get_config_file", return_value=config_file):
            config_show(color=False)

        out = capsys.readouterr().out
        always_visible = [o for o in CONFIG_OPTIONS if o.visible is None]
        for opt in always_visible:
            assert opt.env_key in out, f"{opt.env_key} missing from config show output"

    def test_config_show_hides_scribe_shows_hint(self, tmp_path, capsys):
        """config show hides scribe sub-options and shows disabled hint."""
        from summon_claude.cli.config import config_show

        config_file = tmp_path / "config.env"
        config_file.write_text("")

        with patch("summon_claude.cli.config.get_config_file", return_value=config_file):
            config_show(color=False)

        out = capsys.readouterr().out
        assert "disabled" in out
        assert "SUMMON_SCRIBE_SCAN_INTERVAL_MINUTES" not in out

    def test_config_show_no_ansi_with_color_false(self, tmp_path, capsys):
        """config show with color=False produces no ANSI escape codes."""
        from summon_claude.cli.config import config_show

        config_file = tmp_path / "config.env"
        config_file.write_text("SUMMON_SLACK_BOT_TOKEN=xoxb-test\n")

        with patch("summon_claude.cli.config.get_config_file", return_value=config_file):
            config_show(color=False)

        out = capsys.readouterr().out
        assert "\x1b[" not in out, "ANSI escape codes found in --no-color output"

    def test_config_show_github_pat_masked(self, tmp_path, capsys):
        """config show masks github_pat value."""
        from summon_claude.cli.config import config_show

        config_file = tmp_path / "config.env"
        config_file.write_text("SUMMON_GITHUB_PAT=ghp_secret123abc\n")

        with patch("summon_claude.cli.config.get_config_file", return_value=config_file):
            config_show(color=False)

        out = capsys.readouterr().out
        assert "ghp_secret123abc" not in out
        assert "configured" in out


class TestNoUpdateCheckField:
    """Tests for the promoted no_update_check SummonConfig field."""

    def test_no_update_check_default_false(self):
        """no_update_check defaults to False."""
        default = get_config_default(
            next(o for o in CONFIG_OPTIONS if o.field_name == "no_update_check")
        )
        assert default is False

    def test_no_update_check_in_config_options(self):
        """no_update_check should exist in CONFIG_OPTIONS."""
        matches = [o for o in CONFIG_OPTIONS if o.field_name == "no_update_check"]
        assert len(matches) == 1
        assert matches[0].input_type == "flag"
        assert matches[0].group == "Behavior"


class TestConfigOptionOrdering:
    """Guard: CONFIG_OPTIONS must list all core options before any advanced options."""

    def test_core_options_precede_advanced(self):
        """Once an advanced option appears, no core options may follow."""
        seen_advanced = False
        for opt in CONFIG_OPTIONS:
            if opt.advanced:
                seen_advanced = True
            elif seen_advanced:
                # Core option after an advanced one — ordering is broken.
                # visibility-gated options (like scribe sub-options) that appear
                # before the advanced block are fine since they're core.
                pytest.fail(
                    f"Core option {opt.env_key!r} appears after advanced options. "
                    "Move it before the advanced block in CONFIG_OPTIONS."
                )


class TestChannelPrefixValidation:
    """Guard: channel_prefix must conform to Slack channel naming rules."""

    def test_valid_prefix(self):
        cfg = SummonConfig(
            slack_bot_token="xoxb-test",
            slack_app_token="xapp-test",
            slack_signing_secret="abc123",
            channel_prefix="my-team",
        )
        assert cfg.channel_prefix == "my-team"

    def test_invalid_prefix_uppercase(self):
        with pytest.raises(ValueError, match="channel_prefix must be"):
            SummonConfig(
                slack_bot_token="xoxb-test",
                slack_app_token="xapp-test",
                slack_signing_secret="abc123",
                channel_prefix="MyTeam",
            )

    def test_invalid_prefix_spaces(self):
        with pytest.raises(ValueError, match="channel_prefix must be"):
            SummonConfig(
                slack_bot_token="xoxb-test",
                slack_app_token="xapp-test",
                slack_signing_secret="abc123",
                channel_prefix="my team",
            )

    def test_invalid_prefix_empty(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            SummonConfig(
                slack_bot_token="xoxb-test",
                slack_app_token="xapp-test",
                slack_signing_secret="abc123",
                channel_prefix="",
            )


class TestSigningSecretValidation:
    """Guard: signing_secret must be a hex string."""

    def test_valid_hex(self):
        cfg = SummonConfig(
            slack_bot_token="xoxb-test",
            slack_app_token="xapp-test",
            slack_signing_secret="abcdef012345",
        )
        assert cfg.slack_signing_secret == "abcdef012345"

    def test_invalid_non_hex(self):
        with pytest.raises(ValueError, match="hex string"):
            SummonConfig(
                slack_bot_token="xoxb-test",
                slack_app_token="xapp-test",
                slack_signing_secret="not-hex-value",
            )

    def test_empty_passes_validator(self):
        """Empty string bypasses the @field_validator; caught by validate() instead."""
        cfg = SummonConfig(
            slack_bot_token="xoxb-test",
            slack_app_token="xapp-test",
            slack_signing_secret="",
        )
        assert cfg.slack_signing_secret == ""


class TestSlackScopeGuard:
    """Guard: hardcoded required scopes in config_check must match the manifest."""

    def test_required_scopes_match_manifest(self):
        import yaml

        manifest_path = Path(__file__).resolve().parent.parent / "slack-app-manifest.yaml"
        if not manifest_path.exists():
            pytest.skip("slack-app-manifest.yaml not found")

        manifest = yaml.safe_load(manifest_path.read_text())
        manifest_scopes = set(manifest["oauth_config"]["scopes"]["bot"])

        # Import the same set used in config_check
        # (hardcoded in _check_slack_scopes → inline in config_check)
        from summon_claude.cli.config import _REQUIRED_SLACK_SCOPES

        assert manifest_scopes == _REQUIRED_SLACK_SCOPES, (
            f"Scope mismatch.\n"
            f"  In manifest but not in code: {manifest_scopes - _REQUIRED_SLACK_SCOPES}\n"
            f"  In code but not in manifest: {_REQUIRED_SLACK_SCOPES - manifest_scopes}"
        )


class TestFeatureInventory:
    """Tests for _print_feature_inventory output."""

    def test_shows_no_projects(self, tmp_path, capsys):
        """Feature inventory shows 'none registered' when DB has no projects."""
        from summon_claude.cli.config import _print_feature_inventory

        db_path = tmp_path / "registry.db"
        _print_feature_inventory(db_path, {})

        out = capsys.readouterr().out
        assert "none registered" in out

    def test_db_failure_does_not_show_getting_started(self, tmp_path, capsys):
        """Feature inventory suppresses 'Getting started' nudge on DB failure."""
        from summon_claude.cli.config import _print_feature_inventory

        db_path = tmp_path / "registry.db"
        with patch("summon_claude.cli.config.asyncio.run", side_effect=OSError("DB fail")):
            _print_feature_inventory(db_path, {})

        out = capsys.readouterr().out
        assert "Getting started" not in out


class TestIncludeGlobalToken:
    """Tests for the INCLUDE_GLOBAL_TOKEN."""

    def test_include_global_token_defined(self):
        from summon_claude.sessions.hook_types import INCLUDE_GLOBAL_TOKEN

        assert INCLUDE_GLOBAL_TOKEN == "$INCLUDE_GLOBAL"
