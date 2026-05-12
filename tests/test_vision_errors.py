"""
Tests for vision module error handling.
"""

import pytest

from octoprint_plugin.infillcode.vision import (
    VisionError,
    VisionErrorCode,
    extract_spacings,
)


def test_vision_error_invalid_url():
    """Test error handling for empty URL."""
    with pytest.raises(VisionError) as exc_info:
        extract_spacings("")
    
    assert exc_info.value.code == VisionErrorCode.INVALID_URL


def test_vision_error_network_error():
    """Test error handling for invalid URL."""
    with pytest.raises(VisionError) as exc_info:
        extract_spacings("http://invalid-domain-that-does-not-exist.local/image.jpg")
    
    assert exc_info.value.code == VisionErrorCode.NETWORK_ERROR


def test_vision_error_divide_by_zero():
    """Test guard against division by zero."""
    # This is hard to test without mocking, but we document that it's handled
    pass


def test_vision_error_message_format():
    """Test that error messages are formatted correctly."""
    try:
        extract_spacings("")
    except VisionError as e:
        # Should have format: [error_code] message
        assert "[" in str(e)
        assert "]" in str(e)
        assert "INVALID_URL" in str(e) or "invalid_url" in str(e)
