# File to test edge cases in the trading logic

import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from parser import generate_occ_symbol, parse_discord_signal


class TestGenerateOccSymbol(unittest.TestCase):
    """Tests for the pure OCC symbol generation function."""

    def setUp(self):
        self.year = datetime.now().strftime("%y")

    def test_spy_put(self):
        result = generate_occ_symbol("SPY", "03/10", "P", "661")
        self.assertEqual(result, f"SPY{self.year}0310P00661000")

    def test_hood_call(self):
        result = generate_occ_symbol("HOOD", "03/20", "C", "78")
        self.assertEqual(result, f"HOOD{self.year}0320C00078000")

    def test_spx_high_strike(self):
        result = generate_occ_symbol("SPX", "02/26", "C", "6900")
        self.assertEqual(result, f"SPX{self.year}0226C06900000")

    def test_lowercase_ticker_and_type_are_uppercased(self):
        result = generate_occ_symbol("spy", "03/10", "p", "661")
        self.assertEqual(result, f"SPY{self.year}0310P00661000")

    def test_decimal_strike(self):
        result = generate_occ_symbol("SPY", "03/10", "C", "682.5")
        self.assertEqual(result, f"SPY{self.year}0310C00682500")


class TestParseDiscordSignal(unittest.TestCase):
    """Tests for parse_discord_signal — Gemini API is mocked throughout."""

    def _mock_response(self, data: dict):
        mock = MagicMock()
        mock.text = json.dumps(data)
        return mock

    # --- ENTRY messages ---

    @patch("parser.client")
    def test_entry_spy_put(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response(
            {"type": "ENTRY", "ticker": "SPY", "exp_date": "02/27", "strike": "682", "opt_type": "P", "price": 2.00}
        )
        result = parse_discord_signal("@Premium  **LOTTO**\nSPY here\n02/27 682P\nAvg. 2.00")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "ENTRY")
        self.assertEqual(result["ticker"], "SPY")
        self.assertIn("occ_symbol", result)
        self.assertTrue(result["occ_symbol"].startswith("SPY"))

    @patch("parser.client")
    def test_entry_hood_call(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response(
            {"type": "ENTRY", "ticker": "HOOD", "exp_date": "02/27", "strike": "78", "opt_type": "C", "price": 1.50}
        )
        result = parse_discord_signal("@Premium  *Riskier*\nHOOD here\n02/27 78C\nAvg, 1.50")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "ENTRY")
        self.assertEqual(result["ticker"], "HOOD")
        self.assertIn("occ_symbol", result)
        self.assertTrue(result["occ_symbol"].startswith("HOOD"))

    @patch("parser.client")
    def test_entry_spx_call(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response(
            {"type": "ENTRY", "ticker": "SPX", "exp_date": "02/26", "strike": "6900", "opt_type": "C", "price": 6.00}
        )
        result = parse_discord_signal(
            "@Premium  **HIGH RISK**\nSPX here\n02/26 6900C\nAvg, 6.00\nUsing VIX 20, same plan laid out before^"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "ENTRY")
        self.assertEqual(result["ticker"], "SPX")
        year = datetime.now().strftime("%y")
        self.assertEqual(result["occ_symbol"], f"SPX{year}0226C06900000")

    @patch("parser.client")
    def test_entry_missing_required_field_returns_none(self, mock_client):
        # exp_date is None — parser should reject and return None
        mock_client.models.generate_content.return_value = self._mock_response(
            {"type": "ENTRY", "ticker": "SPY", "exp_date": None, "strike": "682", "opt_type": "P", "price": 2.00}
        )
        result = parse_discord_signal("SPY here\n682P\nAvg. 2.00")
        self.assertIsNone(result)

    # --- EXIT_ALL messages ---

    @patch("parser.client")
    def test_exit_all_stopped_out(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response(
            {"type": "EXIT_ALL", "ticker": "SPY", "exp_date": None, "strike": None, "opt_type": None, "price": None}
        )
        result = parse_discord_signal("@Premium  Stopped out of SPY 🔻\n2026 is the year of the balance")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "EXIT_ALL")
        self.assertEqual(result["ticker"], "SPY")

    @patch("parser.client")
    def test_exit_all_closed(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response(
            {"type": "EXIT_ALL", "ticker": "HOOD", "exp_date": None, "strike": None, "opt_type": None, "price": None}
        )
        result = parse_discord_signal("@Premium  Closed HOOD here")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "EXIT_ALL")
        self.assertEqual(result["ticker"], "HOOD")

    # --- EXIT_PARTIAL messages ---

    @patch("parser.client")
    def test_exit_partial_trim_with_percentage(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response(
            {"type": "EXIT_PARTIAL", "ticker": "SPX", "exp_date": None, "strike": None, "opt_type": None, "price": 8.00}
        )
        result = parse_discord_signal("@Premium  Trim SPX here\n6.00 - 8.00 ✅ 33%\nHolding most.")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "EXIT_PARTIAL")
        self.assertEqual(result["ticker"], "SPX")
        self.assertEqual(result["price"], 8.00)

    @patch("parser.client")
    def test_exit_partial_price_range_uses_highest_price(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response(
            {"type": "EXIT_PARTIAL", "ticker": "SPY", "exp_date": None, "strike": None, "opt_type": None, "price": 4.45}
        )
        result = parse_discord_signal("@Premium  SPY\n2.20 - 4.45 ✅ 102%\nHolding last cons.")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "EXIT_PARTIAL")
        self.assertEqual(result["price"], 4.45)

    @patch("parser.client")
    def test_exit_partial_holding_majority(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response(
            {"type": "EXIT_PARTIAL", "ticker": "SPY", "exp_date": None, "strike": None, "opt_type": None, "price": 1.95}
        )
        result = parse_discord_signal("@Premium  More SPY here\n1.30 - 1.95 ✅ 30%\nHolding majority.")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "EXIT_PARTIAL")

    # --- ADD messages ---

    @patch("parser.client")
    def test_add_to_position(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response(
            {"type": "ADD", "ticker": "SPY", "exp_date": None, "strike": None, "opt_type": None, "price": 1.15}
        )
        result = parse_discord_signal("@Premium  Added to SPY @1.15\nNew Avg, is 1.30 olo")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "ADD")
        self.assertEqual(result["ticker"], "SPY")
        self.assertEqual(result["price"], 1.15)

    # --- IGNORE messages ---

    @patch("parser.client")
    def test_ignore_vix_commentary(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response({"type": "IGNORE"})
        result = parse_discord_signal("@Premium  Heres VIX 20. Bulls better pray they can keep it under.")
        self.assertIsNone(result)

    @patch("parser.client")
    def test_ignore_general_market_chatter(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response({"type": "IGNORE"})
        result = parse_discord_signal(
            "@Premium  Markets cooked, and then we're so back, then markets cooked again, rinse and repeat all 2026."
        )
        self.assertIsNone(result)

    @patch("parser.client")
    def test_ignore_confidence_message(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response({"type": "IGNORE"})
        result = parse_discord_signal(
            "@Premium  HOOD has shown great relative strength all day and continues to contest key 78 level repeatedly."
        )
        self.assertIsNone(result)

    # --- Error handling ---

    @patch("parser.client")
    def test_api_exception_returns_none(self, mock_client):
        mock_client.models.generate_content.side_effect = Exception("API error")
        result = parse_discord_signal("SPY here\n03/10 682P\nAvg. 2.00")
        self.assertIsNone(result)

    @patch("parser.client")
    def test_whitespace_input_is_stripped(self, mock_client):
        mock_client.models.generate_content.return_value = self._mock_response(
            {"type": "ENTRY", "ticker": "SPY", "exp_date": "02/27", "strike": "682", "opt_type": "P", "price": 2.00}
        )
        result = parse_discord_signal("  \nSPY here\n02/27 682P\nAvg. 2.00\n  ")
        self.assertIsNotNone(result)
        mock_client.models.generate_content.assert_called_once()


if __name__ == "__main__":
    unittest.main()
