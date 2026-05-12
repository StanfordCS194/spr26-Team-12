"""Source search for Feature 1 claim checking.

Tavily is used when configured for broad web search. PubMed is the no-key
fallback so the MVP still performs real source lookup for fitness science.

Quality scoring is purely string-based: we never fetch the URL during scoring,
which keeps the pipeline safe from SSRF and fast.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional
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
    "examine.com",
)
SOURCE_ALIASES = {
    "creatine": ("creatine",),
    "ashwagandha": ("ashwagandha",),
    "bcaa": ("bcaa", "bcaas", "branched-chain amino", "branched chain amino"),
    "beta-alanine": ("beta-alanine", "beta alanine"),
    "caffeine": ("caffeine",),
    "tongkat-ali": ("tongkat", "eurycoma", "longifolia"),
    "protein": ("protein", "whey", "casein", "amino acid"),
    "fasted_cardio": ("fasted cardio", "fasted training", "morning cardio"),
    "intermittent_fasting": ("intermittent fasting", "16:8", "time-restricted"),
    "sleep": ("sleep", "insomnia", "rest"),
    "doms": ("doms", "soreness", "muscle soreness"),
    "lactate": ("lactic acid", "lactate"),
    "hiit": ("hiit", "interval training", "sprint interval"),
    "training_frequency": ("training frequency", "workout frequency", "sessions per week"),
    "training_volume": ("training volume", "weekly sets", "hard sets"),
    "spot_reduction": ("spot reduction", "target fat", "belly fat"),
    "stretching": ("stretching", "static stretch", "dynamic warm-up"),
    "cardio_kills_gains": ("interference", "concurrent training", "cardio kills"),
    "squat": ("squat depth", "deep squat", "atg", "knees over toes"),
    "injury_prevention": ("injury prevention", "injury risk"),
    "preworkout": ("pre-workout", "preworkout"),
    "natural_limits": ("ffmi", "natural limit", "natty"),
    "alcohol": ("alcohol", "drinking", "beer"),
}

# Tiered study-type quality. Higher = stronger evidence type.
STUDY_TYPE_TIER = {
    "meta_analysis": 1.00,
    "systematic_review": 0.95,
    "position_stand": 0.90,
    "rct": 0.85,
    "review": 0.70,
    "observational": 0.55,
    "pubmed": 0.65,
    "web": 0.40,
    "blog": 0.20,
}
_CURRENT_YEAR = datetime.utcnow().year
_DEFAULT_TIER = 0.50


def _quality_score(url: str, source_type: str, year: Optional[int] = None) -> float:
    """Pure URL/metadata-based quality estimate in [0, 1].

    No network calls are made — `url` is treated as opaque display data and
    only its lowercased substrings are inspected. This keeps the scoring step
    safe from SSRF and side-effect free.
    """
    lowered = (url or "").lower()
    base = STUDY_TYPE_TIER.get((source_type or "").lower(), _DEFAULT_TIER)

    if any(domain in lowered for domain in TRUSTED_DOMAINS):
        base += 0.15
    if any(term in lowered for term in ("shop", "affiliate", "coupon", "/blog", ".blog")):
        base -= 0.25

    if isinstance(year, int) and 1900 < year <= _CURRENT_YEAR + 1:
        decades = max(0, (_CURRENT_YEAR - year) // 10)
        base -= 0.02 * decades  # gentle decay; meta-analyses still beat fresh blogs

    return max(0.0, min(1.0, round(base, 2)))


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
        parsed_year = int(year) if isinstance(year, int) else None
        results.append(
            SourceCandidate(
                title=str(doc.get("source_title") or "Curated source"),
                url=url,
                snippet=str(doc.get("full_text") or doc.get("notes") or "")[:900],
                source_type=source_type,
                year=parsed_year,
                provider="curated_corpus",
                quality_score=max(_quality_score(url, source_type, parsed_year), 0.92),
                effect_direction=(str(doc.get("effect_direction")) if doc.get("effect_direction") else None),
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
                quality_score=_quality_score(url, "web", None),
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
                quality_score=_quality_score(url, "pubmed", year),
            )
        )
    return results
