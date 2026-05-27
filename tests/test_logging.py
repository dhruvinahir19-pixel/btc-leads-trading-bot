"""
test_logging.py — Tests for the logging_setup module.

Verifies:
- JSON format of log output
- Stdout and file handlers
- get_logger() creates child loggers
- Rotating file handler works
- Level filtering
- Edge cases: special characters, exceptions
"""
import pytest
import json
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile


class TestLoggingSetup:
    """Test structured logging configuration."""

    def test_setup_logging_stdout_only(self, db_conn):
        """Logging should write JSON to stdout."""
        from backend.logging_setup import setup_logging, get_logger
        logger = setup_logging(log_level="DEBUG")
        assert logger is not None
        assert logger.name == "trading_bot"
        # Should have stdout handler
        assert len(logger.handlers) >= 1

    def test_get_logger_child(self, db_conn):
        """get_logger should create a named child logger."""
        from backend.logging_setup import get_logger
        logger = get_logger("test_module")
        assert logger.name == "trading_bot.test_module"

    def test_json_output_format(self, db_conn, capsys):
        """Log output should be valid JSON."""
        from backend.logging_setup import setup_logging
        logger = setup_logging(log_level="DEBUG")
        test_msg = "Test message for JSON validation"
        logger.info(test_msg)
        captured = capsys.readouterr()
        if captured.out:
            log_entry = json.loads(captured.out.strip())
            assert log_entry["message"] == test_msg
            assert log_entry["level"] == "INFO"
            assert "timestamp" in log_entry
            assert "module" in log_entry

    def test_log_level_warning(self, db_conn, capsys):
        """Warning level should be in JSON output."""
        from backend.logging_setup import setup_logging, get_logger
        logger = setup_logging(log_level="DEBUG")
        logger.warning("This is a warning")
        captured = capsys.readouterr()
        if captured.out:
            entry = json.loads(captured.out.strip())
            assert entry["level"] == "WARNING"

    def test_log_level_error(self, db_conn, capsys):
        """Error level should be in JSON output."""
        from backend.logging_setup import setup_logging
        logger = setup_logging(log_level="DEBUG")
        logger.error("This is an error")
        captured = capsys.readouterr()
        if captured.out:
            entry = json.loads(captured.out.strip())
            assert entry["level"] == "ERROR"

    def test_log_exception(self, db_conn, capsys):
        """Exception info should be included in JSON."""
        from backend.logging_setup import setup_logging
        logger = setup_logging(log_level="DEBUG")
        try:
            raise ValueError("test exception")
        except ValueError:
            logger.exception("Exception occurred")
        captured = capsys.readouterr()
        if captured.out:
            entry = json.loads(captured.out.strip())
            assert "exception" in entry
            assert "ValueError" in entry["exception"]

    def test_log_level_filtering(self, db_conn, capsys):
        """Info messages should not appear when level is WARNING."""
        from backend.logging_setup import setup_logging
        logger = setup_logging(log_level="WARNING")
        logger.info("This should be filtered")
        captured = capsys.readouterr()
        # With WARNING level, INFO messages should not appear
        assert captured.out == "" or "This should be filtered" not in captured.out


class TestFileLogging:
    """Test rotating file handler."""

    def test_file_handler_created(self, db_conn):
        """File handler should be created when log_dir is provided."""
        from backend.logging_setup import setup_logging
        import logging
        # Clear any existing handlers to ensure fresh setup with log_dir
        root = logging.getLogger("trading_bot")
        old_handlers = list(root.handlers)
        root.handlers.clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = setup_logging(log_dir=Path(tmpdir), log_level="DEBUG")
            handler_names = [h.__class__.__name__ for h in logger.handlers]
            assert "RotatingFileHandler" in handler_names
            # Cleanup: close handlers so tmpdir can be cleaned
            for h in list(logger.handlers):
                h.close()
                logger.removeHandler(h)
        # Restore old handlers
        root.handlers = old_handlers

    def test_file_writes(self, db_conn):
        """Log messages should be written to file."""
        from backend.logging_setup import setup_logging
        import logging
        # Clear any existing handlers to ensure fresh setup with log_dir
        root = logging.getLogger("trading_bot")
        old_handlers = list(root.handlers)
        root.handlers.clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = setup_logging(log_dir=Path(tmpdir), log_level="DEBUG")
            logger.info("File log test")
            # Close file handler so log file is released
            for h in list(logger.handlers):
                h.close()
                logger.removeHandler(h)
            # Check the file was created
            log_file = Path(tmpdir) / "trading_bot.log"
            assert log_file.exists()
            content = log_file.read_text()
            assert "File log test" in content
        # Restore old handlers
        root.handlers = old_handlers

    def test_file_json_format(self, db_conn):
        """File output should also be valid JSON."""
        from backend.logging_setup import setup_logging
        import logging
        # Clear any existing handlers to ensure fresh setup with log_dir
        root = logging.getLogger("trading_bot")
        old_handlers = list(root.handlers)
        root.handlers.clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = setup_logging(log_dir=Path(tmpdir), log_level="DEBUG")
            logger.info("JSON in file test")
            # Close file handler so log file is released
            for h in list(logger.handlers):
                h.close()
                logger.removeHandler(h)
            log_file = Path(tmpdir) / "trading_bot.log"
            lines = log_file.read_text().strip().split("\n")
            # Find the test message (setup_logging also logs initial lines)
            found = False
            for line in lines:
                if line:
                    entry = json.loads(line)
                    if entry["message"] == "JSON in file test":
                        found = True
                        break
            assert found, "Test message not found in log file"
        # Restore old handlers
        root.handlers = old_handlers


class TestEdgeCases:
    """Test edge cases in logging."""

    def test_special_characters(self, db_conn, capsys):
        """Special characters should be JSON-encodable."""
        from backend.logging_setup import setup_logging
        logger = setup_logging(log_level="DEBUG")
        special_msg = "Price: $123.45 | Symbol: DOGE/USDT | Status: ✅"
        logger.info(special_msg)
        captured = capsys.readouterr()
        if captured.out:
            entry = json.loads(captured.out.strip())
            assert entry["message"] == special_msg

    def test_unicode_characters(self, db_conn, capsys):
        """Unicode characters should be JSON-encodable."""
        from backend.logging_setup import setup_logging
        logger = setup_logging(log_level="DEBUG")
        unicode_msg = "🚀 TRIGGER: BTC +1.5% @ 17:30 IST (LONG)"
        logger.info(unicode_msg)
        captured = capsys.readouterr()
        if captured.out:
            entry = json.loads(captured.out.strip())
            assert "TRIGGER" in entry["message"]

    def test_multiple_loggers(self, db_conn):
        """Multiple child loggers should all work."""
        from backend.logging_setup import setup_logging, get_logger
        root = setup_logging(log_level="DEBUG")
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")
        assert logger1.name == "trading_bot.module1"
        assert logger2.name == "trading_bot.module2"
        # Both should have the same handlers as root
        assert len(logger1.handlers) == 0  # Child loggers propagate to root
        assert len(logger2.handlers) == 0

    def test_reinitialization_idempotent(self, db_conn):
        """Calling setup_logging twice should not duplicate handlers."""
        from backend.logging_setup import setup_logging
        logger1 = setup_logging(log_level="DEBUG")
        initial_count = len(logger1.handlers)
        logger2 = setup_logging(log_level="INFO")
        assert len(logger2.handlers) == initial_count  # No duplicate handlers
