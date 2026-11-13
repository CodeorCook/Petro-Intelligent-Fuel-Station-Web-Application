"""Official fuel-price providers used by the reference-price workflow.

Petrolimex Region 2 is primary. The legacy PVOIL crawler remains a secondary
provider, while database fallback is handled by ``fuel_pricing_service``.
"""

import asyncio
import base64
import json
import logging
import re
import time
import unicodedata
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import (
    ConnectionError as CurlConnectionError,
    DNSError,
    RequestException,
    Timeout,
)

logger = logging.getLogger(__name__)

PVOIL_PRICE_URL = "https://www.pvoil.com.vn/tin-gia-xang-dau"
PVOIL_OFFICIAL_SOURCE_URLS = (
    PVOIL_PRICE_URL,
    "https://www.pvoil.com.vn/",
    "https://www.pvoil.com.vn/tin-tuc",
)
PETROLIMEX_PRICE_URL = "https://www.petrolimex.com.vn/nd/gia-ban-le-xang-dau.html"
PETROLIMEX_PRICE_API_URL = (
    "https://portals.petrolimex.com.vn/~apis/portals/cms.item/search"
)
CRAWL_CACHE_TTL_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 10.0
CURL_IMPERSONATE_TARGET = "chrome"
PETROLIMEX_PUBLIC_HOSTS = frozenset({"www.petrolimex.com.vn", "w.petrolimex.com.vn"})


class FuelCrawlerError(Exception):
    """Base class for controlled crawler failures."""


class FuelCrawlerNetworkError(FuelCrawlerError):
    """PVOIL could not be reached or returned an HTTP error."""


class FuelCrawlerParseError(FuelCrawlerError):
    """PVOIL HTML did not contain a usable supported-fuel price table."""


@dataclass(frozen=True, slots=True)
class CrawledFuelPrice:
    fuel_id: str
    source_name: str
    price: Decimal
    change_amount: Decimal | None
    effective_date: date
    effective_time: str | None


@dataclass(frozen=True, slots=True)
class FuelPriceProviderResult:
    provider_name: str
    prices: list[CrawledFuelPrice]
    source_url: str | None = None
    fetched_at: datetime | None = None
    is_cached: bool = False
    attempts: tuple[dict, ...] = ()


class FuelPriceProvider(ABC):
    """Replaceable transport/parser boundary for an official price source."""

    name: str

    @abstractmethod
    async def fetch_prices(self, session: AsyncSession) -> list[CrawledFuelPrice]:
        raise NotImplementedError


def normalize_fuel_name(name: str) -> str:
    value = unicodedata.normalize("NFKC", name).casefold()
    value = value.replace("\u00a0", " ").replace(",", ".")
    value = re.sub(r"[‐‑‒–—−]", "-", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\s*-\s*", "-", value)
    value = re.sub(r"ron\s*(\d+)", r"ron \1", value)
    return value


_FUEL_ALIASES = {
    "NL000001": (
        "Xăng E10 RON 95-III", "E10 RON 95-III", "E10 RON95-III",
    ),
    "NL000002": (
        "Xăng E5 RON 92-II", "E5 RON 92-II", "E5 RON92-II",
    ),
    "NL000003": (
        "Dầu DO 0,05S-II", "Dầu DO 0.05S-II", "DO 0,05S-II", "DO 0.05S-II",
    ),
}
FUEL_NAME_TO_ID = {
    normalize_fuel_name(alias): fuel_id
    for fuel_id, aliases in _FUEL_ALIASES.items()
    for alias in aliases
}


def map_pvoil_fuel_name(name: str) -> str | None:
    """Map only an exact, explicitly supported PVOIL alias."""
    return FUEL_NAME_TO_ID.get(normalize_fuel_name(name))


_PETROLIMEX_FUEL_ALIASES = {
    "NL000001": (
        "Xăng E10 RON 95-III",
        "Xăng E10 RON95-III",
        "Xăng E10 RON 95 Mức 3",
    ),
    "NL000002": ("Xăng E5 RON 92-II", "Xăng E5 RON 92 Mức 2"),
    "NL000003": ("Đi-ê-zen 0,05S-II", "DO 0,05S-II", "DO 0,05S Mức 2"),
}
PETROLIMEX_FUEL_NAME_TO_ID = {
    normalize_fuel_name(alias): fuel_id
    for fuel_id, aliases in _PETROLIMEX_FUEL_ALIASES.items()
    for alias in aliases
}


def map_petrolimex_fuel_name(name: str) -> str | None:
    """Strictly map only explicit Petrolimex product titles."""
    return PETROLIMEX_FUEL_NAME_TO_ID.get(normalize_fuel_name(name))


def _map_petrolimex_api_product(item: dict) -> str | None:
    fuel_id = map_petrolimex_fuel_name(str(item.get("Title") or ""))
    expected_aliases = {"NL000001": "e10-ron-95-iii", "NL000002": "e5-ron-92-ii", "NL000003": "do-005s-ii"}
    if fuel_id and item.get("Alias") and item["Alias"] != expected_aliases[fuel_id]:
        raise FuelCrawlerParseError("Contradictory Petrolimex product title/grade alias")
    # Observed 15/10 public widget title omits E5's grade. Only its explicit,
    # exact official Alias corroborates grade II; do not broaden HTML aliases.
    if (fuel_id is None and normalize_fuel_name(str(item.get("Title") or "")) == normalize_fuel_name("Xăng E5 RON 92")
            and item.get("Alias") == "e5-ron-92-ii"
            and normalize_fuel_name(str(item.get("EnglishTitle") or "")) == normalize_fuel_name("E5 RON 92")):
        return "NL000002"
    return fuel_id


def parse_vnd_price(text: str) -> Decimal:
    cleaned = unicodedata.normalize("NFKC", text).strip().lower()
    cleaned = cleaned.replace("vnđ", "").replace("vnd", "").replace("đ", "")
    match = re.search(r"([+-]?)\s*(\d[\d\s.,]*)", cleaned)
    if not match:
        raise ValueError(f"Invalid VND amount: {text!r}")
    sign, digits = match.groups()
    digits = re.sub(r"[\s.,]", "", digits)
    try:
        return Decimal(f"{sign}{digits}")
    except InvalidOperation as error:
        raise ValueError(f"Invalid VND amount: {text!r}") from error


def parse_petrolimex_html(html: str) -> list[CrawledFuelPrice]:
    """Parse a Petrolimex table and require an explicit Region 2 column."""
    soup = BeautifulSoup(html, "html.parser")
    selected_table: Tag | None = None
    header_row: Tag | None = None
    product_index: int | None = None
    region_2_index: int | None = None
    region_2_pattern = re.compile(r"\bvung\s*(?:2|ii)\b", re.IGNORECASE)

    for table in soup.find_all("table"):
        grid, occupied = [], {}
        for y, tr in enumerate(table.find_all('tr')):
            x=0
            for cell in tr.find_all(['th','td'],recursive=False):
                while (y,x) in occupied:x+=1
                for dy in range(int(cell.get('rowspan',1))):
                    for dx in range(int(cell.get('colspan',1))):occupied[y+dy,x+dx]=cell.get_text(' ',strip=True)
                x+=int(cell.get('colspan',1))
            grid.append(y)
        if not occupied:continue
        width=max(x for y,x in occupied)+1
        table.clear()
        for y in grid:
            tr=soup.new_tag('tr')
            for x in range(width):
                td=soup.new_tag('td');td.string=occupied.get((y,x),'');tr.append(td)
            table.append(tr)
        # Propagate product header across multi-row column headings.
        product_header=None
        for tr in table.find_all('tr'):
            cells=tr.find_all('td');texts=[_plain_text(v.get_text()) for v in cells]
            for x,t in enumerate(texts):
                if 'mat hang' in t or 'san pham' in t:product_header=x
            if product_header is not None and any(re.search(r'vung\s*(2|ii)\b',t) for t in texts):
                cells[product_header].string='Mặt hàng'
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            headers = [_plain_text(cell.get_text(" ", strip=True)) for cell in cells]
            current_product = next(
                (
                    index
                    for index, value in enumerate(headers)
                    if "san pham" in value or "mat hang" in value
                ),
                None,
            )
            current_region_2 = next(
                (
                    index
                    for index, value in enumerate(headers)
                    if region_2_pattern.search(value)
                ),
                None,
            )
            if current_product is not None and current_region_2 is not None:
                selected_table = table
                header_row = row
                product_index = current_product
                region_2_index = current_region_2
                break
        if selected_table is not None:
            break

    if (
        selected_table is None
        or header_row is None
        or product_index is None
        or region_2_index is None
    ):
        raise FuelCrawlerParseError(
            "Petrolimex Region 2 column was not found; Region 1 must not be used"
        )

    effective_date, effective_time = _parse_petrolimex_effective_datetime(soup)
    rows = selected_table.find_all("tr")
    prices: list[CrawledFuelPrice] = []
    for row in rows[rows.index(header_row) + 1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) <= max(product_index, region_2_index):
            continue
        source_name = cells[product_index].get_text(" ", strip=True)
        if not source_name:
            continue
        fuel_id = map_petrolimex_fuel_name(source_name)
        if fuel_id is None:
            logger.warning("Unsupported Petrolimex fuel ignored: %s", source_name)
            continue
        try:
            price = parse_vnd_price(
                cells[region_2_index].get_text(" ", strip=True)
            )
        except ValueError as error:
            raise FuelCrawlerParseError(
                f"Invalid Petrolimex Region 2 price for {source_name!r}"
            ) from error
        prices.append(
            CrawledFuelPrice(
                fuel_id=fuel_id,
                source_name=source_name,
                price=price,
                change_amount=None,
                effective_date=effective_date,
                effective_time=effective_time,
            )
        )
    _require_all_supported_petrolimex_fuels(prices)
    return prices


def parse_petrolimex_api_payload(
    payload: dict, *, effective_period: tuple[date, str | None] | None = None,
) -> list[CrawledFuelPrice]:
    """Parse the public JSON payload used by Petrolimex's own price widget."""
    if not isinstance(payload, dict):
        raise FuelCrawlerParseError("Petrolimex price API root must be an object")
    objects = payload.get("Objects")
    if not isinstance(objects, list) or not objects:
        raise FuelCrawlerParseError("Petrolimex price API returned no products")

    if effective_period is None:
        raise FuelCrawlerParseError("Petrolimex requires a verified announcement effective period; LastModified is CMS metadata")
    period_date, period_time = effective_period
    prices: list[CrawledFuelPrice] = []
    for item in objects:
        if not isinstance(item, dict):
            raise FuelCrawlerParseError("Invalid Petrolimex product record")
        source_name = str(item.get("Title") or "").strip()
        fuel_id = _map_petrolimex_api_product(item)
        if fuel_id is None:
            if source_name:
                logger.warning("Unsupported Petrolimex fuel ignored: %s", source_name)
            continue
        # Only matched products participate. Never assign an unrelated item's
        # maximum CMS timestamp to this global response. CMS date corroborates
        # the announcement date, but its time is NOT the effective time.
        try:
            modified = _parse_petrolimex_timestamp(str(item.get("LastModified")))
            if modified.tzinfo is None:
                raise ValueError("CMS timestamp has no timezone")
        except ValueError as error:
            raise FuelCrawlerParseError("Matched Petrolimex product lacks a valid CMS timestamp") from error
        # Per-product CMS metadata may stay old when the published price is unchanged.
        if item.get("Status") not in (None, "Published"):
            raise FuelCrawlerParseError("Unpublished product in current widget")
        if "Zone2Price" not in item or "Zone1Price" not in item:
            raise FuelCrawlerParseError(
                f"Petrolimex Region 2 is not explicit for {source_name!r}"
            )
        try:
            region_2_price = Decimal(str(item["Zone2Price"]))
        except (InvalidOperation, TypeError) as error:
            raise FuelCrawlerParseError(
                f"Invalid Petrolimex Region 2 price for {source_name!r}"
            ) from error
        if not region_2_price.is_finite() or region_2_price <= 0:
            raise FuelCrawlerParseError("Petrolimex Region 2 price must be finite and positive")
        if any(p.fuel_id == fuel_id for p in prices):
            raise FuelCrawlerParseError("Duplicate canonical Petrolimex product")
        prices.append(
            CrawledFuelPrice(
                fuel_id=fuel_id,
                source_name=source_name,
                price=region_2_price,
                change_amount=None,
                effective_date=period_date,
                effective_time=period_time,
            )
        )

    _require_all_supported_petrolimex_fuels(prices)
    return prices


def _parse_petrolimex_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_petrolimex_effective_datetime(
    soup: BeautifulSoup,
) -> tuple[date, str | None]:
    # Explicit effective text only, never publication time or LastModified.
    contexts = [node.get_text(" ", strip=True) for node in soup.select("h1, title")]
    article = soup.select_one(".entry-detail, article, .cms-detail-content, .detail-content")
    if article is not None:
        for node in article.find_all(["p", "li"]):
            value = _plain_text(node.get_text(" ", strip=True))
            if ("petrolimex" in value and re.search(r"gia (?:ban le|xang dau)", value)
                    and re.search(r"\btu\s+\d", value)):
                contexts.append(value)
    pattern = re.compile(
        r"(?:tu\s*)?(?P<hour>\d{1,2})\s*(?:h|gio|:)\s*"
        r"(?P<minute>\d{2})(?:\s*phut)?\s*ngay\s*"
        r"(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>\d{4})",
        flags=re.IGNORECASE,
    )
    periods = set()
    for context in contexts:
        for match in pattern.finditer(_plain_text(context)):
            try:
                effective_date = date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
                hour, minute = int(match.group("hour")), int(match.group("minute"))
                datetime(2000, 1, 1, hour, minute)
            except ValueError as error:
                raise FuelCrawlerParseError("Petrolimex effective date is invalid") from error
            periods.add((effective_date, f"{hour:02d}:{minute:02d}"))
    if not periods:
        raise FuelCrawlerParseError("Petrolimex effective date was not found")
    if len(periods) != 1:
        raise FuelCrawlerParseError("Ambiguous Petrolimex effective periods in announcement")
    return periods.pop()


def find_petrolimex_announcements(html: str) -> list[str]:
    """Only public press-release links advertised on Petrolimex itself."""
    urls = []
    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        title = _plain_text(anchor.get_text(" ", strip=True))
        if "petrolimex" not in title or not re.search(r"(?:dieu chinh|giam|tang|cong bo|cap nhat).{0,100}gia xang dau", title):
            continue
        url = urljoin(PETROLIMEX_PRICE_URL, anchor["href"])
        parsed = urlparse(url)
        if (parsed.scheme == "https" and parsed.netloc in PETROLIMEX_PUBLIC_HOSTS
                and parsed.path.startswith("/ndi/thong-cao-bao-chi/") and not parsed.query and not parsed.fragment):
            if url not in urls:
                urls.append(url)
    return urls


def _require_all_supported_petrolimex_fuels(
    prices: list[CrawledFuelPrice],
) -> None:
    found = {item.fuel_id for item in prices}
    required = {"NL000001", "NL000002", "NL000003"}
    missing = sorted(required - found)
    if missing:
        for fuel_id in missing:
            logger.warning("Supported local fuel %s (%s) not present in Petrolimex feed",
                           fuel_id, _PETROLIMEX_FUEL_ALIASES[fuel_id][0])
        if "NL000001" in missing:
            logger.warning(
                "Supported local fuel NL000001 not present in Petrolimex feed"
            )
        raise FuelCrawlerParseError(
            f"Petrolimex Region 2 prices are incomplete; missing {missing}"
        )


def parse_pvoil_html(html: str) -> list[CrawledFuelPrice]:
    soup = BeautifulSoup(html, "html.parser")
    try:
        table = _find_price_table(soup)
    except FuelCrawlerParseError:
        return _parse_official_price_block(soup)
    effective_date, effective_time = _parse_effective_datetime(soup, table)
    header_row, indexes = _find_header_row(table)
    prices: list[CrawledFuelPrice] = []
    rows = table.find_all("tr")
    start_index = rows.index(header_row) + 1
    for row in rows[start_index:]:
        cells = row.find_all(["td", "th"])
        if len(cells) <= max(indexes.values()):
            continue
        source_name = cells[indexes["product"]].get_text(" ", strip=True)
        if not source_name:
            continue
        fuel_id = map_pvoil_fuel_name(source_name)
        if fuel_id is None:
            logger.warning("Unsupported PVOIL fuel ignored: %s", source_name)
            continue
        try:
            price = parse_vnd_price(cells[indexes["price"]].get_text(" ", strip=True))
            change = parse_vnd_price(cells[indexes["change"]].get_text(" ", strip=True))
        except ValueError as error:
            raise FuelCrawlerParseError(
                f"Invalid price values for supported fuel {source_name!r}"
            ) from error
        prices.append(
            CrawledFuelPrice(
                fuel_id=fuel_id,
                source_name=source_name,
                price=price,
                change_amount=change,
                effective_date=effective_date,
                effective_time=effective_time,
            )
        )
    if not prices:
        raise FuelCrawlerParseError("No supported PVOIL fuel prices were found")
    return prices


def _parse_official_price_block(soup: BeautifulSoup) -> list[CrawledFuelPrice]:
    """Parse PVOIL's homepage/news price cards where published change is absent."""
    effective_date, effective_time = _parse_effective_datetime(soup)
    fragments = [value.strip() for value in soup.stripped_strings if value.strip()]
    prices: list[CrawledFuelPrice] = []
    found_fuels: set[str] = set()
    for index, fragment in enumerate(fragments):
        fuel_id = map_pvoil_fuel_name(fragment)
        source_name = fragment
        if fuel_id is None:
            normalized_fragment = normalize_fuel_name(fragment)
            matches = [
                (alias, mapped_id)
                for alias, mapped_id in FUEL_NAME_TO_ID.items()
                if normalized_fragment.startswith(f"{alias} ")
            ]
            if len(matches) == 1:
                _, fuel_id = matches[0]
        if fuel_id is None or fuel_id in found_fuels:
            normalized = normalize_fuel_name(fragment)
            if fuel_id is None and ("ron" in normalized or "dau do" in normalized):
                logger.warning("Unsupported PVOIL fuel ignored: %s", fragment)
            continue
        price: Decimal | None = None
        for candidate in fragments[index:index + 5]:
            if not re.search(r"\d{1,3}(?:[.\s]\d{3})+(?:\s*(?:đ|vnd|vnđ))?", candidate, re.I):
                continue
            try:
                price = parse_vnd_price(candidate)
                break
            except ValueError:
                continue
        if price is None:
            logger.warning("PVOIL fuel mapping succeeded but price was not found: %s", source_name)
            continue
        found_fuels.add(fuel_id)
        prices.append(CrawledFuelPrice(
            fuel_id=fuel_id,
            source_name=source_name,
            price=price,
            change_amount=None,
            effective_date=effective_date,
            effective_time=effective_time,
        ))
    if not prices:
        raise FuelCrawlerParseError("Official PVOIL price block was not found")
    return prices


def _plain_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.replace("đ", "d")
    return re.sub(r"\s+", " ", normalized).strip()


def _has_required_headers(table: Tag) -> bool:
    text = _plain_text(table.get_text(" ", strip=True))
    return all(fragment in text for fragment in ("mat hang", "gia dieu chinh", "chenh lech"))


def _find_price_table(soup: BeautifulSoup) -> Tag:
    selected = soup.select_one("#table")
    if selected is not None:
        candidate = selected if selected.name == "table" else selected.find("table")
        if isinstance(candidate, Tag) and _has_required_headers(candidate):
            return candidate
    for table in soup.find_all("table"):
        if _has_required_headers(table):
            return table
    raise FuelCrawlerParseError("PVOIL price table was not found")


def _find_header_row(table: Tag) -> tuple[Tag, dict[str, int]]:
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        headers = [_plain_text(cell.get_text(" ", strip=True)) for cell in cells]
        indexes: dict[str, int] = {}
        for index, header in enumerate(headers):
            if "mat hang" in header:
                indexes["product"] = index
            elif "gia dieu chinh" in header:
                indexes["price"] = index
            elif "chenh lech" in header:
                indexes["change"] = index
        if set(indexes) == {"product", "price", "change"}:
            return row, indexes
    raise FuelCrawlerParseError("PVOIL table headers are not usable")


def _parse_effective_datetime(
    soup: BeautifulSoup, table: Tag | None = None
) -> tuple[date, str | None]:
    context = ((table.get_text(" ", strip=True) + " ") if table is not None else "") + soup.get_text(" ", strip=True)
    match = re.search(
        r"(?:(?:lúc|từ)\s*(?P<time>\d{1,2}:\d{2})\s*)?ngày\s*"
        r"(?P<date>\d{1,2}/\d{1,2}/\d{4})",
        context,
        flags=re.IGNORECASE,
    )
    if not match:
        raise FuelCrawlerParseError("PVOIL effective date was not found")
    try:
        effective_date = datetime.strptime(match.group("date"), "%d/%m/%Y").date()
    except ValueError as error:
        raise FuelCrawlerParseError("PVOIL effective date is invalid") from error
    return effective_date, match.group("time")


_cache_lock = asyncio.Lock()
_cached_prices: tuple[CrawledFuelPrice, ...] | None = None
_cached_at: float | None = None
_cached_pvoil_source_url: str | None = None


def _looks_like_challenge_page(html: str) -> bool:
    """Detect obvious Cloudflare/access-denied pages before parsing prices."""
    normalized = html.casefold()
    markers = (
        "cf-chl-",
        "/cdn-cgi/challenge-platform/",
        "cf-browser-verification",
        "challenge-running",
        "just a moment...",
        "attention required! | cloudflare",
        "cloudflare ray id",
        "verify you are human",
        "<title>access denied</title>",
    )
    return any(marker in normalized for marker in markers)


async def _fetch_official_text(
    session: AsyncSession,
    url: str,
    *,
    provider_name: str,
    expected_content: str,
    referer: str,
) -> str:
    """Fetch official content and normalize curl errors into crawler errors."""
    logger.info(
        "%s request client=curl_cffi impersonate=%s url=%s",
        provider_name,
        CURL_IMPERSONATE_TARGET,
        url,
    )
    try:
        response = await session.get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=True,
            headers={"Referer": referer},
        )
    except Timeout as error:
        raise FuelCrawlerNetworkError(
            f"{provider_name} timeout for {url}"
        ) from error
    except (DNSError, CurlConnectionError) as error:
        raise FuelCrawlerNetworkError(
            f"{provider_name} DNS/connect error for {url}: {type(error).__name__}"
        ) from error
    except RequestException as error:
        raise FuelCrawlerNetworkError(
            f"{provider_name} request error for {url}: {type(error).__name__}"
        ) from error

    status_code = response.status_code
    final_url = str(getattr(response, "url", url))
    content_type = response.headers.get("content-type", "")
    response_size = len(response.content)
    logger.info(
        "%s response client=curl_cffi impersonate=%s url=%s status=%s "
        "final_url=%s content_type=%s length=%d",
        provider_name,
        CURL_IMPERSONATE_TARGET,
        url,
        status_code,
        final_url,
        content_type,
        response_size,
    )
    if status_code >= 400:
        reason = "access limited" if status_code in (403, 429) else "HTTP error"
        raise FuelCrawlerNetworkError(
            f"{provider_name} {reason} {status_code} for {url}"
        )
    if provider_name == "Petrolimex":
        final = urlparse(final_url)
        if final.scheme != "https" or final.netloc not in PETROLIMEX_PUBLIC_HOSTS | {"portals.petrolimex.com.vn"}:
            raise FuelCrawlerParseError("Petrolimex redirected outside the approved official hosts")
    if expected_content not in content_type.casefold() and content_type:
        raise FuelCrawlerParseError(
            f"{provider_name} returned unexpected content for {url}: {content_type}"
        )
    text = response.text
    if _looks_like_challenge_page(text):
        raise FuelCrawlerNetworkError(
            f"{provider_name} challenge/access-denied page returned for {url}"
        )
    return text


async def fetch_pvoil_html(session: AsyncSession, url: str) -> str:
    """Fetch one official PVOIL page using browser-impersonating curl."""
    return await _fetch_official_text(
        session,
        url,
        provider_name="PVOIL",
        expected_content="html",
        referer="https://www.pvoil.com.vn/",
    )


async def fetch_petrolimex_text(
    session: AsyncSession,
    url: str,
    *,
    expected_content: str,
) -> str:
    return await _fetch_official_text(
        session,
        url,
        provider_name="Petrolimex",
        expected_content=expected_content,
        referer="https://www.petrolimex.com.vn/",
    )


async def crawl_pvoil_prices(
    *, session: AsyncSession | None = None, force_refresh: bool = False
) -> list[CrawledFuelPrice]:
    global _cached_prices, _cached_at
    async with _cache_lock:
        now = time.monotonic()
        if (
            not force_refresh
            and _cached_prices is not None
            and _cached_at is not None
            and now - _cached_at < CRAWL_CACHE_TTL_SECONDS
        ):
            return list(_cached_prices)
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Referer": "https://www.pvoil.com.vn/",
        }
        async def fetch_with(active_session: AsyncSession) -> list[CrawledFuelPrice]:
            global _cached_pvoil_source_url
            failures: list[FuelCrawlerError] = []
            for url in PVOIL_OFFICIAL_SOURCE_URLS:
                try:
                    html = await fetch_pvoil_html(active_session, url)
                except FuelCrawlerError as error:
                    logger.warning("%s", error)
                    failures.append(error)
                    continue
                try:
                    parsed = parse_pvoil_html(html)
                except FuelCrawlerParseError as error:
                    logger.warning("PVOIL parse failure for %s: %s", url, error)
                    failures.append(error)
                    continue
                logger.info("PVOIL official source selected: %s", url)
                _cached_pvoil_source_url = url
                return parsed
            if failures:
                raise failures[-1]
            raise FuelCrawlerNetworkError("No official PVOIL source was attempted")

        if session is None:
            async with AsyncSession(
                impersonate=CURL_IMPERSONATE_TARGET,
                headers=headers,
            ) as owned_session:
                prices = await fetch_with(owned_session)
        else:
            prices = await fetch_with(session)
        _cached_prices = tuple(prices)
        _cached_at = time.monotonic()
        logger.info("PVOIL crawl succeeded with %d supported prices", len(prices))
        return list(prices)


def _base64url(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _build_petrolimex_api_url() -> str:
    # These public identifiers and request shape are used by Petrolimex's own
    # plx.1.prices.min.js widget. No session token or private credential is used.
    request_payload = {
        "FilterBy": {
            "And": [
                {"SystemID": {"Equals": "6783dc1271ff449e95b74a9520964169"}},
                {"RepositoryID": {"Equals": "a95451e23b474fe5886bfb7cf843f53c"}},
                {"RepositoryEntityID": {"Equals": "3801378fe1e045b1afa10de7c5776124"}},
                {"Status": {"Equals": "Published"}},
            ]
        },
        "SortBy": {"LastModified": "Descending"},
        "Pagination": {
            "TotalRecords": -1,
            "TotalPages": 0,
            "PageSize": 0,
            "PageNumber": 0,
        },
    }
    compact_payload = json.dumps(
        request_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    query = urlencode(
        {
            "x-request": _base64url(compact_payload),
            "x-device-id": _base64url(f"{uuid.uuid4()}@portals"),
            "x-app-name": _base64url("NGX Websites"),
            "x-app-platform": _base64url("Desktop PWA"),
            "language": "vi-VN",
        }
    )
    return f"{PETROLIMEX_PRICE_API_URL}?{query}"


class PetrolimexFuelPriceProvider(FuelPriceProvider):
    name = "petrolimex"

    async def fetch_prices(self, session: AsyncSession) -> list[CrawledFuelPrice]:
        from app.services.petrolimex_snapshot import verified_snapshot
        prices, self.source_url = await verified_snapshot(session)
        return prices


class PVOILFuelPriceProvider(FuelPriceProvider):
    name = "pvoil"

    async def fetch_prices(self, session: AsyncSession) -> list[CrawledFuelPrice]:
        prices = await crawl_pvoil_prices(session=session, force_refresh=True)
        self.source_url = _cached_pvoil_source_url
        found = {item.fuel_id for item in prices}
        missing = sorted({"NL000001", "NL000002", "NL000003"} - found)
        if missing:
            raise FuelCrawlerParseError(
                f"PVOIL prices are incomplete for the global-source API; missing {missing}"
            )
        return prices


_reference_cache_lock = asyncio.Lock()
_cached_provider_result: FuelPriceProviderResult | None = None
_cached_provider_at: float | None = None
_last_provider_failure: FuelCrawlerError | None = None
_last_provider_failure_at: float | None = None


async def crawl_reference_prices(
    *, session: AsyncSession | None = None, force_refresh: bool = False
) -> FuelPriceProviderResult:
    """Try Petrolimex Region 2, then legacy PVOIL, then let service use DB."""
    global _cached_provider_result, _cached_provider_at, _last_provider_failure, _last_provider_failure_at
    requested_at = time.monotonic()
    async with _reference_cache_lock:
        now = time.monotonic()
        # Short failure cooldown prevents every page load retrying all sources.
        # This is a cached failure, never a successful/live price result.
        if _last_provider_failure is not None and _last_provider_failure_at is not None and now - _last_provider_failure_at < (30 if force_refresh else 60):
            raise _last_provider_failure
        if (
            _cached_provider_result is not None
            and _cached_provider_at is not None
            and (now - _cached_provider_at < (30 if force_refresh else CRAWL_CACHE_TTL_SECONDS)
                 or _cached_provider_at >= requested_at)
        ):
            return FuelPriceProviderResult(
                provider_name=_cached_provider_result.provider_name,
                prices=list(_cached_provider_result.prices),
                source_url=_cached_provider_result.source_url,
                fetched_at=_cached_provider_result.fetched_at,
                is_cached=True,
                attempts=_cached_provider_result.attempts,
            )

        providers: tuple[FuelPriceProvider, ...] = (
            PetrolimexFuelPriceProvider(),
        )
        attempts: list[dict] = []

        async def run(active_session: AsyncSession) -> FuelPriceProviderResult:
            failures: list[FuelCrawlerError] = []
            candidates: list[FuelPriceProviderResult] = []
            for provider in providers:
                try:
                    prices = await provider.fetch_prices(active_session)
                    if {p.fuel_id for p in prices} != {"NL000001", "NL000002", "NL000003"} or len(prices) != 3:
                        raise FuelCrawlerParseError("Provider global result requires exactly three canonical fuels")
                    if len({(p.effective_date, p.effective_time) for p in prices}) != 1:
                        raise FuelCrawlerParseError("Provider global result contains mixed effective periods")
                    # Do not let a future/erroneous period outrank verified data.
                    local_day = datetime.now(timezone(timedelta(hours=7))).date()
                    if prices[0].effective_date > local_day:
                        raise FuelCrawlerParseError("Provider effective period is in the future")
                except FuelCrawlerError as error:
                    logger.warning("Fuel provider %s failed: %s", provider.name, error)
                    failures.append(error)
                    attempts.append(dict(source=provider.name, status="error", detail=str(error).split('?')[0]))
                    continue
                attempts.append(dict(source=provider.name, status="verified", effective_date=prices[0].effective_date.isoformat(),
                                     source_url=getattr(provider, "source_url", None)))
                candidates.append(FuelPriceProviderResult(
                    provider.name, prices, getattr(provider, "source_url", None), datetime.now(timezone.utc)
                ))
                # Petrolimex has priority when fresh. Check PVOIL only if its
                # verified period is older than yesterday; on the same calendar
                # day official sources may have different retail pricing.
                if provider.name == "petrolimex" and (local_day - prices[0].effective_date).days <= 1:
                    break
            if candidates:
                # Tie: retain Petrolimex Vùng 2 over PVOIL. A newer PVOIL
                # period may be displayed with source attribution, never silently
                # persisted into Petrolimex station-specific history.
                selected = max(candidates, key=lambda c: (
                    c.prices[0].effective_date, 1 if c.provider_name == "petrolimex" else 0
                ))
                logger.info("Fuel provider selected: %s period=%s", selected.provider_name, selected.prices[0].effective_date)
                return FuelPriceProviderResult(selected.provider_name, selected.prices, selected.source_url,
                                               selected.fetched_at, attempts=tuple(attempts))
            if failures:
                error = FuelCrawlerError("; ".join(f"{a['source']}: {a['detail']}" for a in attempts))
                error.attempts = tuple(attempts)
                raise error
            raise FuelCrawlerError("No fuel-price provider was configured")

        try:
            if session is None:
                async with AsyncSession(
                    impersonate=CURL_IMPERSONATE_TARGET,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.7",
                        "Cache-Control": "no-cache",
                    },
                ) as owned_session:
                    result = await asyncio.wait_for(run(owned_session), timeout=40)
            else:
                result = await asyncio.wait_for(run(session), timeout=40)
        except asyncio.TimeoutError:
            error = FuelCrawlerNetworkError("Official source check exceeded 40 seconds")
            error.attempts = tuple(attempts) + (dict(source="official_sources", status="error", detail=str(error)),)
            _last_provider_failure, _last_provider_failure_at = error, time.monotonic()
            raise error from None
        except FuelCrawlerError as error:
            _last_provider_failure, _last_provider_failure_at = error, time.monotonic()
            raise

        _last_provider_failure, _last_provider_failure_at = None, None
        _cached_provider_result = result
        _cached_provider_at = time.monotonic()
        return FuelPriceProviderResult(result.provider_name, list(result.prices), result.source_url, result.fetched_at,
                                       attempts=result.attempts)


def clear_crawl_cache() -> None:
    """Clear the process-local cache; useful for deterministic tests."""
    global _cached_prices, _cached_at, _cached_provider_result, _cached_provider_at, _last_provider_failure, _last_provider_failure_at
    _cached_prices = None
    _cached_at = None
    _cached_provider_result = None
    _cached_provider_at = None
    _last_provider_failure = None
    _last_provider_failure_at = None
