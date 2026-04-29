"""Source search for Feature 1 claim checking.

Tavily is used when configured for broad web search. PubMed is the no-key
fallback so the MVP still performs real source lookup for fitness science.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List
from urllib.parse import quote_plus

import httpx

from .. import config
from ..models import SourceCandidate
from . import retriever

TRUSTED_DOMAINS = (
    "nih.gov",
    "ncbi.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov",
    "jissn.biomedcentral.com",
    "frontiersin.org",
    "nature.com",
    "bmj.com",
    "cochranelibrary.com",
    "sportsmedicine-open.springeropen.com",
)
SOURCE_ALIASES = {
    "creatine": ("creatine",),
    "ashwagandha": ("ashwagandha",),
    "bcaa": ("bcaa", "bcaas", "branched-chain amino", "branched chain amino"),
    "beta-alanine": ("beta-alanine", "beta alanine"),
    "caffeine": ("caffeine",),
    "tongkat-ali": ("tongkat", "eurycoma", "longifolia"),
}


def _quality_score(url: str, source_type: str) -> float:
    score = 0.45
    lowered = url.lower()
    if any(domain in lowered for domain in TRUSTED_DOMAINS):
        score += 0.35
    if source_type in {"pubmed", "review", "meta_analysis"}:
        score += 0.15
    if any(term in lowered for term in ("shop", "affiliate", "coupon", "blog")):
        score -= 0.2
    return max(0.0, min(1.0, round(score, 2)))


def _dedupe(sources: List[SourceCandidate]) -> List[SourceCandidate]:
    seen = set()
    unique: List[SourceCandidate] = []
    for source in sources:
        key = source.url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return sorted(unique, key=lambda s: s.quality_score, reverse=True)


def _doc_matches_claim(doc: dict, claim: str) -> bool:
    supplement = str(doc.get("supplement") or "").lower()
    aliases = SOURCE_ALIASES.get(supplement, (supplement,))
    lowered = claim.lower()
    return any(alias and alias in lowered for alias in aliases)


async def search_sources(claim: str, *, limit: int = 5) -> List[SourceCandidate]:
    sources: List[SourceCandidate] = []
    sources.extend(_search_curated_corpus(claim, limit=limit))
    if config.TAVILY_API_KEY:
        sources.extend(await _search_tavily(claim, limit=limit))
    sources.extend(await _search_pubmed(claim, limit=limit))
    return _dedupe(sources)[:limit]


def _search_curated_corpus(claim: str, *, limit: int) -> List[SourceCandidate]:
    results: List[SourceCandidate] = []
    for doc in retriever.retrieve(claim, k=limit):
        if not _doc_matches_claim(doc, claim):
            continue
        url = str(doc.get("source_url") or "")
        if not url:
            continue
        source_type = str(doc.get("study_type") or "review")
        year = doc.get("year")
        results.append(
            SourceCandidate(
                title=str(doc.get("source_title") or "Curated source"),
                url=url,
                snippet=str(doc.get("full_text") or doc.get("notes") or "")[:900],
                source_type=source_type,
                year=int(year) if isinstance(year, int) else None,
                provider="curated_corpus",
                quality_score=max(_quality_score(url, source_type), 0.92),
            )
        )
    return results


async def _search_tavily(claim: str, *, limit: int) -> List[SourceCandidate]:
    query = f"fitness science evidence {claim} randomized trial review PubMed"
    payload = {
        "api_key": config.TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": limit,
        "include_answer": False,
    }
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post("https://api.tavily.com/search", json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception:
        return []

    results = []
    for item in data.get("results", []):
        url = str(item.get("url", ""))
        title = str(item.get("title", "Untitled source"))
        snippet = str(item.get("content", ""))[:800]
        if not url:
            continue
        results.append(
            SourceCandidate(
                title=title,
                url=url,
                snippet=snippet,
                source_type="web",
                provider="tavily",
                quality_score=_quality_score(url, "web"),
            )
        )
    return results


def _fitness_query(claim: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\s\-]", " ", claim)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return f"({cleaned}) AND (exercise OR resistance training OR supplement OR nutrition OR muscle OR performance)"


async def _search_pubmed(claim: str, *, limit: int) -> List[SourceCandidate]:
    query = quote_plus(_fitness_query(claim))
    search_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&retmode=json&retmax={limit}&sort=relevance&term={query}"
    )
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            search_response = await client.get(search_url)
            search_response.raise_for_status()
            ids = search_response.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []
            fetch_url = (
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                f"?db=pubmed&retmode=xml&id={','.join(ids)}"
            )
            fetch_response = await client.get(fetch_url)
            fetch_response.raise_for_status()
    except Exception:
        return []

    candidates = _parse_pubmed_xml(fetch_response.text)
    relevant = [source for source in candidates if _source_mentions_claim_context(source, claim)]
    return relevant or candidates[:1]


def _source_mentions_claim_context(source: SourceCandidate, claim: str) -> bool:
    claim_text = claim.lower()
    source_text = f"{source.title} {source.snippet}".lower()
    if "hair" in claim_text:
        return any(term in source_text for term in ("hair", "dht", "androgen", "alopecia"))
    if any(term in claim_text for term in ("testosterone", "hormone")):
        return any(term in source_text for term in ("testosterone", "hormone", "androgen", "hypogonad"))
    if any(term in claim_text for term in ("muscle", "hypertrophy", "protein synthesis")):
        return "muscle" in source_text and any(term in source_text for term in ("protein", "synthesis", "hypertrophy"))
    if any(term in claim_text for term in ("fat loss", "weight loss")):
        return any(term in source_text for term in ("fat", "weight", "adipose", "body composition"))
    return True


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _parse_pubmed_xml(xml_text: str) -> List[SourceCandidate]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    results: List[SourceCandidate] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = _text(article.find(".//PMID"))
        title = _text(article.find(".//ArticleTitle")) or "PubMed source"
        abstract = _text(article.find(".//Abstract"))
        year_text = _text(article.find(".//PubDate/Year"))
        year = int(year_text) if year_text.isdigit() else None
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "https://pubmed.ncbi.nlm.nih.gov/"
        if not pmid:
            continue
        results.append(
            SourceCandidate(
                title=title,
                url=url,
                snippet=abstract[:900],
                source_type="pubmed",
                year=year,
                provider="pubmed",
                quality_score=_quality_score(url, "pubmed"),
            )
        )
    return results
