# NOTE: This test module exercises dynamically imported local scripts plus fake
# request/session objects, which confuses static signature checking more than it
# helps. Runtime coverage is what matters here, so we relax those diagnostics.
# pyright: reportCallIssue=false, reportAttributeAccessIssue=false
import unittest

import requests

import download_mk_lore
import scrape_pirates


class FakeResponse:
    def __init__(self, *, json_payload=None, content: bytes = b"<html><body><p>Hello</p></body></html>") -> None:
        self._json_payload = json_payload
        self.content = content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._json_payload


class RecordingSession:
    def __init__(self, *, response: FakeResponse | None = None, exception: Exception | None = None) -> None:
        self.response = response or FakeResponse()
        self.exception = exception
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.exception is not None:
            raise self.exception
        return self.response


class DownloadMkLoreHttpTests(unittest.TestCase):
    def test_get_soup_uses_timeout_and_headers(self) -> None:
        session = RecordingSession()

        soup = download_mk_lore.get_soup("https://example.com", session=session)

        self.assertEqual(session.calls[0]["timeout"], download_mk_lore.REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(session.calls[0]["headers"], download_mk_lore.HEADERS)
        self.assertEqual(soup.find("p").get_text(), "Hello")

    def test_get_soup_returns_none_on_request_failure(self) -> None:
        session = RecordingSession(exception=requests.RequestException("boom"))

        soup = download_mk_lore.get_soup("https://example.com", session=session)

        self.assertIsNone(soup)


class ScrapePiratesHttpTests(unittest.TestCase):
    def test_get_all_page_titles_uses_timeout(self) -> None:
        session = RecordingSession(
            response=FakeResponse(
                json_payload={"query": {"allpages": [{"title": "Jack Sparrow"}]}}
            )
        )

        titles = list(scrape_pirates.get_all_page_titles(limit=1, session=session))

        self.assertEqual(titles, ["Jack Sparrow"])
        self.assertEqual(session.calls[0]["timeout"], scrape_pirates.REQUEST_TIMEOUT_SECONDS)

    def test_get_all_page_titles_handles_request_exception(self) -> None:
        session = RecordingSession(exception=requests.RequestException("boom"))

        titles = list(scrape_pirates.get_all_page_titles(limit=1, session=session))

        self.assertEqual(titles, [])


if __name__ == "__main__":
    unittest.main()
