from __future__ import annotations

import logging
import re
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse
import httpx

from .base import SearchProvider, SearchResult

logger = logging.getLogger("agent_platform.foundation_research.search.duckduckgo")

# Publisher domain to authoritative entity mapping
KNOWN_PUBLISHERS = {
    "fhwa.dot.gov": ("Federal Highway Administration (FHWA)", "GOVERNMENT_AGENCY"),
    "usace.army.mil": ("U.S. Army Corps of Engineers (USACE)", "GOVERNMENT_AGENCY"),
    "txdot.gov": ("Texas Department of Transportation (TxDOT)", "GOVERNMENT_AGENCY"),
    "post-tensioning.org": ("Post-Tensioning Institute (PTI)", "STANDARDS_ORGANIZATION"),
    "asce.org": ("American Society of Civil Engineers (ASCE)", "STANDARDS_ORGANIZATION"),
    "ascelibrary.org": ("ASCE Library / Geo-Institute", "STANDARDS_ORGANIZATION"),
    "dfi.org": ("Deep Foundations Institute (DFI)", "STANDARDS_ORGANIZATION"),
    "iccsafe.org": ("International Code Council (ICC / IBC)", "STANDARDS_ORGANIZATION"),
    "concrete.org": ("American Concrete Institute (ACI)", "STANDARDS_ORGANIZATION"),
    "astm.org": ("ASTM International", "STANDARDS_ORGANIZATION"),
    "bts.gov": ("Bureau of Transportation Statistics", "GOVERNMENT_AGENCY"),
    "rosap.ntl.bts.gov": ("National Transportation Library", "GOVERNMENT_AGENCY"),
    "nap.edu": ("National Academies Press / TRB", "ACADEMIC_RESEARCH"),
    "sciencedirect.com": ("ScienceDirect Geotechnical Engineering", "ACADEMIC_RESEARCH"),
    "springer.com": ("Springer Geotechnical Research", "ACADEMIC_RESEARCH"),
    "pilebuck.com": ("Pile Buck Foundation Magazine", "INDUSTRY_TECHNICAL"),
    "geotechdata.info": ("Geotechnical Engineering Directory", "INDUSTRY_TECHNICAL"),
    "geoengineer.org": ("Geoengineer.org Technical Information", "INDUSTRY_TECHNICAL"),
}


class DuckDuckGoSearchProvider(SearchProvider):
    """Executes live technical web queries using DuckDuckGo public endpoints."""

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout = timeout_seconds
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        url = f"https://html.duckduckgo.com/html/?q={httpx.URL(query).raw_path.decode('ascii') if hasattr(httpx.URL(query), 'raw_path') else query}"
        target_url = "https://html.duckduckgo.com/html/"
        logger.info("Executing DuckDuckGo technical research query: '%s'", query)

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=self.headers) as client:
                resp = await client.post(target_url, data={"q": query})
                if resp.status_code != 200:
                    logger.warning("DuckDuckGo returned status %d for query '%s'", resp.status_code, query)
                    return []

                return self._parse_ddg_html(resp.text, max_results=max_results)
        except Exception as exc:
            logger.warning("DuckDuckGo search failed (%s): %s", type(exc).__name__, exc)
            return []

    def _parse_ddg_html(self, html: str, max_results: int = 5) -> List[SearchResult]:
        results: List[SearchResult] = []
        blocks = re.findall(r'<div class="result results_links results_links_deep[^"]*">(.*?)</div>\s*</div>', html, re.DOTALL)

        for b in blocks:
            # 1. Extract Target URL
            m_link = re.search(r'href="([^"]+)"', b)
            if not m_link:
                continue
            raw_href = m_link.group(1)
            target_url = self._extract_clean_url(raw_href)
            if not target_url or target_url.startswith("//duckduckgo.com"):
                continue

            # 2. Extract Title
            m_title = re.search(r'<h2 class="result__title">\s*<a[^>]*>(.*?)</a>', b, re.DOTALL)
            if not m_title:
                m_title = re.search(r'<a class="result__a"[^>]*>(.*?)</a>', b, re.DOTALL)
            title = re.sub(r'<[^>]+>', '', m_title.group(1)).strip() if m_title else "Technical Engineering Publication"

            # 3. Extract Snippet
            m_snippet = re.search(r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>', b, re.DOTALL)
            snippet = re.sub(r'<[^>]+>', '', m_snippet.group(1)).strip() if m_snippet else ""
            if not snippet:
                m_body = re.search(r'<div class="result__snippet[^"]*">(.*?)</div>', b, re.DOTALL)
                snippet = re.sub(r'<[^>]+>', '', m_body.group(1)).strip() if m_body else ""

            # 4. Determine Publisher and Authority Category
            publisher, authority = self._identify_publisher_and_authority(target_url)

            # 5. Extract Publication Date from snippet if mentioned
            pub_date = self._extract_publication_date(snippet)

            results.append(SearchResult(
                title=title,
                url=target_url,
                snippet=snippet,
                publisher=publisher,
                publication_date=pub_date,
                authority_category=authority,
            ))

            if len(results) >= max_results:
                break

        return results

    def _extract_clean_url(self, raw_href: str) -> str:
        if "uddg=" in raw_href:
            parsed = urlparse(raw_href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        if raw_href.startswith("//"):
            return "https:" + raw_href
        return raw_href

    def _identify_publisher_and_authority(self, url: str) -> tuple[str, str]:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        for known_domain, (pub_name, auth_cat) in KNOWN_PUBLISHERS.items():
            if domain == known_domain or domain.endswith("." + known_domain):
                return pub_name, auth_cat

        if domain.endswith(".gov") or domain.endswith(".mil"):
            return f"Government Agency ({domain})", "GOVERNMENT_AGENCY"
        if domain.endswith(".edu"):
            return f"Academic Research Institution ({domain})", "ACADEMIC_RESEARCH"
        if domain.endswith(".org"):
            return f"Engineering Organization ({domain})", "STANDARDS_ORGANIZATION"

        return domain.capitalize(), "INDUSTRY_TECHNICAL"

    def _extract_publication_date(self, text: str) -> Optional[str]:
        # Search for Month YYYY or YYYY-MM-DD or (YYYY)
        m = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b", text, re.IGNORECASE)
        if m:
            return m.group(0)
        m_iso = re.search(r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b", text)
        if m_iso:
            return m_iso.group(1)
        m_year = re.search(r"\b(20[0-2]\d|199\d)\b", text)
        if m_year:
            return m_year.group(1)
        return None

    async def fetch_page_content(self, url: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=self.headers) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    text = re.sub(r'<script[^>]*>.*?</script>', '', resp.text, flags=re.DOTALL)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    return re.sub(r'\s+', ' ', text).strip()[:4000]
        except Exception as exc:
            logger.debug("Failed to fetch full page content for %s: %s", url, exc)
        return None
