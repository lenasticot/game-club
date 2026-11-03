"""rawg._get turns network/HTTP failures into RawgError."""

import io
import unittest
import urllib.error
from unittest.mock import patch

from gameclub import rawg


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "err", {},  # type: ignore
                                  io.BytesIO(b""))


class TestRawgErrors(unittest.TestCase):
    def setUp(self) -> None:
        env = patch.dict("os.environ", {"RAWG_API_KEY": "k"})
        env.start()
        self.addCleanup(env.stop)

    def fail_with(self, exc: Exception) -> rawg.RawgError:
        with patch("urllib.request.urlopen", side_effect=exc):
            with self.assertRaises(rawg.RawgError) as cm:
                rawg.fetch("hollow knight", "now")
        return cm.exception

    def test_404_is_not_found(self) -> None:
        self.assertIsInstance(self.fail_with(_http_error(404)),
                              rawg.RawgNotFound)

    def test_401_mentions_the_key(self) -> None:
        e = self.fail_with(_http_error(401))
        self.assertNotIsInstance(e, rawg.RawgNotFound)
        self.assertIn("API key", str(e))

    def test_unreachable(self) -> None:
        e = self.fail_with(urllib.error.URLError("timed out"))
        self.assertIn("could not reach RAWG", str(e))


if __name__ == "__main__":
    unittest.main()
