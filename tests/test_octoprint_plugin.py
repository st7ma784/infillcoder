"""
Tests for OctoPrint InfillCode plugin.

These tests mock the octoprint module to enable testing without OctoPrint installed.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, Mock, patch, PropertyMock
from pathlib import Path


# Mock octoprint module before importing the plugin
@pytest.fixture(scope="session", autouse=True)
def mock_octoprint():
    """Mock the octoprint module for testing."""
    import sys
    
    # Create distinct mock classes for each plugin interface
    class SettingsPlugin:
        pass
    
    class AssetPlugin:
        pass
    
    class TemplatePlugin:
        pass
    
    class EventHandlerPlugin:
        pass
    
    class SimpleApiPlugin:
        pass
    
    class StartupPlugin:
        pass
    
    class ProgressPlugin:
        pass
    
    # Create mock octoprint module hierarchy
    octoprint_mock = MagicMock()
    octoprint_mock.plugin = MagicMock()
    octoprint_mock.plugin.SettingsPlugin = SettingsPlugin
    octoprint_mock.plugin.AssetPlugin = AssetPlugin
    octoprint_mock.plugin.TemplatePlugin = TemplatePlugin
    octoprint_mock.plugin.EventHandlerPlugin = EventHandlerPlugin
    octoprint_mock.plugin.SimpleApiPlugin = SimpleApiPlugin
    octoprint_mock.plugin.StartupPlugin = StartupPlugin
    octoprint_mock.plugin.ProgressPlugin = ProgressPlugin
    
    sys.modules["octoprint"] = octoprint_mock
    sys.modules["octoprint.plugin"] = octoprint_mock.plugin


@pytest.fixture
def plugin_instance():
    """Create an instance of InfillCodePlugin with mocked dependencies."""
    from octoprint_plugin.infillcode import InfillCodePlugin
    
    plugin = InfillCodePlugin()
    
    # Mock the logger
    plugin._logger = Mock()
    
    # Mock the settings
    plugin._settings = Mock()
    plugin._settings.get = MagicMock(return_value=None)
    plugin._settings.set = Mock()
    
    # Mock the printer
    plugin._printer = Mock()
    plugin._printer.pause_print = Mock()
    
    # Mock the file manager
    plugin._file_manager = Mock()
    plugin._file_manager.path_on_disk = Mock(return_value="/path/to/file.gcode")
    
    # Mock the plugin manager
    plugin._plugin_manager = Mock()
    plugin._plugin_manager.send_plugin_message = Mock()
    
    # Plugin identifier
    plugin._identifier = "infillcode"
    
    # Initialize the plugin state
    plugin.initialize()
    
    return plugin


class TestInfillCodePluginInitialization:
    """Test plugin initialization and state management."""
    
    def test_plugin_initializes_state(self, plugin_instance):
        """Test that plugin initializes state correctly."""
        assert plugin_instance._last_fingerprint_check_pct is None
        assert plugin_instance._fingerprint_history == []
        assert plugin_instance._consecutive_failures == 0

    def test_get_settings_defaults(self, plugin_instance):
        """Test that default settings are configured."""
        defaults = plugin_instance.get_settings_defaults()
        
        assert "db_path" in defaults
        assert "snapshot_url" in defaults
        assert "nominal_spacing_mm" in defaults
        assert "auto_resume" in defaults
        assert defaults["auto_resume"] is True


class TestInfillCodePluginAssets:
    """Test plugin asset registration."""
    
    def test_get_assets(self, plugin_instance):
        """Test that plugin registers CSS and JS assets."""
        assets = plugin_instance.get_assets()
        
        assert "js" in assets
        assert "css" in assets
        assert len(assets["js"]) > 0
        assert len(assets["css"]) > 0


class TestInfillCodePluginTemplates:
    """Test plugin template registration."""
    
    def test_get_template_configs(self, plugin_instance):
        """Test that plugin registers templates."""
        templates = plugin_instance.get_template_configs()
        
        assert len(templates) >= 2
        assert any(t["type"] == "sidebar" for t in templates)
        assert any(t["type"] == "settings" for t in templates)


class TestFingerprintTracking:
    """Test fingerprint detection and tracking logic."""
    
    def test_record_check_result_passed(self, plugin_instance):
        """Test recording a successful fingerprint check."""
        plugin_instance._record_check_result(passed=True)
        
        assert plugin_instance._fingerprint_history == [True]
        assert plugin_instance._consecutive_failures == 0

    def test_record_check_result_failed(self, plugin_instance):
        """Test recording a failed fingerprint check."""
        plugin_instance._record_check_result(passed=False)
        
        assert plugin_instance._fingerprint_history == [False]
        assert plugin_instance._consecutive_failures == 1

    def test_consecutive_failures_reset(self, plugin_instance):
        """Test that consecutive failures reset on success."""
        plugin_instance._record_check_result(passed=False)
        plugin_instance._record_check_result(passed=False)
        plugin_instance._record_check_result(passed=True)
        
        assert plugin_instance._consecutive_failures == 0

    def test_health_score_calculation(self, plugin_instance):
        """Test health score calculation."""
        # Add history: 2 passed, 1 failed
        plugin_instance._record_check_result(passed=True)
        plugin_instance._record_check_result(passed=True)
        plugin_instance._record_check_result(passed=False)
        
        health = plugin_instance._health_score()
        assert health == 67  # 2/3 ≈ 67%

    def test_health_score_empty_history(self, plugin_instance):
        """Test that health score returns None with empty history."""
        assert plugin_instance._health_score() is None

    def test_health_window_limit(self, plugin_instance):
        """Test that health history is limited to window size."""
        # Add more results than window size
        for i in range(plugin_instance._HEALTH_WINDOW + 5):
            plugin_instance._record_check_result(passed=i % 2 == 0)
        
        assert len(plugin_instance._fingerprint_history) == plugin_instance._HEALTH_WINDOW


class TestPrintStateManagement:
    """Test print state reset and management."""
    
    def test_reset_print_state(self, plugin_instance):
        """Test that print state is properly reset."""
        # Set some state
        plugin_instance._last_fingerprint_check_pct = 50
        plugin_instance._fingerprint_history = [True, False]
        plugin_instance._consecutive_failures = 2
        
        # Reset
        plugin_instance._reset_print_state()
        
        assert plugin_instance._last_fingerprint_check_pct is None
        assert plugin_instance._fingerprint_history == []
        assert plugin_instance._consecutive_failures == 0


class TestAutoPause:
    """Test auto-pause functionality."""
    
    def test_maybe_auto_pause_disabled(self, plugin_instance):
        """Test that auto-pause does nothing when disabled."""
        plugin_instance._settings.get.return_value = 0  # disabled
        plugin_instance._consecutive_failures = 5
        
        plugin_instance._maybe_auto_pause(50)
        
        # Should not pause
        plugin_instance._printer.pause_print.assert_not_called()

    def test_maybe_auto_pause_threshold_not_reached(self, plugin_instance):
        """Test that auto-pause doesn't trigger before threshold."""
        plugin_instance._settings.get.return_value = 5  # threshold = 5
        plugin_instance._consecutive_failures = 3
        
        plugin_instance._maybe_auto_pause(50)
        
        # Should not pause
        plugin_instance._printer.pause_print.assert_not_called()

    def test_maybe_auto_pause_threshold_reached(self, plugin_instance):
        """Test that auto-pause triggers when threshold is reached."""
        plugin_instance._settings.get.return_value = 3  # threshold = 3
        plugin_instance._consecutive_failures = 3
        
        plugin_instance._maybe_auto_pause(50)
        
        # Should pause
        plugin_instance._printer.pause_print.assert_called_once()

    def test_maybe_auto_pause_handles_exception(self, plugin_instance):
        """Test that auto-pause handles pause exceptions gracefully."""
        plugin_instance._settings.get.return_value = 1  # threshold = 1
        plugin_instance._consecutive_failures = 1
        plugin_instance._printer.pause_print.side_effect = Exception("Printer error")
        
        # Should not raise exception
        plugin_instance._maybe_auto_pause(50)
        plugin_instance._logger.error.assert_called()


class TestEventHandling:
    """Test event handler functionality."""
    
    def test_on_event_print_started(self, plugin_instance):
        """Test that PrintStarted event resets state."""
        plugin_instance._fingerprint_history = [True, False]
        plugin_instance._consecutive_failures = 2
        
        plugin_instance.on_event("PrintStarted", {})
        
        assert plugin_instance._fingerprint_history == []
        assert plugin_instance._consecutive_failures == 0

    def test_on_event_print_done(self, plugin_instance):
        """Test that PrintDone event triggers analysis."""
        with patch.object(plugin_instance, "_analyse_snapshot") as mock_analyse:
            plugin_instance.on_event("PrintDone", {})
            plugin_instance._reset_print_state()
            
            # State should be reset
            assert plugin_instance._fingerprint_history == []
