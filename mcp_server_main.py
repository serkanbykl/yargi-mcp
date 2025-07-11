# mcp_server_main.py
import asyncio
import atexit
import logging
import os
from pydantic import HttpUrl, Field 
from typing import Optional, Dict, List, Literal
import urllib.parse

# --- Logging Configuration Start ---
LOG_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
if not os.path.exists(LOG_DIRECTORY):
    os.makedirs(LOG_DIRECTORY)
LOG_FILE_PATH = os.path.join(LOG_DIRECTORY, "mcp_server.log")

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG) 

log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(threadName)s - %(message)s')

file_handler = logging.FileHandler(LOG_FILE_PATH, mode='a', encoding='utf-8')
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.DEBUG)
root_logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO) 
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)
# --- Logging Configuration End ---

from fastmcp import FastMCP

# --- Module Imports ---
from yargitay_mcp_module.client import YargitayOfficialApiClient
from yargitay_mcp_module.models import (
    YargitayDetailedSearchRequest, YargitayDocumentMarkdown, CompactYargitaySearchResult,
    YargitayBirimEnum
)
from bedesten_mcp_module.client import BedestenApiClient
from bedesten_mcp_module.models import (
    BedestenSearchRequest, BedestenSearchData,
    BedestenDocumentMarkdown, DanistayBirimEnum
)
from danistay_mcp_module.client import DanistayApiClient
from danistay_mcp_module.models import (
    DanistayKeywordSearchRequest, DanistayDetailedSearchRequest,
    DanistayDocumentMarkdown, CompactDanistaySearchResult
)
from emsal_mcp_module.client import EmsalApiClient
from emsal_mcp_module.models import (
    EmsalSearchRequest, EmsalDocumentMarkdown, CompactEmsalSearchResult
)
from uyusmazlik_mcp_module.client import UyusmazlikApiClient
from uyusmazlik_mcp_module.models import (
    UyusmazlikSearchRequest, UyusmazlikSearchResponse, UyusmazlikDocumentMarkdown,
    UyusmazlikBolumEnum, UyusmazlikTuruEnum, UyusmazlikKararSonucuEnum
)
from anayasa_mcp_module.client import AnayasaMahkemesiApiClient
from anayasa_mcp_module.bireysel_client import AnayasaBireyselBasvuruApiClient
from anayasa_mcp_module.models import (
    AnayasaNormDenetimiSearchRequest,
    AnayasaSearchResult,
    AnayasaDocumentMarkdown,
    AnayasaBireyselReportSearchRequest,
    AnayasaBireyselReportSearchResult,
    AnayasaBireyselBasvuruDocumentMarkdown,
    AnayasaDonemEnum, AnayasaBasvuruTuruEnum, AnayasaVarYokEnum,
    AnayasaNormTuruEnum, AnayasaIncelemeSonucuEnum, AnayasaSonucGerekcesiEnum
)
# KIK Module Imports
from kik_mcp_module.client import KikApiClient
from kik_mcp_module.models import ( 
    KikKararTipi, 
    KikSearchRequest,
    KikSearchResult,
    KikDocumentMarkdown 
)

from rekabet_mcp_module.client import RekabetKurumuApiClient
from rekabet_mcp_module.models import (
    RekabetKurumuSearchRequest,
    RekabetSearchResult,
    RekabetDocument,
    RekabetKararTuruGuidEnum
)


app = FastMCP(
    name="YargiMCP",
    instructions="MCP server for TR legal databases (Yargitay, Danistay, Emsal, Uyusmazlik, Anayasa-Norm, Anayasa-Bireysel, KIK).",
    dependencies=["httpx", "beautifulsoup4", "markitdown", "pydantic", "aiohttp", "playwright"]
)

# --- API Client Instances ---
yargitay_client_instance = YargitayOfficialApiClient()
danistay_client_instance = DanistayApiClient()
emsal_client_instance = EmsalApiClient()
uyusmazlik_client_instance = UyusmazlikApiClient()
anayasa_norm_client_instance = AnayasaMahkemesiApiClient()
anayasa_bireysel_client_instance = AnayasaBireyselBasvuruApiClient()
kik_client_instance = KikApiClient()
rekabet_client_instance = RekabetKurumuApiClient()
bedesten_client_instance = BedestenApiClient()


KARAR_TURU_ADI_TO_GUID_ENUM_MAP = {
    "": RekabetKararTuruGuidEnum.TUMU, 
    "Birleşme ve Devralma": RekabetKararTuruGuidEnum.BIRLESME_DEVRALMA,
    "Diğer": RekabetKararTuruGuidEnum.DIGER,
    "Menfi Tespit ve Muafiyet": RekabetKararTuruGuidEnum.MENFI_TESPIT_MUAFIYET,
    "Özelleştirme": RekabetKararTuruGuidEnum.OZELLESTIRME,
    "Rekabet İhlali": RekabetKararTuruGuidEnum.REKABET_IHLALI,
}

# --- MCP Tools for Yargitay ---
@app.tool(
    description="Search Court of Cassation (Yargıtay) decisions using the primary official API with advanced search operators, chamber filtering (52 options), and comprehensive criteria. This is Turkey's highest court for civil and criminal matters, providing supreme court precedents",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_yargitay_detailed(
    arananKelime: str = Field("", description="""Keyword to search for.
    Search operators:
    • Space between words = OR logic (arsa payı → "arsa" OR "payı")
    • "exact phrase" = Exact match ("arsa payı" → exact phrase)
    • word1+word2 = AND logic (arsa+payı → both words required)
    • word* = Wildcard (bozma* → bozma, bozması, bozmanın, etc.)
    • +"phrase1" +"phrase2" = Multiple required phrases
    • +"required" -"excluded" = Include and exclude
    Examples: arsa payı | "arsa payı" | +"arsa payı" +"bozma sebebi" | bozma*"""),
    birimYrgKurulDaire: YargitayBirimEnum = Field("", description="""
        Yargıtay chamber/board selection. Available options:
        • Empty string ('') for ALL chambers
        • Hukuk Genel Kurulu (Civil General Assembly)
        • 1. Hukuk Dairesi through 23. Hukuk Dairesi (Civil Chambers 1-23)
        • Hukuk Daireleri Başkanlar Kurulu (Civil Chambers Presidents Board)
        • Ceza Genel Kurulu (Criminal General Assembly)
        • 1. Ceza Dairesi through 23. Ceza Dairesi (Criminal Chambers 1-23)
        • Ceza Daireleri Başkanlar Kurulu (Criminal Chambers Presidents Board)
        • Büyük Genel Kurulu (Grand General Assembly)
        Total: 49 possible values
    """),
    birimYrgHukukDaire: str = Field("", description="Legacy field - use birimYrgKurulDaire instead"),
    birimYrgCezaDaire: str = Field("", description="Legacy field - use birimYrgKurulDaire instead"),
    esasYil: str = Field("", description="Case year for 'Esas No'."),
    esasIlkSiraNo: str = Field("", description="Starting sequence number for 'Esas No'."),
    esasSonSiraNo: str = Field("", description="Ending sequence number for 'Esas No'."),
    kararYil: str = Field("", description="Decision year for 'Karar No'."),
    kararIlkSiraNo: str = Field("", description="Starting sequence number for 'Karar No'."),
    kararSonSiraNo: str = Field("", description="Ending sequence number for 'Karar No'."),
    baslangicTarihi: str = Field("", description="Start date for decision search (DD.MM.YYYY)."),
    bitisTarihi: str = Field("", description="End date for decision search (DD.MM.YYYY)."),
    siralama: str = Field("3", description="Sorting criteria (1: Esas No, 2: Karar No, 3: Karar Tarihi)."),
    siralamaDirection: str = Field("desc", description="Sorting direction ('asc' or 'desc')."),
    pageSize: int = Field(10, ge=1, le=100, description="Number of results per page."),
    pageNumber: int = Field(1, ge=1, description="Page number to retrieve.")
) -> CompactYargitaySearchResult:
    """
    Searches Court of Cassation (Yargıtay) decisions using the primary official API.
    
    The Court of Cassation (Yargıtay) is Turkey's highest court for civil and criminal matters,
    equivalent to a Supreme Court. This tool provides access to the most comprehensive database
    of supreme court precedents with advanced search capabilities and filtering options.
    
    Key Features:
    • Advanced search operators (AND, OR, wildcards, exclusions)
    • Chamber filtering: 52 options (23 Civil (Hukuk) + 23 Criminal (Ceza) + General Assemblies (Genel Kurullar))
    • Date range filtering with DD.MM.YYYY format
    • Case number filtering (Case No (Esas No) and Decision No (Karar No))
    • Pagination support (1-100 results per page)
    • Multiple sorting options (by case number, decision number, date)
    
    SEARCH SYNTAX GUIDE:
    • Words with spaces: OR search ("property share" finds ANY of the words)
    • "Quotes": Exact phrase search ("property share" finds exact phrase)
    • Plus sign (+): AND search (property+share requires both words)
    • Asterisk (*): Wildcard (construct* matches variations)
    • Minus sign (-): Exclude terms (avoid unwanted results)
    
    Common Search Patterns:
    • Simple OR: property share (finds ~523K results)
    • Exact phrase: "property share" (finds ~22K results)
    • Multiple required: +"property share" +"annulment reason (bozma sebebi)" (finds ~234 results)
    • Wildcard expansion: construct* (matches construction, constructive, etc.)
    • Exclude unwanted: +"property share" -"construction contract"
    
    Use cases:
    • Research supreme court precedents and legal principles
    • Find decisions from specific chambers (Civil (Hukuk) vs Criminal (Ceza))
    • Search for interpretations of specific legal concepts
    • Analyze court reasoning on complex legal issues
    • Track legal developments over time periods
    
    Returns structured search results with decision metadata. Use get_yargitay_document_markdown()
    to retrieve full decision texts for detailed analysis.
    """
    
    search_query = YargitayDetailedSearchRequest(
        arananKelime=arananKelime,
        birimYrgKurulDaire=birimYrgKurulDaire,
        birimYrgHukukDaire=birimYrgHukukDaire,
        birimYrgCezaDaire=birimYrgCezaDaire,
        esasYil=esasYil,
        esasIlkSiraNo=esasIlkSiraNo,
        esasSonSiraNo=esasSonSiraNo,
        kararYil=kararYil,
        kararIlkSiraNo=kararIlkSiraNo,
        kararSonSiraNo=kararSonSiraNo,
        baslangicTarihi=baslangicTarihi,
        bitisTarihi=bitisTarihi,
        siralama=siralama,
        siralamaDirection=siralamaDirection,
        pageSize=pageSize,
        pageNumber=pageNumber
    )
    
    logger.info(f"Tool 'search_yargitay_detailed' called: {search_query.model_dump_json(exclude_none=True, indent=2)}")
    try:
        api_response = await yargitay_client_instance.search_detailed_decisions(search_query)
        if api_response.data:
            return CompactYargitaySearchResult(
                decisions=api_response.data.data,
                total_records=api_response.data.recordsTotal,
                requested_page=search_query.pageNumber,
                page_size=search_query.pageSize)
        logger.warning("API response for Yargitay search did not contain expected data structure.")
        return CompactYargitaySearchResult(decisions=[], total_records=0, requested_page=search_query.pageNumber, page_size=search_query.pageSize)
    except Exception as e:
        logger.exception(f"Error in tool 'search_yargitay_detailed'.")
        raise

@app.tool(
    description="Retrieve the full text of a specific Court of Cassation (Yargıtay) decision from the primary official API in Markdown format",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True
    }
)
async def get_yargitay_document_markdown(id: str) -> YargitayDocumentMarkdown:
    """
    Retrieves the full text of a specific Court of Cassation (Yargıtay) decision from the primary official API in Markdown format.
    
    This tool fetches complete supreme court decision documents and converts them to clean,
    readable Markdown format suitable for detailed legal analysis and processing.
    
    Input Requirements:
    • id: Decision ID from search_yargitay_detailed results
    • ID must be non-empty string from official Court of Cassation (Yargıtay) database
    
    Output Format:
    • Clean Markdown text with legal structure preserved
    • Organized sections: case info, facts, legal reasoning, conclusion
    • Proper formatting for citations and legal references
    • Removes technical artifacts from source HTML
    
    Supreme Court Decision Content:
    • Complete legal reasoning and precedent analysis
    • Detailed examination of lower court decisions
    • Citation of relevant laws, regulations, and prior cases
    • Final ruling (karar) with legal justification
    
    Use for:
    • Reading full supreme court decision texts
    • Legal research and precedent (emsal) analysis
    • Citation extraction and reference building
    • Understanding supreme court legal reasoning
    • Academic and professional legal research
    """
    logger.info(f"Tool 'get_yargitay_document_markdown' called for ID: {id}")
    if not id or not id.strip(): raise ValueError("Document ID must be a non-empty string.")
    try:
        return await yargitay_client_instance.get_decision_document_as_markdown(id)
    except Exception as e:
        logger.exception(f"Error in tool 'get_yargitay_document_markdown'.")
        raise

# --- MCP Tools for Danistay ---
@app.tool(
    description="Search Council of State (Danıştay) decisions using keyword-based logic with AND/OR/NOT operators for complex administrative law research",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_danistay_by_keyword(
    andKelimeler: List[str] = Field(default_factory=list, description="Keywords for AND logic, e.g., ['word1', 'word2']"),
    orKelimeler: List[str] = Field(default_factory=list, description="Keywords for OR logic."),
    notAndKelimeler: List[str] = Field(default_factory=list, description="Keywords for NOT AND logic."),
    notOrKelimeler: List[str] = Field(default_factory=list, description="Keywords for NOT OR logic."),
    pageNumber: int = Field(1, ge=1, description="Page number."),
    pageSize: int = Field(10, ge=1, le=100, description="Results per page.")
) -> CompactDanistaySearchResult:
    """
    Searches Council of State (Danıştay) decisions using keyword-based logic.
    
    The Council of State (Danıştay) is Turkey's highest administrative court, responsible for
    reviewing administrative actions and providing administrative law precedents. This tool
    provides flexible keyword-based searching with Boolean logic operators.
    
    Key Features:
    • Boolean logic operators: AND, OR, NOT combinations
    • Multiple keyword lists for complex search strategies
    • Pagination support (1-100 results per page)
    • Administrative law focus (permits, licenses, public administration)
    • Complement to search_danistay_detailed for comprehensive coverage
    
    Keyword Logic:
    • andKelimeler: ALL keywords must be present (AND logic)
    • orKelimeler: ANY keyword can be present (OR logic)
    • notAndKelimeler: EXCLUDE if ALL keywords present (NOT AND)
    • notOrKelimeler: EXCLUDE if ANY keyword present (NOT OR)
    
    Administrative Law Use Cases:
    • Research administrative court precedents
    • Find decisions on specific government agencies
    • Search for rulings on permits (ruhsat) and licenses (izin)
    • Analyze administrative procedure interpretations
    • Study public administration legal principles
    
    Examples:
    • Simple AND: andKelimeler=["administrative act (idari işlem)", "annulment (iptal)"]
    • OR search: orKelimeler=["permit (ruhsat)", "permission (izin)", "license (lisans)"]
    • Complex: andKelimeler=["municipality (belediye)"], notOrKelimeler=["tax (vergi)"]
    
    Returns structured search results. Use get_danistay_document_markdown() for full texts.
    For comprehensive Council of State (Danıştay) research, also use search_danistay_detailed and search_danistay_bedesten.
    """
    
    search_query = DanistayKeywordSearchRequest(
        andKelimeler=andKelimeler,
        orKelimeler=orKelimeler,
        notAndKelimeler=notAndKelimeler,
        notOrKelimeler=notOrKelimeler,
        pageNumber=pageNumber,
        pageSize=pageSize
    )
    
    logger.info(f"Tool 'search_danistay_by_keyword' called.")
    try:
        api_response = await danistay_client_instance.search_keyword_decisions(search_query)
        if api_response.data:
            return CompactDanistaySearchResult(
                decisions=api_response.data.data,
                total_records=api_response.data.recordsTotal,
                requested_page=search_query.pageNumber,
                page_size=search_query.pageSize)
        logger.warning("API response for Danistay keyword search did not contain expected data structure.")
        return CompactDanistaySearchResult(decisions=[], total_records=0, requested_page=search_query.pageNumber, page_size=search_query.pageSize)
    except Exception as e:
        logger.exception(f"Error in tool 'search_danistay_by_keyword'.")
        raise

@app.tool(
    description="Search Council of State (Danıştay) decisions using detailed criteria including chamber (daire) selection, case numbers, dates, and legislation references for comprehensive administrative law research",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_danistay_detailed(
    daire: Optional[str] = Field(None, description="Chamber/Department name (e.g., '1. Daire')."),
    esasYil: Optional[str] = Field(None, description="Case year for 'Esas No'."),
    esasIlkSiraNo: Optional[str] = Field(None, description="Starting sequence for 'Esas No'."),
    esasSonSiraNo: Optional[str] = Field(None, description="Ending sequence for 'Esas No'."),
    kararYil: Optional[str] = Field(None, description="Decision year for 'Karar No'."),
    kararIlkSiraNo: Optional[str] = Field(None, description="Starting sequence for 'Karar No'."),
    kararSonSiraNo: Optional[str] = Field(None, description="Ending sequence for 'Karar No'."),
    baslangicTarihi: Optional[str] = Field(None, description="Start date for decision (DD.MM.YYYY)."),
    bitisTarihi: Optional[str] = Field(None, description="End date for decision (DD.MM.YYYY)."),
    mevzuatNumarasi: Optional[str] = Field(None, description="Legislation number."),
    mevzuatAdi: Optional[str] = Field(None, description="Legislation name."),
    madde: Optional[str] = Field(None, description="Article number."),
    siralama: str = Field("1", description="Sorting criteria (e.g., 1: Esas No, 3: Karar Tarihi)."),
    siralamaDirection: str = Field("desc", description="Sorting direction ('asc' or 'desc')."),
    pageNumber: int = Field(1, ge=1, description="Page number."),
    pageSize: int = Field(10, ge=1, le=100, description="Results per page.")
) -> CompactDanistaySearchResult:
    """
    Performs detailed search for Council of State (Danıştay) decisions with comprehensive filtering.
    
    The Council of State (Danıştay) is Turkey's highest administrative court, providing final
    rulings on administrative law matters. This tool offers the most comprehensive search
    capabilities for administrative court decisions with detailed filtering options.
    
    Key Features:
    • Chamber/Department (Daire) filtering (specify exact chamber like '1st Chamber (1. Daire)')
    • Case number filtering (Case No (Esas No) and Decision No (Karar No) with ranges)
    • Date range filtering with DD.MM.YYYY format
    • Legislation-based search (law numbers, names, article numbers)
    • Multiple sorting options (case number, decision date)
    • Pagination support (1-100 results per page)
    
    Advanced Filtering Options:
    • Specific chamber targeting for specialized administrative areas
    • Sequential case number ranges for comprehensive coverage
    • Legislation cross-referencing for regulatory compliance research
    • Time-period analysis with precise date ranges
    
    Administrative Law Use Cases:
    • Research specific administrative chambers' decisions
    • Find rulings on specific laws and regulations
    • Track administrative precedents over time periods
    • Analyze government agency-specific decisions
    • Study administrative procedure developments
    • Research permit, license, and regulatory decisions
    
    Chamber Examples:
    • '1st Chamber (1. Daire)' through '17th Chamber (17. Daire)' - Administrative chambers
    • 'Tax Cases Chambers Council (Vergi Dava Daireleri Kurulu)' - Tax cases
    • 'Administrative Cases Chambers Council (İdare Dava Daireleri Kurulu)' - Administrative cases
    
    Returns structured search results with comprehensive metadata.
    Use get_danistay_document_markdown() for full decision texts.
    For complete Council of State (Danıştay) coverage, also use search_danistay_by_keyword and search_danistay_bedesten.
    """
    
    search_query = DanistayDetailedSearchRequest(
        daire=daire,
        esasYil=esasYil,
        esasIlkSiraNo=esasIlkSiraNo,
        esasSonSiraNo=esasSonSiraNo,
        kararYil=kararYil,
        kararIlkSiraNo=kararIlkSiraNo,
        kararSonSiraNo=kararSonSiraNo,
        baslangicTarihi=baslangicTarihi,
        bitisTarihi=bitisTarihi,
        mevzuatNumarasi=mevzuatNumarasi,
        mevzuatAdi=mevzuatAdi,
        madde=madde,
        siralama=siralama,
        siralamaDirection=siralamaDirection,
        pageNumber=pageNumber,
        pageSize=pageSize
    )
    
    logger.info(f"Tool 'search_danistay_detailed' called.")
    try:
        api_response = await danistay_client_instance.search_detailed_decisions(search_query)
        if api_response.data:
            return CompactDanistaySearchResult(
                decisions=api_response.data.data,
                total_records=api_response.data.recordsTotal,
                requested_page=search_query.pageNumber,
                page_size=search_query.pageSize)
        logger.warning("API response for Danistay detailed search did not contain expected data structure.")
        return CompactDanistaySearchResult(decisions=[], total_records=0, requested_page=search_query.pageNumber, page_size=search_query.pageSize)
    except Exception as e:
        logger.exception(f"Error in tool 'search_danistay_detailed'.")
        raise

@app.tool(
    description="Retrieve the full text of a specific Council of State (Danıştay) decision from the primary official API in Markdown format",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True
    }
)
async def get_danistay_document_markdown(id: str) -> DanistayDocumentMarkdown:
    """
    Retrieves the full text of a specific Council of State (Danıştay) decision from the primary official API in Markdown format.
    
    This tool fetches complete administrative court decision documents and converts them to clean,
    readable Markdown format suitable for detailed legal analysis and administrative law research.
    
    Input Requirements:
    • id: Decision ID from search_danistay_by_keyword or search_danistay_detailed results
    • ID must be non-empty string from official Council of State (Danıştay) database
    
    Output Format:
    • Clean Markdown text with administrative legal structure preserved
    • Organized sections: case info, administrative facts, legal analysis, ruling
    • Proper formatting for administrative law citations and references
    • Removes technical artifacts from source HTML
    
    Administrative Court Decision Content:
    • Complete administrative law reasoning and precedent analysis
    • Review of administrative actions (idari işlemler) and government decisions
    • Citation of relevant administrative laws and regulations
    • Final administrative ruling (karar) with legal justification
    • Analysis of public administration procedures
    
    Use for:
    • Reading full administrative court decision texts
    • Administrative law research and precedent (emsal) analysis
    • Government action review and compliance research
    • Understanding administrative law principles
    • Academic and professional administrative law study
    • Regulatory compliance and permit/license (ruhsat/izin) law analysis
    """
    logger.info(f"Tool 'get_danistay_document_markdown' called for ID: {id}")
    if not id or not id.strip(): raise ValueError("Document ID must be a non-empty string for Danıştay.")
    try:
        return await danistay_client_instance.get_decision_document_as_markdown(id)
    except Exception as e:
        logger.exception(f"Error in tool 'get_danistay_document_markdown'.")
        raise

# --- MCP Tools for Emsal ---
@app.tool(
    description="Search Precedent (Emsal) decisions using detailed criteria including court selection, case numbers, and date ranges for comprehensive precedent research across Turkish courts through UYAP system",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_emsal_detailed_decisions(
    keyword: Optional[str] = Field(None, description="Keyword to search."),
    selected_bam_civil_court: Optional[str] = Field(None, description="Selected BAM Civil Court."),
    selected_civil_court: Optional[str] = Field(None, description="Selected Civil Court."),
    selected_regional_civil_chambers: List[str] = Field(default_factory=list, description="Selected Regional Civil Chambers."),
    case_year_esas: Optional[str] = Field(None, description="Case year for 'Esas No'."),
    case_start_seq_esas: Optional[str] = Field(None, description="Starting sequence for 'Esas No'."),
    case_end_seq_esas: Optional[str] = Field(None, description="Ending sequence for 'Esas No'."),
    decision_year_karar: Optional[str] = Field(None, description="Decision year for 'Karar No'."),
    decision_start_seq_karar: Optional[str] = Field(None, description="Starting sequence for 'Karar No'."),
    decision_end_seq_karar: Optional[str] = Field(None, description="Ending sequence for 'Karar No'."),
    start_date: Optional[str] = Field(None, description="Start date for decision (DD.MM.YYYY)."),
    end_date: Optional[str] = Field(None, description="End date for decision (DD.MM.YYYY)."),
    sort_criteria: str = Field("1", description="Sorting criteria (e.g., 1: Esas No)."),
    sort_direction: str = Field("desc", description="Sorting direction ('asc' or 'desc')."),
    page_number: int = Field(1, ge=1, description="Page number."),
    page_size: int = Field(10, ge=1, le=100, description="Results per page.")
) -> CompactEmsalSearchResult:
    """
    Searches for Precedent (Emsal) decisions using detailed criteria.
    
    The Precedent (Emsal) database contains precedent decisions from various Turkish courts
    integrated through the UYAP (National Judiciary Informatics System). This tool provides
    access to a comprehensive collection of court decisions that serve as legal precedents.
    
    Key Features:
    • Multi-court coverage (BAM, Civil courts, Regional chambers)
    • Keyword-based search across decision texts
    • Court-specific filtering for targeted research
    • Case number filtering (Case No (Esas No) and Decision No (Karar No) with ranges)
    • Date range filtering with DD.MM.YYYY format
    • Multiple sorting options and pagination support
    
    Court Selection Options:
    • BAM Civil Courts: Higher regional civil courts
    • Civil Courts: Local and first-instance civil courts
    • Regional Civil Chambers: Specialized civil court departments
    
    Precedent Research Use Cases:
    • Find precedent (emsal) decisions across multiple court levels
    • Research court interpretations of specific legal concepts
    • Analyze consistent legal reasoning patterns
    • Study regional variations in legal decisions
    • Track precedent development over time
    • Compare decisions from different court types
    
    Search Strategy:
    • Use keywords for conceptual searches
    • Filter by specific courts for jurisdiction-focused research
    • Combine with date ranges for temporal analysis
    • Use case number ranges for comprehensive coverage
    
    Returns structured precedent data with court information and decision metadata.
    Use get_emsal_document_markdown() to retrieve full precedent decision texts.
    """
    
    search_query = EmsalSearchRequest(
        keyword=keyword,
        selected_bam_civil_court=selected_bam_civil_court,
        selected_civil_court=selected_civil_court,
        selected_regional_civil_chambers=selected_regional_civil_chambers,
        case_year_esas=case_year_esas,
        case_start_seq_esas=case_start_seq_esas,
        case_end_seq_esas=case_end_seq_esas,
        decision_year_karar=decision_year_karar,
        decision_start_seq_karar=decision_start_seq_karar,
        decision_end_seq_karar=decision_end_seq_karar,
        start_date=start_date,
        end_date=end_date,
        sort_criteria=sort_criteria,
        sort_direction=sort_direction,
        page_number=page_number,
        page_size=page_size
    )
    
    logger.info(f"Tool 'search_emsal_detailed_decisions' called.")
    try:
        api_response = await emsal_client_instance.search_detailed_decisions(search_query)
        if api_response.data:
            return CompactEmsalSearchResult(
                decisions=api_response.data.data,
                total_records=api_response.data.totalRecords if api_response.data.totalRecords is not None else 0,
                requested_page=search_query.page_number,
                page_size=search_query.page_size
            )
        logger.warning("API response for Emsal search did not contain expected data structure.")
        return CompactEmsalSearchResult(decisions=[], total_records=0, requested_page=search_query.page_number, page_size=search_query.page_size)
    except Exception as e:
        logger.exception(f"Error in tool 'search_emsal_detailed_decisions'.")
        raise

@app.tool(
    description="Retrieve the full text of a specific Precedent (Emsal) decision in Markdown format from UYAP system",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True
    }
)
async def get_emsal_document_markdown(id: str) -> EmsalDocumentMarkdown:
    """
    Retrieves the full text of a specific Emsal (UYAP Precedent) decision in Markdown format.
    
    This tool fetches complete precedent decision documents from the UYAP system and converts
    them to clean, readable Markdown format suitable for legal precedent analysis.
    
    Input Requirements:
    • id: Decision ID from search_emsal_detailed_decisions results
    • ID must be non-empty string from UYAP Emsal database
    
    Output Format:
    • Clean Markdown text with legal precedent structure preserved
    • Organized sections: court info, case facts, legal reasoning, conclusion
    • Proper formatting for legal citations and cross-references
    • Removes technical artifacts from source documents
    
    Precedent Decision Content:
    • Complete court reasoning and legal analysis
    • Detailed examination of legal principles applied
    • Citation of relevant laws, regulations, and prior precedents
    • Final ruling with precedent-setting reasoning
    • Court-specific interpretations and legal standards
    
    Use for:
    • Reading full precedent decision texts
    • Legal precedent research and analysis
    • Understanding court reasoning patterns
    • Citation building and legal reference development
    • Comparative legal analysis across court levels
    • Academic and professional legal research
    """
    logger.info(f"Tool 'get_emsal_document_markdown' called for ID: {id}")
    if not id or not id.strip(): raise ValueError("Document ID required for Emsal.")
    try:
        return await emsal_client_instance.get_decision_document_as_markdown(id)
    except Exception as e:
        logger.exception(f"Error in tool 'get_emsal_document_markdown'.")
        raise

# --- MCP Tools for Uyusmazlik ---
@app.tool(
    description="Search Court of Jurisdictional Disputes (Uyuşmazlık Mahkemesi) decisions with comprehensive filtering for dispute resolution between different court systems",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_uyusmazlik_decisions(
    icerik: str = Field("", description="Keyword or content for main text search."),
    bolum: Literal["", "Ceza Bölümü", "Genel Kurul Kararları", "Hukuk Bölümü"] = Field("", description="Select the department (Bölüm)."),
    uyusmazlik_turu: Literal["", "Görev Uyuşmazlığı", "Hüküm Uyuşmazlığı"] = Field("", description="Select the type of dispute."),
    karar_sonuclari: List[Literal["Hüküm Uyuşmazlığı Olmadığına Dair", "Hüküm Uyuşmazlığı Olduğuna Dair"]] = Field(default_factory=list, description="List of desired 'Karar Sonucu' types."),
    esas_yil: str = Field("", description="Case year ('Esas Yılı')."),
    esas_sayisi: str = Field("", description="Case number ('Esas Sayısı')."),
    karar_yil: str = Field("", description="Decision year ('Karar Yılı')."),
    karar_sayisi: str = Field("", description="Decision number ('Karar Sayısı')."),
    kanun_no: str = Field("", description="Relevant Law Number."),
    karar_date_begin: str = Field("", description="Decision start date (DD.MM.YYYY)."),
    karar_date_end: str = Field("", description="Decision end date (DD.MM.YYYY)."),
    resmi_gazete_sayi: str = Field("", description="Official Gazette number."),
    resmi_gazete_date: str = Field("", description="Official Gazette date (DD.MM.YYYY)."),
    tumce: str = Field("", description="Exact phrase search."),
    wild_card: str = Field("", description="Search for phrase and its inflections."),
    hepsi: str = Field("", description="Search for texts containing all specified words."),
    herhangi_birisi: str = Field("", description="Search for texts containing any of the specified words."),
    not_hepsi: str = Field("", description="Exclude texts containing these specified words.")
) -> UyusmazlikSearchResponse:
    """
    Searches for Court of Jurisdictional Disputes (Uyuşmazlık Mahkemesi) decisions.
    
    The Court of Jurisdictional Disputes (Uyuşmazlık Mahkemesi) resolves jurisdictional disputes between different court systems
    in Turkey, determining which court has jurisdiction over specific cases. This specialized
    court handles conflicts between civil, criminal, and administrative jurisdictions.
    
    Key Features:
    • Department filtering (Criminal, Civil, General Assembly decisions)
    • Dispute type classification (Jurisdiction vs Judgment disputes)
    • Decision outcome filtering (dispute resolution results)
    • Case number and date range filtering
    • Advanced text search with Boolean logic operators
    • Official Gazette reference search
    
    Dispute Types:
    • Jurisdictional Disputes (Görev Uyuşmazlığı): Which court has authority
    • Judgment Disputes (Hüküm Uyuşmazlığı): Conflicting final decisions
    
    Departments:
    • Criminal Section (Ceza Bölümü): Criminal section decisions
    • Civil Section (Hukuk Bölümü): Civil section decisions  
    • General Assembly Decisions (Genel Kurul Kararları): General Assembly decisions
    
    Advanced Search Options:
    • tumce: Exact phrase matching
    • wild_card: Phrase with inflections
    • hepsi: All words must be present
    • herhangi_birisi: Any word can be present
    • not_hepsi: Exclude specified words
    
    Use cases:
    • Research jurisdictional precedents
    • Understand court system boundaries
    • Analyze dispute resolution patterns
    • Study inter-court conflict resolution
    • Legal procedure and jurisdiction research
    
    Returns structured search results with dispute resolution information.
    Use get_uyusmazlik_document_markdown_from_url() for full decision texts.
    """
    
    # Convert string literals to enums
    bolum_enum = UyusmazlikBolumEnum(bolum) if bolum else UyusmazlikBolumEnum.TUMU
    uyusmazlik_turu_enum = UyusmazlikTuruEnum(uyusmazlik_turu) if uyusmazlik_turu else UyusmazlikTuruEnum.TUMU
    karar_sonuclari_enums = [UyusmazlikKararSonucuEnum(ks) for ks in karar_sonuclari]
    
    search_params = UyusmazlikSearchRequest(
        icerik=icerik,
        bolum=bolum_enum,
        uyusmazlik_turu=uyusmazlik_turu_enum,
        karar_sonuclari=karar_sonuclari_enums,
        esas_yil=esas_yil,
        esas_sayisi=esas_sayisi,
        karar_yil=karar_yil,
        karar_sayisi=karar_sayisi,
        kanun_no=kanun_no,
        karar_date_begin=karar_date_begin,
        karar_date_end=karar_date_end,
        resmi_gazete_sayi=resmi_gazete_sayi,
        resmi_gazete_date=resmi_gazete_date,
        tumce=tumce,
        wild_card=wild_card,
        hepsi=hepsi,
        herhangi_birisi=herhangi_birisi,
        not_hepsi=not_hepsi
    )
    
    logger.info(f"Tool 'search_uyusmazlik_decisions' called.")
    try:
        return await uyusmazlik_client_instance.search_decisions(search_params)
    except Exception as e:
        logger.exception(f"Error in tool 'search_uyusmazlik_decisions'.")
        raise

@app.tool(
    description="Retrieve the full text of a specific Court of Jurisdictional Disputes (Uyuşmazlık Mahkemesi) decision from its URL in Markdown format",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True
    }
)
async def get_uyusmazlik_document_markdown_from_url(document_url: HttpUrl) -> UyusmazlikDocumentMarkdown:
    """
    Retrieves the full text of a specific Uyuşmazlık Mahkemesi decision from its URL in Markdown format.
    
    This tool fetches complete jurisdictional dispute resolution decisions and converts them
    to clean, readable Markdown format suitable for legal analysis of inter-court disputes.
    
    Input Requirements:
    • document_url: Full URL to the decision document from search_uyusmazlik_decisions results
    • URL must be valid HttpUrl format from official Uyuşmazlık Mahkemesi database
    
    Output Format:
    • Clean Markdown text with jurisdictional dispute structure preserved
    • Organized sections: dispute facts, jurisdictional analysis, resolution ruling
    • Proper formatting for legal citations and court system references
    • Removes technical artifacts from source documents
    
    Jurisdictional Dispute Decision Content:
    • Complete analysis of jurisdictional conflicts between court systems
    • Detailed examination of applicable jurisdictional rules
    • Citation of relevant procedural laws and court organization statutes
    • Final resolution determining proper court jurisdiction
    • Reasoning for jurisdictional boundaries and court authority
    
    Use for:
    • Reading full jurisdictional dispute resolutions
    • Understanding court system boundaries and authority
    • Analyzing jurisdictional precedents and patterns
    • Research on court organization and procedure
    • Academic study of judicial system structure
    • Legal practice guidance on proper court selection
    """
    logger.info(f"Tool 'get_uyusmazlik_document_markdown_from_url' called for URL: {str(document_url)}")
    if not document_url:
        raise ValueError("Document URL (document_url) is required for Uyuşmazlık document retrieval.")
    try:
        return await uyusmazlik_client_instance.get_decision_document_as_markdown(str(document_url))
    except Exception as e:
        logger.exception(f"Error in tool 'get_uyusmazlik_document_markdown_from_url'.")
        raise

# --- MCP Tools for Anayasa Mahkemesi (Norm Denetimi) ---
@app.tool(
    description="Search Constitutional Court (Anayasa Mahkemesi) norm control decisions with comprehensive filtering for constitutional law research and judicial review analysis",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_anayasa_norm_denetimi_decisions(
    keywords_all: List[str] = Field(default_factory=list, description="Keywords for AND logic."),
    keywords_any: List[str] = Field(default_factory=list, description="Keywords for OR logic."),
    keywords_exclude: List[str] = Field(default_factory=list, description="Keywords to exclude."),
    period: Literal["ALL", "1", "2"] = Field("ALL", description="Constitutional period ('ALL': All, '1': 1961, '2': 1982)."),
    case_number_esas: Optional[str] = Field(None, description="Case registry number (e.g., '2023/123')."),
    decision_number_karar: Optional[str] = Field(None, description="Decision number (e.g., '2023/456')."),
    first_review_date_start: Optional[str] = Field(None, description="First review start date (DD/MM/YYYY)."),
    first_review_date_end: Optional[str] = Field(None, description="First review end date (DD/MM/YYYY)."),
    decision_date_start: Optional[str] = Field(None, description="Decision start date (DD/MM/YYYY)."),
    decision_date_end: Optional[str] = Field(None, description="Decision end date (DD/MM/YYYY)."),
    application_type: Literal["ALL", "1", "2", "3"] = Field("ALL", description="Application type ('ALL': All, '1': İptal, '2': İtiraz, '3': Diğer)."),
    applicant_general_name: Optional[str] = Field(None, description="General applicant name."),
    applicant_specific_name: Optional[str] = Field(None, description="Specific applicant name."),
    official_gazette_date_start: Optional[str] = Field(None, description="Official Gazette start date (DD/MM/YYYY)."),
    official_gazette_date_end: Optional[str] = Field(None, description="Official Gazette end date (DD/MM/YYYY)."),
    official_gazette_number_start: Optional[str] = Field(None, description="Official Gazette starting number."),
    official_gazette_number_end: Optional[str] = Field(None, description="Official Gazette ending number."),
    has_press_release: Literal["ALL", "0", "1"] = Field("ALL", description="Press release ('ALL': All, '0': No, '1': Yes)."),
    has_dissenting_opinion: Literal["ALL", "0", "1"] = Field("ALL", description="Dissenting opinion ('ALL': All, '0': No, '1': Yes)."),
    has_different_reasoning: Literal["ALL", "0", "1"] = Field("ALL", description="Different reasoning ('ALL': All, '0': No, '1': Yes)."),
    attending_members_names: List[str] = Field(default_factory=list, description="List of attending members' exact names."),
    rapporteur_name: Optional[str] = Field(None, description="Rapporteur's exact name."),
    norm_type: Literal["ALL", "1", "2", "14", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "0", "13"] = Field("ALL", description="Type of reviewed norm."),
    norm_id_or_name: Optional[str] = Field(None, description="Number or name of the norm."),
    norm_article: Optional[str] = Field(None, description="Article number of the norm."),
    review_outcomes: List[Literal["ALL", "1", "2", "3", "4", "5", "6", "7", "8", "12"]] = Field(default_factory=list, description="List of review outcomes."),
    reason_for_final_outcome: Literal["ALL", "29", "1", "2", "30", "3", "4", "27", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26"] = Field("ALL", description="Main reason for decision outcome."),
    basis_constitution_article_numbers: List[str] = Field(default_factory=list, description="List of supporting Constitution article numbers."),
    results_per_page: int = Field(10, description="Results per page (10, 20, 30, 40, 50)."),
    page_to_fetch: int = Field(1, ge=1, description="Page number to fetch."),
    sort_by_criteria: str = Field("KararTarihi", description="Sort criteria ('KararTarihi', 'YayinTarihi', 'Toplam').")
) -> AnayasaSearchResult:
    """
    Searches Constitutional Court (Anayasa Mahkemesi) norm control decisions with comprehensive filtering.
    
    The Constitutional Court is Turkey's highest constitutional authority, responsible for judicial
    review of laws, regulations, and constitutional amendments. Norm control (Norm Denetimi) is the
    court's power to review the constitutionality of legal norms.
    
    Key Features:
    • Boolean keyword search (AND, OR, NOT logic)
    • Constitutional period filtering (1961 vs 1982 Constitution)
    • Case and decision number filtering
    • Date range filtering for review and decision dates
    • Application type classification (İptal, İtiraz, etc.)
    • Applicant filtering (government entities, opposition parties)
    • Official Gazette publication filtering
    • Judicial opinion analysis (dissents, different reasoning)
    • Court member and rapporteur filtering
    • Norm type classification (laws, regulations, decrees)
    • Review outcome filtering (constitutionality determinations)
    • Constitutional basis article referencing
    
    Constitutional Review Types:
    • Abstract review: Ex ante constitutional control
    • Concrete review: Constitutional questions during litigation
    • Legislative review: Parliamentary acts and government decrees
    • Regulatory review: Administrative regulations and bylaws
    
    Advanced Research Capabilities:
    • Track constitutional interpretation evolution
    • Analyze court composition effects on decisions
    • Study dissenting opinion patterns
    • Research specific constitutional provisions
    • Monitor judicial review trends over time
    
    Use cases:
    • Constitutional law research and analysis
    • Legislative drafting constitutional compliance
    • Academic constitutional law study
    • Legal precedent analysis for constitutional questions
    • Government policy constitutional assessment
    
    Returns structured constitutional court data with comprehensive metadata.
    Use get_anayasa_norm_denetimi_document_markdown() for full decision texts (paginated).
    """
    
    # Convert string literals to enums
    period_enum = AnayasaDonemEnum(period)
    application_type_enum = AnayasaBasvuruTuruEnum(application_type)
    has_press_release_enum = AnayasaVarYokEnum(has_press_release)
    has_dissenting_opinion_enum = AnayasaVarYokEnum(has_dissenting_opinion)
    has_different_reasoning_enum = AnayasaVarYokEnum(has_different_reasoning)
    norm_type_enum = AnayasaNormTuruEnum(norm_type)
    review_outcomes_enums = [AnayasaIncelemeSonucuEnum(ro) for ro in review_outcomes]
    reason_for_final_outcome_enum = AnayasaSonucGerekcesiEnum(reason_for_final_outcome)
    
    search_query = AnayasaNormDenetimiSearchRequest(
        keywords_all=keywords_all,
        keywords_any=keywords_any,
        keywords_exclude=keywords_exclude,
        period=period_enum,
        case_number_esas=case_number_esas,
        decision_number_karar=decision_number_karar,
        first_review_date_start=first_review_date_start,
        first_review_date_end=first_review_date_end,
        decision_date_start=decision_date_start,
        decision_date_end=decision_date_end,
        application_type=application_type_enum,
        applicant_general_name=applicant_general_name,
        applicant_specific_name=applicant_specific_name,
        official_gazette_date_start=official_gazette_date_start,
        official_gazette_date_end=official_gazette_date_end,
        official_gazette_number_start=official_gazette_number_start,
        official_gazette_number_end=official_gazette_number_end,
        has_press_release=has_press_release_enum,
        has_dissenting_opinion=has_dissenting_opinion_enum,
        has_different_reasoning=has_different_reasoning_enum,
        attending_members_names=attending_members_names,
        rapporteur_name=rapporteur_name,
        norm_type=norm_type_enum,
        norm_id_or_name=norm_id_or_name,
        norm_article=norm_article,
        review_outcomes=review_outcomes_enums,
        reason_for_final_outcome=reason_for_final_outcome_enum,
        basis_constitution_article_numbers=basis_constitution_article_numbers,
        results_per_page=results_per_page,
        page_to_fetch=page_to_fetch,
        sort_by_criteria=sort_by_criteria
    )
    
    logger.info(f"Tool 'search_anayasa_norm_denetimi_decisions' called.")
    try:
        return await anayasa_norm_client_instance.search_norm_denetimi_decisions(search_query)
    except Exception as e:
        logger.exception(f"Error in tool 'search_anayasa_norm_denetimi_decisions'.")
        raise

@app.tool(
    description="Retrieve the full text of a Constitutional Court norm control decision in paginated Markdown format",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True
    }
)
async def get_anayasa_norm_denetimi_document_markdown(
    document_url: str = Field(..., description="The URL path (e.g., /ND/YYYY/NN) or full https URL of the AYM Norm Denetimi decision from normkararlarbilgibankasi.anayasa.gov.tr."),
    page_number: Optional[int] = Field(1, ge=1, description="Page number for paginated Markdown content (1-indexed). Default is 1 (first 5,000 characters).")
) -> AnayasaDocumentMarkdown:
    """
    Retrieves the full text of a Constitutional Court norm control decision in paginated Markdown format.
    
    This tool fetches complete constitutional court decisions on norm control (judicial review)
    and converts them to clean, readable Markdown format. Due to the length of constitutional
    decisions, content is paginated into 5,000-character chunks.
    
    Input Requirements:
    • document_url: URL path (e.g., /ND/YYYY/NN) from search_anayasa_norm_denetimi_decisions results
    • page_number: Page number for pagination (1-indexed, default: 1)
    
    Output Format:
    • Clean Markdown text with constitutional legal structure preserved
    • Organized sections: case summary, constitutional analysis, ruling
    • Proper formatting for constitutional law citations and references
    • Paginated content with navigation information
    
    Constitutional Decision Content:
    • Complete constitutional analysis and judicial review reasoning
    • Detailed examination of constitutional provisions
    • Citation of constitutional articles and legal principles
    • Final constitutionality determination with justification
    • Analysis of legislative intent vs constitutional requirements
    • Dissenting and concurring opinions when available
    
    Use for:
    • Reading full constitutional court decisions
    • Constitutional law research and precedent analysis
    • Understanding judicial review standards and methodology
    • Academic constitutional law study
    • Legislative drafting constitutional compliance guidance
    """
    logger.info(f"Tool 'get_anayasa_norm_denetimi_document_markdown' called for URL: {document_url}, Page: {page_number}")
    if not document_url or not document_url.strip():
        raise ValueError("Document URL is required for Anayasa Norm Denetimi document retrieval.")
    current_page_to_fetch = page_number if page_number is not None and page_number >= 1 else 1
    try:
        return await anayasa_norm_client_instance.get_decision_document_as_markdown(document_url, page_number=current_page_to_fetch)
    except Exception as e:
        logger.exception(f"Error in tool 'get_anayasa_norm_denetimi_document_markdown'.")
        raise

# --- MCP Tools for Anayasa Mahkemesi (Bireysel Başvuru Karar Raporu & Belgeler) ---
@app.tool(
    description="Search Constitutional Court individual application (Bireysel Başvuru) decisions for human rights violation reports with keyword filtering",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_anayasa_bireysel_basvuru_report(
    keywords: List[str] = Field(default_factory=list, description="Keywords for AND logic."),
    page_to_fetch: int = Field(1, ge=1, description="Page number to fetch for the report. Default is 1.")
) -> AnayasaBireyselReportSearchResult:
    """
    Searches Constitutional Court individual application (Bireysel Başvuru) decisions for human rights reports.
    
    Individual applications allow citizens to petition the Constitutional Court directly for
    violations of fundamental rights and freedoms. This tool generates decision search reports
    that help identify relevant human rights violation cases.
    
    Key Features:
    • Keyword-based search with AND logic
    • Human rights violation case identification
    • Individual petition decision analysis
    • Fundamental rights and freedoms research
    • Pagination support for large result sets
    
    Individual Application System:
    • Direct citizen access to Constitutional Court
    • Human rights and fundamental freedoms protection
    • Alternative to European Court of Human Rights
    • Domestic remedy for constitutional violations
    • Individual justice and rights enforcement
    
    Human Rights Categories:
    • Right to life and personal liberty
    • Right to fair trial and due process
    • Freedom of expression and press
    • Freedom of religion and conscience
    • Property rights and economic freedoms
    • Right to privacy and family life
    • Political rights and democratic participation
    
    Use cases:
    • Human rights violation research
    • Individual petition precedent analysis
    • Constitutional rights interpretation study
    • Legal remedies for rights violations
    • Academic human rights law research
    • Civil society and NGO legal research
    
    Returns search report with case summaries and violation categories.
    Use get_anayasa_bireysel_basvuru_document_markdown() for full decision texts.
    """
    
    search_query = AnayasaBireyselReportSearchRequest(
        keywords=keywords,
        page_to_fetch=page_to_fetch
    )
    
    logger.info(f"Tool 'search_anayasa_bireysel_basvuru_report' called.")
    try:
        return await anayasa_bireysel_client_instance.search_bireysel_basvuru_report(search_query)
    except Exception as e:
        logger.exception(f"Error in tool 'search_anayasa_bireysel_basvuru_report'.")
        raise

@app.tool(
    description="Retrieve the full text of a Constitutional Court individual application decision in paginated Markdown format",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True
    }
)
async def get_anayasa_bireysel_basvuru_document_markdown(
    document_url_path: str = Field(..., description="The URL path (e.g., /BB/YYYY/NNNN) of the AYM Bireysel Başvuru decision from kararlarbilgibankasi.anayasa.gov.tr."),
    page_number: Optional[int] = Field(1, ge=1, description="Page number for paginated Markdown content (1-indexed). Default is 1 (first 5,000 characters).")
) -> AnayasaBireyselBasvuruDocumentMarkdown:
    """
    Retrieves the full text of a Constitutional Court individual application decision in paginated Markdown format.
    
    This tool fetches complete human rights violation decisions from individual applications
    and converts them to clean, readable Markdown format. Content is paginated into
    5,000-character chunks for easier processing.
    
    Input Requirements:
    • document_url_path: URL path (e.g., /BB/YYYY/NNNN) from search results
    • page_number: Page number for pagination (1-indexed, default: 1)
    
    Output Format:
    • Clean Markdown text with human rights case structure preserved
    • Organized sections: applicant info, violation claims, court analysis, ruling
    • Proper formatting for human rights law citations and references
    • Paginated content with navigation information
    
    Individual Application Decision Content:
    • Complete human rights violation analysis
    • Detailed examination of fundamental rights claims
    • Citation of constitutional articles and international human rights law
    • Final determination on rights violations with remedies
    • Analysis of domestic court proceedings and their adequacy
    • Individual remedy recommendations and compensation
    
    Use for:
    • Reading full human rights violation decisions
    • Human rights law research and precedent analysis
    • Understanding constitutional rights protection standards
    • Individual petition strategy development
    • Academic human rights and constitutional law study
    • Civil society monitoring of rights violations
    """
    logger.info(f"Tool 'get_anayasa_bireysel_basvuru_document_markdown' called for URL path: {document_url_path}, Page: {page_number}")
    if not document_url_path or not document_url_path.strip() or not document_url_path.startswith("/BB/"):
        raise ValueError("Document URL path (e.g., /BB/YYYY/NNNN) is required for Anayasa Bireysel Başvuru document retrieval.")
    current_page_to_fetch = page_number if page_number is not None and page_number >= 1 else 1
    try:
        return await anayasa_bireysel_client_instance.get_decision_document_as_markdown(document_url_path, page_number=current_page_to_fetch)
    except Exception as e:
        logger.exception(f"Error in tool 'get_anayasa_bireysel_basvuru_document_markdown'.")
        raise

# --- MCP Tools for KIK (Kamu İhale Kurulu) ---
@app.tool(
    description="Search Public Procurement Authority (Kamu İhale Kurulu - KIK) decisions with comprehensive filtering for public procurement law and administrative dispute research",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_kik_decisions(
    karar_tipi: Literal["rbUyusmazlik", "rbDuzenleyici", "rbMahkeme"] = Field("rbUyusmazlik", description="Type of KIK Decision."),
    karar_no: Optional[str] = Field(None, description="Decision Number (e.g., '2024/UH.II-1766')."),
    karar_tarihi_baslangic: Optional[str] = Field(None, description="Decision Date Start (DD.MM.YYYY)."),
    karar_tarihi_bitis: Optional[str] = Field(None, description="Decision Date End (DD.MM.YYYY)."),
    basvuru_sahibi: Optional[str] = Field(None, description="Applicant."),
    ihaleyi_yapan_idare: Optional[str] = Field(None, description="Procuring Entity."),
    basvuru_konusu_ihale: Optional[str] = Field(None, description="Tender subject of the application."),
    karar_metni: Optional[str] = Field(None, description="Keyword/phrase in decision text."),
    yil: Optional[str] = Field(None, description="Year of the decision."),
    resmi_gazete_tarihi: Optional[str] = Field(None, description="Official Gazette Date (DD.MM.YYYY)."),
    resmi_gazete_sayisi: Optional[str] = Field(None, description="Official Gazette Number."),
    page: int = Field(1, ge=1, description="Results page number.")
) -> KikSearchResult:
    """
    Searches Public Procurement Authority (Kamu İhale Kurulu - KIK) decisions with comprehensive filtering.
    
    The Public Procurement Authority (KIK) is Turkey's public procurement regulatory authority, responsible for overseeing
    government procurement processes and resolving procurement-related disputes. This tool
    provides access to official procurement decisions and regulatory interpretations.
    
    Key Features:
    • Decision type filtering (Disputes, Regulatory, Court decisions)
    • Decision number and date range filtering
    • Applicant and procuring entity filtering
    • Tender subject and content-based search
    • Official Gazette publication tracking
    • Pagination support for large result sets
    
    Decision Types:
    • rbUyusmazlik: Procurement dispute resolutions
    • rbDuzenleyici: Regulatory and interpretive decisions
    • rbMahkeme: Court-related procurement decisions
    
    Public Procurement Law Areas:
    • Tender procedure disputes and violations
    • Bid evaluation and award challenges
    • Procurement regulation interpretations
    • Contract performance and compliance issues
    • Vendor qualification and exclusion decisions
    • Emergency procurement and exceptions
    
    Use cases:
    • Public procurement law research
    • Tender dispute precedent analysis
    • Government contracting compliance guidance
    • Procurement policy and regulation study
    • Vendor rights and remedies research
    • Academic public administration law study
    
    Returns structured procurement decision data with comprehensive metadata.
    Use get_kik_document_markdown() for full decision texts (paginated).
    """
    
    # Convert string literal to enum
    karar_tipi_enum = KikKararTipi(karar_tipi)
    
    search_query = KikSearchRequest(
        karar_tipi=karar_tipi_enum,
        karar_no=karar_no,
        karar_tarihi_baslangic=karar_tarihi_baslangic,
        karar_tarihi_bitis=karar_tarihi_bitis,
        basvuru_sahibi=basvuru_sahibi,
        ihaleyi_yapan_idare=ihaleyi_yapan_idare,
        basvuru_konusu_ihale=basvuru_konusu_ihale,
        karar_metni=karar_metni,
        yil=yil,
        resmi_gazete_tarihi=resmi_gazete_tarihi,
        resmi_gazete_sayisi=resmi_gazete_sayisi,
        page=page
    )
    
    logger.info(f"Tool 'search_kik_decisions' called.")
    try:
        api_response = await kik_client_instance.search_decisions(search_query)
        page_param_for_log = search_query.page if hasattr(search_query, 'page') else 1
        if not api_response.decisions and api_response.total_records == 0 and page_param_for_log == 1:
             logger.warning(f"KIK search returned no decisions for query.")
        return api_response
    except Exception as e:
        logger.exception(f"Error in KIK search tool 'search_kik_decisions'.")
        current_page_val = search_query.page if hasattr(search_query, 'page') else 1
        return KikSearchResult(decisions=[], total_records=0, current_page=current_page_val)

@app.tool(
    description="Retrieve the full text of a Public Procurement Authority (KIK) decision in paginated Markdown format",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True
    }
)
async def get_kik_document_markdown(
    karar_id: str = Field(..., description="The Base64 encoded KIK decision identifier."),
    page_number: Optional[int] = Field(1, ge=1, description="Page number for paginated Markdown content (1-indexed). Default is 1.")
) -> KikDocumentMarkdown:
    """
    Retrieves the full text of a KIK (Public Procurement Authority) decision in paginated Markdown format.
    
    This tool fetches complete public procurement authority decisions and converts them to clean,
    readable Markdown format. Content is paginated into manageable chunks for easier processing.
    
    Input Requirements:
    • karar_id: Base64 encoded decision identifier from search_kik_decisions results
    • page_number: Page number for pagination (1-indexed, default: 1)
    
    Output Format:
    • Clean Markdown text with procurement decision structure preserved
    • Organized sections: case info, procurement facts, legal analysis, ruling
    • Proper formatting for procurement law citations and references
    • Paginated content with navigation information
    
    Public Procurement Decision Content:
    • Complete procurement dispute analysis and resolution
    • Detailed examination of tender procedures and compliance
    • Citation of procurement laws, regulations, and guidelines
    • Final determination on procurement disputes with remedies
    • Analysis of bid evaluation and award processes
    • Regulatory interpretations and policy guidance
    
    Use for:
    • Reading full public procurement authority decisions
    • Procurement law research and precedent analysis
    • Understanding tender dispute resolution standards
    • Government contracting compliance guidance
    • Academic public administration and procurement law study
    • Vendor legal strategy and rights enforcement
    """
    logger.info(f"Tool 'get_kik_document_markdown' called for KIK karar_id: {karar_id}, Markdown Page: {page_number}")
    
    if not karar_id or not karar_id.strip():
        logger.error("KIK Document retrieval: karar_id cannot be empty.")
        return KikDocumentMarkdown( 
            retrieved_with_karar_id=karar_id,
            error_message="karar_id is required and must be a non-empty string.",
            current_page=page_number or 1,
            total_pages=1,
            is_paginated=False
            )

    current_page_to_fetch = page_number if page_number is not None and page_number >= 1 else 1

    try:
        return await kik_client_instance.get_decision_document_as_markdown(
            karar_id_b64=karar_id, 
            page_number=current_page_to_fetch
        )
    except Exception as e:
        logger.exception(f"Error in KIK document retrieval tool 'get_kik_document_markdown' for karar_id: {karar_id}")
        return KikDocumentMarkdown(
            retrieved_with_karar_id=karar_id,
            error_message=f"Tool-level error during KIK document retrieval: {str(e)}",
            current_page=current_page_to_fetch, 
            total_pages=1, 
            is_paginated=False
        )
@app.tool(
    description="Search Competition Authority (Rekabet Kurumu) decisions with comprehensive filtering for competition law and antitrust research",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_rekabet_kurumu_decisions(
    sayfaAdi: Optional[str] = Field(None, description="Search in decision title (Başlık)."),
    YayinlanmaTarihi: Optional[str] = Field(None, description="Publication date (Yayım Tarihi), e.g., DD.MM.YYYY."),
    PdfText: Optional[str] = Field(
        None,
        description='Search in decision text (Metin). For an exact phrase match, enclose the phrase in double quotes (e.g., "\\"vertical agreement\\" competition). The website indicates that using "" provides more precise results for phrases.'
    ),
    KararTuru: Literal[ 
        "", 
        "Birleşme ve Devralma",
        "Diğer",
        "Menfi Tespit ve Muafiyet",
        "Özelleştirme",
        "Rekabet İhlali"
    ] = Field("", description="Decision type (Karar Türü). Leave empty for 'All'. Options: '', 'Birleşme ve Devralma', 'Diğer', 'Menfi Tespit ve Muafiyet', 'Özelleştirme', 'Rekabet İhlali'."),
    KararSayisi: Optional[str] = Field(None, description="Decision number (Karar Sayısı)."),
    KararTarihi: Optional[str] = Field(None, description="Decision date (Karar Tarihi), e.g., DD.MM.YYYY."),
    page: int = Field(1, ge=1, description="Page number to fetch for the results list.")
) -> RekabetSearchResult:
    """
    Searches Competition Authority (Rekabet Kurumu) decisions with comprehensive filtering.
    
    The Competition Authority (Rekabet Kurumu) is Turkey's competition authority, responsible for enforcing antitrust laws,
    preventing anti-competitive practices, and regulating mergers and acquisitions. This tool
    provides access to official competition law decisions and regulatory interpretations.
    
    Key Features:
    • Decision type filtering (Mergers, Violations, Exemptions, etc.)
    • Title and content-based text search with exact phrase matching
    • Publication date filtering
    • Case year and decision number filtering
    • Pagination support for large result sets
    
    Competition Law Decision Types:
    • Birleşme ve Devralma: Merger and acquisition approvals
    • Rekabet İhlali: Competition violation investigations
    • Muafiyet: Exemption and negative clearance decisions
    • Geçici Tedbir: Interim measures and emergency orders
    • Sektör İncelemesi: Sector inquiry and market studies
    • Diğer: Other regulatory and interpretive decisions
    
    Competition Law Areas:
    • Anti-competitive agreements and cartels
    • Abuse of dominant market position
    • Merger control and market concentration
    • Vertical agreements and distribution restrictions
    • Unfair competition and consumer protection
    • Market definition and economic analysis
    
    Advanced Search:
    • Exact phrase matching with double quotes for precise legal terms
    • Content search across full decision texts (PdfText parameter)
    • Title search for specific case names or topics
    • Date range filtering for temporal analysis
    
    Example for exact phrase search: PdfText="\\"tender process\\" consultancy"
    
    Use cases:
    • Competition law research and precedent analysis
    • Merger and acquisition due diligence
    • Antitrust compliance and risk assessment
    • Market analysis and competitive intelligence
    • Academic competition economics study
    • Legal strategy development for competition cases
    
    Returns structured competition authority data with comprehensive metadata.
    Use get_rekabet_kurumu_document() for full decision texts (paginated PDF conversion).
    """
    
    karar_turu_guid_enum = KARAR_TURU_ADI_TO_GUID_ENUM_MAP.get(KararTuru)

    try:
        if karar_turu_guid_enum is None: 
            logger.warning(f"Invalid user-provided KararTuru: '{KararTuru}'. Defaulting to TUMU (all).")
            karar_turu_guid_enum = RekabetKararTuruGuidEnum.TUMU
    except Exception as e_map: 
        logger.error(f"Error mapping KararTuru '{KararTuru}': {e_map}. Defaulting to TUMU.")
        karar_turu_guid_enum = RekabetKararTuruGuidEnum.TUMU

    search_query = RekabetKurumuSearchRequest(
        sayfaAdi=sayfaAdi,
        YayinlanmaTarihi=YayinlanmaTarihi,
        PdfText=PdfText,
        KararTuruID=karar_turu_guid_enum, 
        KararSayisi=KararSayisi,
        KararTarihi=KararTarihi,
        page=page
    )
    logger.info(f"Tool 'search_rekabet_kurumu_decisions' called. Query: {search_query.model_dump_json(exclude_none=True, indent=2)}")
    try:
       
        return await rekabet_client_instance.search_decisions(search_query)
    except Exception as e:
        logger.exception("Error in tool 'search_rekabet_kurumu_decisions'.")
        return RekabetSearchResult(decisions=[], retrieved_page_number=page, total_records_found=0, total_pages=0)

@app.tool(
    description="Retrieve the full text of a Competition Authority (Rekabet Kurumu) decision in paginated Markdown format converted from PDF",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True
    }
)
async def get_rekabet_kurumu_document(
    karar_id: str = Field(..., description="GUID (kararId) of the Rekabet Kurumu decision. This ID is obtained from search results."),
    page_number: Optional[int] = Field(1, ge=1, description="Requested page number for the Markdown content converted from PDF (1-indexed). Default is 1.")
) -> RekabetDocument:
    """
    Retrieves the full text of a Turkish Competition Authority decision in paginated Markdown format.
    
    This tool fetches complete competition authority decisions and converts them from PDF to clean,
    readable Markdown format. Content is paginated for easier processing of lengthy competition law decisions.
    
    Input Requirements:
    • karar_id: GUID (kararId) from search_rekabet_kurumu_decisions results
    • page_number: Page number for pagination (1-indexed, default: 1)
    
    Output Format:
    • Clean Markdown text converted from original PDF documents
    • Organized sections: case summary, market analysis, legal reasoning, decision
    • Proper formatting for competition law citations and references
    • Paginated content with navigation information
    • Metadata including PDF source link and document information
    
    Competition Authority Decision Content:
    • Complete competition law analysis and market assessment
    • Detailed examination of anti-competitive practices
    • Economic analysis and market definition studies
    • Citation of competition laws, regulations, and precedents
    • Final determination on competition violations with remedies
    • Merger and acquisition approval conditions
    • Regulatory guidance and policy interpretations
    
    Use for:
    • Reading full competition authority decisions
    • Competition law research and precedent analysis
    • Market analysis and economic impact assessment
    • Antitrust compliance and risk evaluation
    • Academic competition economics and law study
    • Legal strategy development for competition cases
    """
    logger.info(f"Tool 'get_rekabet_kurumu_document' called. Karar ID: {karar_id}, Markdown Page: {page_number}")
    
    current_page_to_fetch = page_number if page_number is not None and page_number >= 1 else 1
    
    try:
      
        return await rekabet_client_instance.get_decision_document(karar_id, page_number=current_page_to_fetch)
    except Exception as e:
        logger.exception(f"Error in tool 'get_rekabet_kurumu_document'. Karar ID: {karar_id}")
        raise 

# --- MCP Tools for Bedesten (Alternative Yargitay Search) ---
@app.tool(
    description="Search Court of Cassation (Yargıtay) decisions using the Bedesten API - an alternative data source that complements the primary Court of Cassation API. This tool provides access to recent decisions with advanced filtering capabilities including chamber selection, date ranges, and exact phrase matching. Use this alongside search_yargitay_detailed for comprehensive coverage.",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_yargitay_bedesten(
    phrase: str = Field(..., description="""
        Aranacak kavram/kelime. İki farklı arama türü desteklenir:
        • Normal arama: "mülkiyet kararı" - kelimeler ayrı ayrı aranır
        • Tam cümle arama: "\"mülkiyet kararı\"" - tırnak içindeki ifade aynen aranır
        Tam cümle aramalar daha kesin sonuçlar verir.
    """),
    pageSize: int = Field(10, ge=1, le=100, description="Sayfa başına sonuç sayısı"),
    pageNumber: int = Field(1, ge=1, description="Sayfa numarası"),
    birimAdi: Optional[YargitayBirimEnum] = Field(None, description="""
        Yargıtay chamber/board filter (optional). Available options:
        • None for ALL chambers  
        • 'Hukuk Genel Kurulu' (Civil General Assembly)
        • '1. Hukuk Dairesi' through '23. Hukuk Dairesi' (Civil Chambers 1-23)
        • 'Hukuk Daireleri Başkanlar Kurulu' (Civil Chambers Presidents Board)
        • 'Ceza Genel Kurulu' (Criminal General Assembly)
        • '1. Ceza Dairesi' through '23. Ceza Dairesi' (Criminal Chambers 1-23)  
        • 'Ceza Daireleri Başkanlar Kurulu' (Criminal Chambers Presidents Board)
        • 'Büyük Genel Kurulu' (Grand General Assembly)
        Total: 49 chamber options
    """),
    kararTarihiStart: Optional[str] = Field(None, description="""
        Decision start date filter (optional). Format: YYYY-MM-DDTHH:MM:SS.000Z
        Example: "2024-01-01T00:00:00.000Z" for decisions from Jan 1, 2024
        Use with kararTarihiEnd for date range filtering
    """),
    kararTarihiEnd: Optional[str] = Field(None, description="""
        Decision end date filter (optional). Format: YYYY-MM-DDTHH:MM:SS.000Z
        Example: "2024-12-31T23:59:59.999Z" for decisions until Dec 31, 2024
        Use with kararTarihiStart for date range filtering
    """)
) -> dict:
    """
    Searches Yargıtay decisions using Bedesten API (alternative source).
    This complements search_yargitay_detailed for comprehensive coverage.
    Always use BOTH Yargıtay search tools for complete results.
    
    Returns a simplified response with decision list and metadata.
    """
    search_data = BedestenSearchData(
        pageSize=pageSize,
        pageNumber=pageNumber,
        itemTypeList=["YARGITAYKARARI"],  # Only Yargıtay decisions
        phrase=phrase,
        birimAdi=birimAdi,
        kararTarihiStart=kararTarihiStart,
        kararTarihiEnd=kararTarihiEnd
    )
    
    search_request = BedestenSearchRequest(data=search_data)
    
    logger.info(f"Tool 'search_yargitay_bedesten' called: phrase='{phrase}', birimAdi='{birimAdi}', dateRange='{kararTarihiStart}' to '{kararTarihiEnd}', page={pageNumber}")
    
    try:
        response = await bedesten_client_instance.search_documents(search_request)
        
        # Return simplified response format
        return {
            "decisions": [d.model_dump() for d in response.data.emsalKararList],
            "total_records": response.data.total,
            "requested_page": pageNumber,
            "page_size": pageSize
        }
    except Exception as e:
        logger.exception("Error in tool 'search_yargitay_bedesten'")
        raise

@app.tool(
    description="Retrieve a specific Yargıtay decision document from the Bedesten API and convert it to Markdown format. This tool takes a documentId obtained from search results and fetches the full decision text, supporting both HTML and PDF source documents. The content is automatically converted to readable Markdown format for easy analysis.",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def get_yargitay_bedesten_document_markdown(
    documentId: str = Field(..., description="Document ID from Bedesten search results")
) -> BedestenDocumentMarkdown:
    """
    Retrieves a Yargıtay decision document from Bedesten API and converts to Markdown.
    Supports both HTML and PDF content types.
    Use documentId from search_yargitay_bedesten results.
    """
    logger.info(f"Tool 'get_yargitay_bedesten_document_markdown' called for ID: {documentId}")
    
    if not documentId or not documentId.strip():
        raise ValueError("Document ID must be a non-empty string.")
    
    try:
        return await bedesten_client_instance.get_document_as_markdown(documentId)
    except Exception as e:
        logger.exception("Error in tool 'get_yargitay_bedesten_document_markdown'")
        raise

# --- MCP Tools for Bedesten (Alternative Danıştay Search) ---
@app.tool(
    description="Search Council of State (Danıştay) decisions using the Bedesten API - a powerful alternative data source. This tool provides access to administrative court decisions with comprehensive filtering options including chamber (daire) selection (27 options), date ranges, and exact phrase matching. Use this alongside search_danistay_by_keyword and search_danistay_detailed for complete coverage of administrative law decisions.",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_danistay_bedesten(
    phrase: str = Field(..., description="""
        Aranacak kavram/kelime. İki farklı arama türü desteklenir:
        • Normal arama: "mülkiyet kararı" - kelimeler ayrı ayrı aranır
        • Tam cümle arama: "\"mülkiyet kararı\"" - tırnak içindeki ifade aynen aranır
        Tam cümle aramalar daha kesin sonuçlar verir.
    """),
    pageSize: int = Field(10, ge=1, le=100, description="Sayfa başına sonuç sayısı"),
    pageNumber: int = Field(1, ge=1, description="Sayfa numarası"),
    birimAdi: Optional[DanistayBirimEnum] = Field(None, description="""
        Danıştay chamber/board filter (optional). Available options:
        • None for ALL chambers
        • Main Councils: 'Büyük Gen.Kur.', 'İdare Dava Daireleri Kurulu', 'Vergi Dava Daireleri Kurulu'
        • Chambers: '1. Daire' through '17. Daire' (17 administrative chambers)
        • Special Councils: 'İçtihatları Birleştirme Kurulu', 'İdari İşler Kurulu', 'Başkanlar Kurulu'
        • Military: 'Askeri Yüksek İdare Mahkemesi' and its chambers/councils
        Total: 27 chamber options
    """),
    kararTarihiStart: Optional[str] = Field(None, description="""
        Decision start date filter (optional). Format: YYYY-MM-DDTHH:MM:SS.000Z
        Example: "2024-01-01T00:00:00.000Z" for decisions from Jan 1, 2024
        Use with kararTarihiEnd for date range filtering
    """),
    kararTarihiEnd: Optional[str] = Field(None, description="""
        Decision end date filter (optional). Format: YYYY-MM-DDTHH:MM:SS.000Z
        Example: "2024-12-31T23:59:59.999Z" for decisions until Dec 31, 2024
        Use with kararTarihiStart for date range filtering
    """)
) -> dict:
    """
    Searches Danıştay decisions using Bedesten API (alternative source).
    This complements existing Danıştay search tools (search_danistay_by_keyword, search_danistay_detailed) 
    for comprehensive coverage. Always use ALL Danıştay search tools for complete results.
    
    Returns a simplified response with decision list and metadata.
    """
    search_data = BedestenSearchData(
        pageSize=pageSize,
        pageNumber=pageNumber,
        itemTypeList=["DANISTAYKARAR"],  # Only Danıştay decisions
        phrase=phrase,
        birimAdi=birimAdi,
        kararTarihiStart=kararTarihiStart,
        kararTarihiEnd=kararTarihiEnd
    )
    
    search_request = BedestenSearchRequest(data=search_data)
    
    logger.info(f"Tool 'search_danistay_bedesten' called: phrase='{phrase}', birimAdi='{birimAdi}', dateRange='{kararTarihiStart}' to '{kararTarihiEnd}', page={pageNumber}")
    
    try:
        response = await bedesten_client_instance.search_documents(search_request)
        
        # Return simplified response format
        return {
            "decisions": [d.model_dump() for d in response.data.emsalKararList],
            "total_records": response.data.total,
            "requested_page": pageNumber,
            "page_size": pageSize
        }
    except Exception as e:
        logger.exception("Error in tool 'search_danistay_bedesten'")
        raise

@app.tool(
    description="Retrieve a specific Danıştay decision document from the Bedesten API and convert it to Markdown format. This tool fetches the complete administrative court decision text using a documentId from search results. It handles both HTML and PDF source documents and converts them to structured Markdown for easy reading and analysis.",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def get_danistay_bedesten_document_markdown(
    documentId: str = Field(..., description="Document ID from Bedesten search results")
) -> BedestenDocumentMarkdown:
    """
    Retrieves a Danıştay decision document from Bedesten API and converts to Markdown.
    Supports both HTML and PDF content types.
    Use documentId from search_danistay_bedesten results.
    """
    logger.info(f"Tool 'get_danistay_bedesten_document_markdown' called for ID: {documentId}")
    
    if not documentId or not documentId.strip():
        raise ValueError("Document ID must be a non-empty string.")
    
    try:
        return await bedesten_client_instance.get_document_as_markdown(documentId)
    except Exception as e:
        logger.exception("Error in tool 'get_danistay_bedesten_document_markdown'")
        raise

# --- MCP Tools for Bedesten (Yerel Hukuk Mahkemesi Search) ---
@app.tool(
    description="Search Local Civil Courts (Yerel Hukuk Mahkemeleri) decisions using the Bedesten API. This is the primary and only available tool for accessing local court decisions, which represent the first instance of civil litigation in Turkey. Supports advanced search features including date filtering and exact phrase matching for precise legal research.",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_yerel_hukuk_bedesten(
    phrase: str = Field(..., description="""
        Aranacak kavram/kelime. İki farklı arama türü desteklenir:
        • Normal arama: "mülkiyet kararı" - kelimeler ayrı ayrı aranır
        • Tam cümle arama: "\"mülkiyet kararı\"" - tırnak içindeki ifade aynen aranır
        Tam cümle aramalar daha kesin sonuçlar verir.
    """),
    pageSize: int = Field(10, ge=1, le=100, description="Sayfa başına sonuç sayısı"),
    pageNumber: int = Field(1, ge=1, description="Sayfa numarası"),
    kararTarihiStart: Optional[str] = Field(None, description="""
        Decision start date filter (optional). Format: YYYY-MM-DDTHH:MM:SS.000Z
        Example: "2024-01-01T00:00:00.000Z" for decisions from Jan 1, 2024
        Use with kararTarihiEnd for date range filtering
    """),
    kararTarihiEnd: Optional[str] = Field(None, description="""
        Decision end date filter (optional). Format: YYYY-MM-DDTHH:MM:SS.000Z
        Example: "2024-12-31T23:59:59.999Z" for decisions until Dec 31, 2024
        Use with kararTarihiStart for date range filtering
    """)
) -> dict:
    """
    Searches Yerel Hukuk Mahkemesi (Local Civil Court) decisions using Bedesten API.
    This provides access to local court decisions that are not available through other APIs.
    Currently the only available tool for searching Yerel Hukuk Mahkemesi decisions.
    
    Returns a simplified response with decision list and metadata.
    """
    search_data = BedestenSearchData(
        pageSize=pageSize,
        pageNumber=pageNumber,
        itemTypeList=["YERELHUKUK"],  # Local Civil Court decisions
        phrase=phrase,
        kararTarihiStart=kararTarihiStart,
        kararTarihiEnd=kararTarihiEnd
    )
    
    search_request = BedestenSearchRequest(data=search_data)
    
    logger.info(f"Tool 'search_yerel_hukuk_bedesten' called: phrase='{phrase}', dateRange='{kararTarihiStart}' to '{kararTarihiEnd}', page={pageNumber}")
    
    try:
        response = await bedesten_client_instance.search_documents(search_request)
        
        # Return simplified response format
        return {
            "decisions": [d.model_dump() for d in response.data.emsalKararList],
            "total_records": response.data.total,
            "requested_page": pageNumber,
            "page_size": pageSize
        }
    except Exception as e:
        logger.exception("Error in tool 'search_yerel_hukuk_bedesten'")
        raise

@app.tool(
    description="Retrieve a specific local civil court decision document from the Bedesten API and convert it to readable Markdown format. This tool fetches complete local court decision texts using documentId from search results. Perfect for detailed analysis of first-instance civil court rulings.",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def get_yerel_hukuk_bedesten_document_markdown(
    documentId: str = Field(..., description="Document ID from Bedesten search results")
) -> BedestenDocumentMarkdown:
    """
    Retrieves a Yerel Hukuk Mahkemesi decision document from Bedesten API and converts to Markdown.
    Supports both HTML and PDF content types.
    Use documentId from search_yerel_hukuk_bedesten results.
    """
    logger.info(f"Tool 'get_yerel_hukuk_bedesten_document_markdown' called for ID: {documentId}")
    
    if not documentId or not documentId.strip():
        raise ValueError("Document ID must be a non-empty string.")
    
    try:
        return await bedesten_client_instance.get_document_as_markdown(documentId)
    except Exception as e:
        logger.exception("Error in tool 'get_yerel_hukuk_bedesten_document_markdown'")
        raise

# --- MCP Tools for Bedesten (İstinaf Hukuk Mahkemesi Search) ---
@app.tool(
    description="Search Civil Courts of Appeals (İstinaf Hukuk Mahkemeleri) decisions using Bedesten API with advanced filtering options including date range and exact phrase search capabilities",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_istinaf_hukuk_bedesten(
    phrase: str = Field(..., description="""
        Aranacak kavram/kelime. İki farklı arama türü desteklenir:
        • Normal arama: "mülkiyet kararı" - kelimeler ayrı ayrı aranır
        • Tam cümle arama: "\"mülkiyet kararı\"" - tırnak içindeki ifade aynen aranır
        Tam cümle aramalar daha kesin sonuçlar verir.
    """),
    pageSize: int = Field(10, ge=1, le=100, description="Sayfa başına sonuç sayısı"),
    pageNumber: int = Field(1, ge=1, description="Sayfa numarası"),
    kararTarihiStart: Optional[str] = Field(None, description="""
        Decision start date filter (optional). Format: YYYY-MM-DDTHH:MM:SS.000Z
        Example: "2024-01-01T00:00:00.000Z" for decisions from Jan 1, 2024
        Use with kararTarihiEnd for date range filtering
    """),
    kararTarihiEnd: Optional[str] = Field(None, description="""
        Decision end date filter (optional). Format: YYYY-MM-DDTHH:MM:SS.000Z
        Example: "2024-12-31T23:59:59.999Z" for decisions until Dec 31, 2024
        Use with kararTarihiStart for date range filtering
    """)
) -> dict:
    """
    Searches İstinaf Hukuk Mahkemesi (Civil Court of Appeals) decisions using Bedesten API.
    
    İstinaf courts are intermediate appellate courts in the Turkish judicial system that handle
    appeals from local civil courts before cases reach Yargıtay (Court of Cassation).
    This is the only available tool for accessing İstinaf Hukuk Mahkemesi decisions.
    
    Key Features:
    • Date range filtering with ISO 8601 format (YYYY-MM-DDTHH:MM:SS.000Z)
    • Exact phrase search using double quotes: "\"legal term\"" 
    • Regular search for individual keywords
    • Pagination support (1-100 results per page)
    
    Use cases:
    • Research appellate court precedents
    • Track appeals from specific lower courts
    • Find decisions on specific legal issues at appellate level
    • Analyze intermediate court reasoning before supreme court review
    
    Returns structured data with decision metadata including dates, case numbers, and summaries.
    Use get_istinaf_hukuk_bedesten_document_markdown() to retrieve full decision texts.
    """
    search_data = BedestenSearchData(
        pageSize=pageSize,
        pageNumber=pageNumber,
        itemTypeList=["ISTINAFHUKUK"],  # Civil Court of Appeals decisions
        phrase=phrase,
        kararTarihiStart=kararTarihiStart,
        kararTarihiEnd=kararTarihiEnd
    )
    
    search_request = BedestenSearchRequest(data=search_data)
    
    logger.info(f"Tool 'search_istinaf_hukuk_bedesten' called: phrase='{phrase}', dateRange='{kararTarihiStart}' to '{kararTarihiEnd}', page={pageNumber}")
    
    try:
        response = await bedesten_client_instance.search_documents(search_request)
        
        # Return simplified response format
        return {
            "decisions": [d.model_dump() for d in response.data.emsalKararList],
            "total_records": response.data.total,
            "requested_page": pageNumber,
            "page_size": pageSize
        }
    except Exception as e:
        logger.exception("Error in tool 'search_istinaf_hukuk_bedesten'")
        raise

@app.tool(
    description="Retrieve full text of an İstinaf Hukuk Mahkemesi decision document from Bedesten API in Markdown format",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True
    }
)
async def get_istinaf_hukuk_bedesten_document_markdown(
    documentId: str = Field(..., description="Document ID from Bedesten search results")
) -> BedestenDocumentMarkdown:
    """
    Retrieves the full text of an İstinaf Hukuk Mahkemesi decision document in Markdown format.
    
    This tool converts the original decision document (HTML or PDF) from Bedesten API
    into clean, readable Markdown format suitable for analysis and processing.
    
    Input Requirements:
    • documentId: Use the ID from search_istinaf_hukuk_bedesten results
    • Document ID must be non-empty string
    
    Output Format:
    • Clean Markdown text with proper formatting
    • Preserves legal structure (headers, paragraphs, citations)
    • Removes extraneous HTML/PDF artifacts
    
    Use for:
    • Reading full appellate court decision texts
    • Legal analysis of İstinaf court reasoning
    • Citation extraction and reference building
    • Content analysis and summarization
    """
    logger.info(f"Tool 'get_istinaf_hukuk_bedesten_document_markdown' called for ID: {documentId}")
    
    if not documentId or not documentId.strip():
        raise ValueError("Document ID must be a non-empty string.")
    
    try:
        return await bedesten_client_instance.get_document_as_markdown(documentId)
    except Exception as e:
        logger.exception("Error in tool 'get_istinaf_hukuk_bedesten_document_markdown'")
        raise

# --- MCP Tools for Bedesten (Kanun Yararına Bozma Search) ---
@app.tool(
    description="Search Extraordinary Appeal (Kanun Yararına Bozma - KYB) decisions using Bedesten API with date filtering and exact phrase search support",
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
        "idempotentHint": True
    }
)
async def search_kyb_bedesten(
    phrase: str = Field(..., description="""
        Aranacak kavram/kelime. İki farklı arama türü desteklenir:
        • Normal arama: "mülkiyet kararı" - kelimeler ayrı ayrı aranır
        • Tam cümle arama: "\"mülkiyet kararı\"" - tırnak içindeki ifade aynen aranır
        Tam cümle aramalar daha kesin sonuçlar verir.
    """),
    pageSize: int = Field(10, ge=1, le=100, description="Sayfa başına sonuç sayısı"),
    pageNumber: int = Field(1, ge=1, description="Sayfa numarası"),
    kararTarihiStart: Optional[str] = Field(None, description="""
        Decision start date filter (optional). Format: YYYY-MM-DDTHH:MM:SS.000Z
        Example: "2024-01-01T00:00:00.000Z" for decisions from Jan 1, 2024
        Use with kararTarihiEnd for date range filtering
    """),
    kararTarihiEnd: Optional[str] = Field(None, description="""
        Decision end date filter (optional). Format: YYYY-MM-DDTHH:MM:SS.000Z
        Example: "2024-12-31T23:59:59.999Z" for decisions until Dec 31, 2024
        Use with kararTarihiStart for date range filtering
    """)
) -> dict:
    """
    Searches Kanun Yararına Bozma (KYB - Extraordinary Appeal) decisions using Bedesten API.
    
    KYB is an extraordinary legal remedy in the Turkish judicial system where the
    Public Prosecutor's Office can request review of finalized decisions in favor of
    the law and defendants. This is the only available tool for accessing KYB decisions.
    
    Key Features:
    • Date range filtering with ISO 8601 format (YYYY-MM-DDTHH:MM:SS.000Z)
    • Exact phrase search using double quotes: "\"extraordinary appeal\""
    • Regular search for individual keywords
    • Pagination support (1-100 results per page)
    
    Legal Significance:
    • Extraordinary remedy beyond regular appeals
    • Initiated by Public Prosecutor's Office
    • Reviews finalized decisions for legal errors
    • Can benefit defendants retroactively
    • Rare but important legal precedents
    
    Use cases:
    • Research extraordinary appeal precedents
    • Study prosecutorial challenges to final decisions
    • Analyze legal errors in finalized cases
    • Track KYB success rates and patterns
    
    Returns structured data with decision metadata. Use get_kyb_bedesten_document_markdown()
    to retrieve full decision texts for detailed analysis.
    """
    search_data = BedestenSearchData(
        pageSize=pageSize,
        pageNumber=pageNumber,
        itemTypeList=["KYB"],  # Kanun Yararına Bozma decisions
        phrase=phrase,
        kararTarihiStart=kararTarihiStart,
        kararTarihiEnd=kararTarihiEnd
    )
    
    search_request = BedestenSearchRequest(data=search_data)
    
    logger.info(f"Tool 'search_kyb_bedesten' called: phrase='{phrase}', dateRange='{kararTarihiStart}' to '{kararTarihiEnd}', page={pageNumber}")
    
    try:
        response = await bedesten_client_instance.search_documents(search_request)
        
        # Return simplified response format
        return {
            "decisions": [d.model_dump() for d in response.data.emsalKararList],
            "total_records": response.data.total,
            "requested_page": pageNumber,
            "page_size": pageSize
        }
    except Exception as e:
        logger.exception("Error in tool 'search_kyb_bedesten'")
        raise

@app.tool(
    description="Retrieve full text of a Kanun Yararına Bozma (KYB) decision document from Bedesten API in Markdown format",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True
    }
)
async def get_kyb_bedesten_document_markdown(
    documentId: str = Field(..., description="Document ID from Bedesten search results")
) -> BedestenDocumentMarkdown:
    """
    Retrieves the full text of a Kanun Yararına Bozma (KYB) decision document in Markdown format.
    
    This tool converts the original extraordinary appeal decision document (HTML or PDF)
    from Bedesten API into clean, readable Markdown format for analysis.
    
    Input Requirements:
    • documentId: Use the ID from search_kyb_bedesten results
    • Document ID must be non-empty string
    
    Output Format:
    • Clean Markdown text with legal formatting preserved
    • Structured content with headers and citations
    • Removes technical artifacts from source documents
    
    Special Value for KYB Documents:
    • Contains rare extraordinary appeal reasoning
    • Shows prosecutorial arguments for legal review
    • Documents correction of finalized legal errors
    • Provides precedent for similar extraordinary circumstances
    
    Use for:
    • Analyzing extraordinary appeal legal reasoning
    • Understanding prosecutorial review criteria
    • Research on legal error correction mechanisms
    • Studying retroactive benefit applications
    """
    logger.info(f"Tool 'get_kyb_bedesten_document_markdown' called for ID: {documentId}")
    
    if not documentId or not documentId.strip():
        raise ValueError("Document ID must be a non-empty string.")
    
    try:
        return await bedesten_client_instance.get_document_as_markdown(documentId)
    except Exception as e:
        logger.exception("Error in tool 'get_kyb_bedesten_document_markdown'")
        raise

# --- Application Shutdown Handling ---
def perform_cleanup():
    logger.info("MCP Server performing cleanup...")
    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
        if loop.is_closed(): 
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError: 
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    clients_to_close = [
        globals().get('yargitay_client_instance'),
        globals().get('danistay_client_instance'),
        globals().get('emsal_client_instance'),
        globals().get('uyusmazlik_client_instance'),
        globals().get('anayasa_norm_client_instance'),
        globals().get('anayasa_bireysel_client_instance'),
        globals().get('kik_client_instance'),
        globals().get('rekabet_client_instance'),
        globals().get('bedesten_client_instance')
    ]
    async def close_all_clients_async():
        tasks = []
        for client_instance in clients_to_close:
            if client_instance and hasattr(client_instance, 'close_client_session') and callable(client_instance.close_client_session):
                logger.info(f"Scheduling close for client session: {client_instance.__class__.__name__}")
                tasks.append(client_instance.close_client_session())
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    client_name = "Unknown Client"
                    if i < len(clients_to_close) and clients_to_close[i] is not None:
                        client_name = clients_to_close[i].__class__.__name__
                    logger.error(f"Error closing client {client_name}: {result}")
    try:
        if loop.is_running(): 
            asyncio.ensure_future(close_all_clients_async(), loop=loop)
            logger.info("Client cleanup tasks scheduled on running event loop.")
        else:
            loop.run_until_complete(close_all_clients_async())
            logger.info("Client cleanup tasks completed via run_until_complete.")
    except Exception as e: 
        logger.error(f"Error during atexit cleanup execution: {e}", exc_info=True)
    logger.info("MCP Server atexit cleanup process finished.")

atexit.register(perform_cleanup)

def main():
    logger.info(f"Starting {app.name} server via main() function...")
    logger.info(f"Logs will be written to: {LOG_FILE_PATH}")
    try:
        app.run()
    except KeyboardInterrupt: 
        logger.info("Server shut down by user (KeyboardInterrupt).")
    except Exception as e: 
        logger.exception("Server failed to start or crashed.")
    finally:
        logger.info(f"{app.name} server has shut down.")

if __name__ == "__main__": 
    main()