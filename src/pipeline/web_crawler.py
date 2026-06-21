import logging
import re
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

try:
    from readability import Document
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False
    logger.warning("readability-lxml not installed, using BeautifulSoup fallback only")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

REQUEST_TIMEOUT = 30
MAX_CONTENT_LENGTH = 10 * 1024 * 1024
MIN_TEXT_LENGTH = 50


def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _detect_encoding(response) -> str:
    encoding = getattr(response, "encoding", None)
    if encoding and encoding.lower() not in ("iso-8859-1",):
        return encoding

    apparent = getattr(response, "apparent_encoding", None)
    if apparent:
        return apparent

    content_type = response.headers.get("Content-Type", "")
    charset_match = re.search(r"charset=([\w-]+)", content_type, re.I)
    if charset_match:
        return charset_match.group(1)

    html_meta = re.search(
        rb'<meta[^>]+charset=["\']?([\w-]+)["\']?',
        response.content[:4096],
        re.I,
    )
    if html_meta:
        try:
            return html_meta.group(1).decode("ascii", errors="ignore")
        except Exception:
            pass

    return "utf-8"


def fetch_url(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[str]:
    if not _is_valid_url(url):
        logger.warning(f"Invalid URL: {url}")
        return None

    for attempt in range(2):
        try:
            response = requests.get(
                url,
                headers=DEFAULT_HEADERS,
                timeout=timeout,
                allow_redirects=True,
                verify=False,
            )
            if response.status_code >= 400:
                logger.warning(f"URL returned status {response.status_code}: {url}")
                if attempt == 0 and response.status_code in (403, 429, 500, 502, 503, 504):
                    import time
                    time.sleep(1.5)
                    continue
                if response.status_code == 404:
                    return None

            content_length = int(response.headers.get("Content-Length", len(response.content) or 0))
            if content_length > MAX_CONTENT_LENGTH:
                logger.warning(f"URL content too large: {url}, size={content_length}")
                return None

            content_type = response.headers.get("Content-Type", "")
            if content_type and "text/html" not in content_type and "application/xhtml" not in content_type:
                if not any(t in content_type for t in ["text/", "application/xml", "json"]):
                    logger.warning(f"URL is not text content: {url}, content-type={content_type}")
                    return None

            encoding = _detect_encoding(response)
            try:
                response.encoding = encoding
                html = response.text
            except Exception:
                try:
                    html = response.content.decode("utf-8", errors="replace")
                except Exception:
                    html = response.content.decode("gbk", errors="replace")

            if html and len(html.strip()) > 100:
                return html

        except requests.exceptions.SSLError:
            try:
                response = requests.get(
                    url,
                    headers=DEFAULT_HEADERS,
                    timeout=timeout,
                    allow_redirects=True,
                    verify=False,
                )
                encoding = _detect_encoding(response)
                response.encoding = encoding
                return response.text
            except Exception as e:
                logger.error(f"Fetch URL (SSL retry) failed {url}: {e}")
        except requests.RequestException as e:
            logger.error(f"Failed to fetch URL {url}: {e}")
            if attempt == 0:
                import time
                time.sleep(1)
                continue

    return None


def _extract_article_readability(html: str, url: str = "") -> Optional[str]:
    if not READABILITY_AVAILABLE:
        return None
    try:
        doc = Document(html, url=url)
        title = doc.title() or ""
        content_html = doc.summary(html_partial=True) or ""

        if not content_html or len(content_html.strip()) < 50:
            if title:
                return title
            return None

        soup = BeautifulSoup(content_html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript", "svg", "form", "button"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        if title and title not in text[:200]:
            text = title + "\n\n" + text
        return text
    except Exception as e:
        logger.debug(f"Readability extraction failed: {e}")
        return None


def _extract_article_bs4(html: str, url: str = "") -> str:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            logger.error(f"BeautifulSoup parse failed: {e}")
            return ""

    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    for tag in soup.find_all(["script", "style", "noscript", "svg", "iframe", "form", "button", "input", "select"]):
        try:
            tag.decompose()
        except Exception:
            pass

    candidates = []

    for selector in [
        "article",
        "main",
        ".article",
        ".content",
        ".post",
        ".entry",
        ".news",
        ".detail",
        ".body",
        "#article",
        "#content",
        "#post",
        ".article-content",
        ".post-content",
        ".entry-content",
        ".news-content",
        "[itemprop='articleBody']",
        "[role='main']",
    ]:
        found = soup.select(selector)
        for el in found:
            text = el.get_text(separator="\n", strip=True)
            if len(text) >= MIN_TEXT_LENGTH:
                candidates.append((len(text), text))

    if not candidates:
        paragraphs = soup.find_all(["p", "h1", "h2", "h3", "h4", "li", "div"])
        text_parts = []
        for p in paragraphs:
            t = p.get_text(strip=True)
            if len(t) >= 8:
                text_parts.append(t)
        combined = "\n".join(text_parts)
        if len(combined) >= MIN_TEXT_LENGTH:
            candidates.append((len(combined), combined))

    if not candidates:
        full_text = soup.get_text(separator="\n", strip=True)
        if len(full_text) >= MIN_TEXT_LENGTH:
            lines = [l.strip() for l in full_text.split("\n") if len(l.strip()) >= 5]
            candidates.append((len(lines), "\n".join(lines)))

    if not candidates:
        return title

    candidates.sort(reverse=True, key=lambda x: x[0])
    best_text = candidates[0][1]

    if title and title not in best_text[:300]:
        best_text = title + "\n\n" + best_text

    return best_text


def _clean_extracted_text(text: str) -> str:
    if not text:
        return ""

    lines = text.split("\n")
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue

        if len(s) < 3 and not any('\u4e00' <= c <= '\u9fff' for c in s):
            continue

        s = re.sub(r'\s{2,}', ' ', s)
        cleaned.append(s)

    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()

    return "\n".join(cleaned)


def extract_main_content(html: str, url: str = "") -> str:
    if not html:
        return ""

    text = _extract_article_readability(html, url)
    if text and len(text.strip()) >= MIN_TEXT_LENGTH:
        cleaned = _clean_extracted_text(text)
        if len(cleaned) >= MIN_TEXT_LENGTH:
            return cleaned

    text = _extract_article_bs4(html, url)
    cleaned = _clean_extracted_text(text)
    if cleaned:
        return cleaned

    return ""


def fetch_and_extract(url: str) -> Optional[str]:
    logger.info(f"Fetching and extracting: {url}")
    html = fetch_url(url)
    if not html:
        logger.warning(f"No HTML retrieved for {url}")
        return None

    logger.info(f"Got {len(html)} chars HTML from {url}")
    content = extract_main_content(html, url)

    if not content or len(content.strip()) < MIN_TEXT_LENGTH:
        logger.warning(f"Extracted content too short for {url}: {len(content or '')} chars")
        if content and len(content.strip()) >= 20:
            return content.strip()
        return None

    logger.info(f"Extracted {len(content)} chars text from {url}")
    return content.strip()
