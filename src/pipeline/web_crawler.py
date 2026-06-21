import logging
from typing import Optional
from urllib.parse import urlparse

import requests
from readability import Document
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 30
MAX_CONTENT_LENGTH = 5 * 1024 * 1024


def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def fetch_url(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[str]:
    if not _is_valid_url(url):
        logger.warning(f"Invalid URL: {url}")
        return None

    try:
        response = requests.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            allow_redirects=True,
            stream=True,
        )
        response.raise_for_status()

        content_length = int(response.headers.get("Content-Length", 0))
        if content_length > MAX_CONTENT_LENGTH:
            logger.warning(f"URL content too large: {url}, size={content_length}")
            return None

        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            logger.warning(f"URL is not HTML: {url}, content-type={content_type}")
            return None

        html = response.text
        return html

    except requests.RequestException as e:
        logger.error(f"Failed to fetch URL {url}: {e}")
        return None


def extract_main_content(html: str, url: str = "") -> str:
    if not html:
        return ""

    try:
        doc = Document(html, url=url)
        title = doc.title() or ""
        content_html = doc.summary(html_partial=True) or ""

        soup = BeautifulSoup(content_html, "lxml")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)

        if title:
            text = title + "\n\n" + text

        return text

    except Exception as e:
        logger.error(f"Readability extraction failed: {e}")
        try:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)
        except Exception as e2:
            logger.error(f"Fallback extraction also failed: {e2}")
            return ""


def fetch_and_extract(url: str) -> Optional[str]:
    html = fetch_url(url)
    if not html:
        return None
    return extract_main_content(html, url)
