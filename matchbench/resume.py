import re
from io import BytesIO
from pathlib import Path
from typing import NoReturn
from zipfile import BadZipFile, ZipFile

from docx import Document
from pypdf import PdfReader

from .schemas import Evidence, Profile

SKILLS = (
    "FastAPI", "Python", "PostgreSQL", "SQL", "Docker", "Kubernetes", "React", "TypeScript", "JavaScript",
    "AWS", "pytest", "Alembic", "SQLAlchemy", "pgvector", "BM25", "LLM agents", "semantic search",
    "embeddings", "Linux", "Java", "Go", "Redis", "Pydantic", "Git", "ETL",
)
ALIASES = {"LLM agents": r"llm agents?|tool.calling|agentic applications?", "PostgreSQL": r"postgres(?:ql)?"}
HEADINGS = {
    "education": "education", "experience": "experience", "work experience": "experience",
    "employment": "experience", "projects": "projects", "selected projects": "projects",
    "skills": "skills", "technical skills": "skills", "interests": "interests", "summary": "summary",
    "certifications": "certifications", "activities": "activities",
}


def invalid(text: str) -> NoReturn:
    raise ValueError(text)


def extract_document(filename: str, data: bytes, maximum: int) -> list[tuple[str, str]]:
    if not data or len(data) > maximum:
        invalid(f"Upload a document smaller than {maximum // (1024 * 1024)} MB.")
    suffix = Path(filename).suffix.lower()
    stream = BytesIO(data)
    if suffix == ".pdf" and data.startswith(b"%PDF-"):
        try:
            reader = PdfReader(stream)
            if reader.is_encrypted or len(reader.pages) > 25:
                invalid("Use an unlocked PDF with at most 25 pages.")
            sections = [(f"PDF page {i}", page.extract_text() or "") for i, page in enumerate(reader.pages, 1)]
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("PDF extraction failed. Export a text-based PDF or paste résumé text.") from exc
    elif suffix == ".docx" and data.startswith(b"PK"):
        try:
            with ZipFile(stream) as archive:
                if sum(entry.file_size for entry in archive.infolist()) > 20_000_000:
                    invalid("The Word document expands beyond the extraction limit.")
                if "word/document.xml" not in archive.namelist():
                    invalid("Select a valid Word .docx document.")
            stream.seek(0)
            document = Document(stream)
            paragraphs = [item.text for item in document.paragraphs]
            paragraphs.extend(cell.text for table in document.tables for row in table.rows for cell in row.cells)
            sections = [("Word document", "\n".join(paragraphs))]
        except (BadZipFile, KeyError) as exc:
            raise ValueError("Select a valid Word .docx document.") from exc
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Word document could not be read. Paste résumé text instead.") from exc
    elif suffix == ".txt" and b"\x00" not in data:
        try:
            sections = [("Text résumé", data.decode("utf-8-sig"))]
        except UnicodeDecodeError as exc:
            raise ValueError("Use UTF-8 for plain text uploads.") from exc
    else:
        invalid("Upload a PDF, DOCX or UTF-8 text document.")
    if not any(content.strip() for _, content in sections):
        invalid("No text was extracted. Use a text-based document or paste the résumé.")
    if sum(len(content) for _, content in sections) > 100_000:
        invalid("The extracted text exceeds 100,000 characters.")
    return sections


def parse_profile(sources: list[tuple[str, str]]) -> Profile:
    facts: dict[str, list[str]] = {"education": [], "experience": [], "projects": []}
    section = "summary"
    evidence: dict[str, Evidence] = {}
    graduation = None
    for source, content in sources:
        for number, line in enumerate(content.splitlines(), 1):
            line = re.sub(r"\s+", " ", line).strip(" •\t")
            if not line:
                continue
            heading = HEADINGS.get(line.casefold().rstrip(":"))
            if heading:
                section = heading
                continue
            if section in facts and len(facts[section]) < (30 if section == "education" else 50):
                facts[section].append(line[:1000])
            if section == "education":
                match = re.search(r"(?i)(?:graduat(?:ion|ing|e[ds]?)|expected)[^\d]{0,28}(20\d{2})", line)
                if match:
                    graduation = int(match[1])
            if section == "interests" or re.search(r"(?i)\b(interested in|learning|want to learn|aspiring)\b", line):
                continue
            for skill in SKILLS:
                pattern = ALIASES.get(skill, re.escape(skill))
                if skill not in evidence and re.search(rf"(?i)(?<![\w])(?:{pattern})(?![\w])", line):
                    evidence[skill] = Evidence(
                        id=f"parsed-{len(evidence) + 1}", skill=skill, excerpt=line[:600],
                        source=f"{source}, line {number}", method="parser", review="pending",
                    )
    return Profile(
        education=facts["education"], experience=facts["experience"], projects=facts["projects"],
        evidence=list(evidence.values()), graduation_year=graduation,
    )
