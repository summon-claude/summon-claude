"""Guard tests for ConfigOption registry — prevents drift with SummonConfig."""

from __future__ import annotations

import pytest

from summon_claude.config import (
    CONFIG_OPTIONS,
    SummonConfig,
    get_config_default,
)


class TestConfigOptionRegistryGuard:
    """Ensure CONFIG_OPTIONS stays in sync with SummonConfig.model_fields."""

    def test_every_config_field_has_option(self):
        """Every SummonConfig field must have a corresponding ConfigOption."""
        option_fields = {opt.field_name for opt in CONFIG_OPTIONS}
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

    def test_scribe_slack_options_need_both_flags(self):
        """Scribe Slack browser/channels need both scribe and slack enabled."""
        cfg_scribe_only = {"SUMMON_SCRIBE_ENABLED": "true"}
        cfg_both = {"SUMMON_SCRIBE_ENABLED": "true", "SUMMON_SCRIBE_SLACK_ENABLED": "true"}

        browser_opt = next(o for o in CONFIG_OPTIONS if o.field_name == "scribe_slack_browser")
        assert browser_opt.visible is not None
        assert not browser_opt.visible(cfg_scribe_only)
        assert browser_opt.visible(cfg_both)

    @pytest.mark.parametrize("bool_value", ["true", "1", "yes", "True", "YES"])
    def test_scribe_enabled_accepts_truthy_values(self, bool_value: str):
        """Visibility predicate should accept all truthy boolean strings."""
        cfg = {"SUMMON_SCRIBE_ENABLED": bool_value}
        scan_opt = next(o for o in CONFIG_OPTIONS if o.field_name == "scribe_scan_interval_minutes")
        assert scan_opt.visible is not None
        assert scan_opt.visible(cfg)


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


class TestWorkflowToken:
    """Tests for the GLOBAL_WORKFLOW_TOKEN."""

    def test_global_workflow_token_defined(self):
        from summon_claude.sessions.hook_types import GLOBAL_WORKFLOW_TOKEN

        assert GLOBAL_WORKFLOW_TOKEN == "$GLOBAL_WORKFLOW"

    def test_include_global_token_unchanged(self):
        """Verify INCLUDE_GLOBAL_TOKEN wasn't altered."""
        from summon_claude.sessions.hook_types import INCLUDE_GLOBAL_TOKEN

        assert INCLUDE_GLOBAL_TOKEN == "$INCLUDE_GLOBAL"
