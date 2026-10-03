"""Offline-first source adapters; compatibility types mirror spec sections 27–30."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, model_validator
from playground.budget import BudgetExceeded, call_with_timeout


class Case(BaseModel):
    source_url: str
    focus: str
    audience: str
    model_config = ConfigDict(extra='allow', strict=True)


class SourceBlock(BaseModel):
    id: str
    type: Literal['heading', 'paragraph', 'equation', 'algorithm', 'table', 'list', 'caption']
    text: str
    section: str | None = None
    section_number: str | None = None
    equation_number: str | None = None
    page: int | None = None
    order: int


class SourceDocument(BaseModel):
    source_url: str
    title: str | None = None
    raw_text: str | None = None
    blocks: list[SourceBlock] = Field(default_factory=list)
    origin: Literal['supplied', 'local', 'url']
    raw_source: str | list[dict[str, Any]] | None = None
    structural_map: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def preserve_raw_source(self):
        if self.raw_source is None:
            self.raw_source = self.raw_text if self.raw_text is not None else [b.model_dump() for b in self.blocks]
        return self


class FocusedEvidence(BaseModel):
    blocks: list[SourceBlock]
    focus: str
    audience: str


class SourceUnavailable(ValueError):
    """No readable scientific source was supplied or permitted."""


def load_case(path: str | Path) -> Case:
    return Case.model_validate(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def _blocks(items: list[Any]) -> list[SourceBlock]:
    result = []
    for i, item in enumerate(items):
        data = item.model_dump() if hasattr(item, 'model_dump') else dict(item)
        if not str(data.get('text', '')).strip():
            continue
        data.setdefault('id', f'b{i:04d}')
        data.setdefault('order', i)
        result.append(SourceBlock.model_validate(data))
    return result


def _html_blocks(text: str) -> list[SourceBlock]:
    soup = BeautifulSoup(text, 'html.parser')
    # MathJax's TeX script tags carry scientific text, not executable instructions.
    for script in soup.find_all('script'):
        if str(script.get('type', '')).lower().startswith('math/tex'):
            equation = soup.new_tag('math')
            equation.string = str(script.string or script.get_text())
            script.replace_with(equation)
    for tag in soup(['script', 'style', 'nav']):
        tag.decompose()
    names = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre', 'table', 'ul', 'ol', 'figcaption'}

    def is_equation(tag):
        return tag.name == 'math' or any(re.search(r'equation|formula|math-display', str(cls), re.I) for cls in tag.get('class', []))

    def selected(tag):
        return tag.name in names or is_equation(tag)

    items = []
    for tag in soup.find_all(selected):
        if any(selected(parent) for parent in tag.parents if parent.name != '[document]'):
            continue
        kind = ('equation' if is_equation(tag) else 'heading' if tag.name.startswith('h') else
                {'pre': 'algorithm', 'table': 'table', 'ul': 'list', 'ol': 'list', 'figcaption': 'caption'}.get(tag.name, 'paragraph'))
        items.append(dict(type=kind, text=tag.get_text(' ', strip=True)))
    if not items:
        items = [dict(type='paragraph', text=soup.get_text(' ', strip=True))]
    return _blocks(items)


def resolve_source(case: Case, *, base_dir: str | Path = '.', allow_url: bool = False,
                   fetch=None, timeout: float = 20, max_bytes: int = 5_000_000) -> SourceDocument:
    fields = case.model_dump()
    for name in ('excerpt', 'source_text', 'content', 'paper_excerpt'):
        value = fields.get(name)
        if isinstance(value, str) and value.strip():
            return SourceDocument(source_url=case.source_url, raw_text=value, origin='supplied')
        if isinstance(value, dict) and isinstance(value.get('blocks'), list):
            blocks = _blocks(value['blocks'])
            if blocks:
                return SourceDocument(source_url=case.source_url, title=value.get('title'), blocks=blocks,
                    raw_source=value['blocks'], raw_text=value.get('raw_text'), metadata=value.get('metadata', {}), origin='supplied')
    if isinstance(fields.get('source_blocks'), list):
        blocks = _blocks(fields['source_blocks'])
        if blocks:
            return SourceDocument(source_url=case.source_url, blocks=blocks, raw_source=fields['source_blocks'], origin='supplied')
    parsed = urlparse(case.source_url)
    local = fields.get('source_path') or fields.get('local_source_path')
    if not local and parsed.scheme == 'file':
        local = unquote(parsed.path).lstrip('/') if re.match(r'^/[A-Za-z]:', parsed.path) else unquote(parsed.path)
    if not local and parsed.scheme not in ('https', 'http', 'file'):
        possible = Path(base_dir) / case.source_url
        if possible.is_file():
            local = case.source_url
    if local:
        path = Path(local)
        if not path.is_absolute():
            path = Path(base_dir) / path
        try:
            if path.stat().st_size > max_bytes:
                raise SourceUnavailable('Local source exceeds size limit')
            if path.suffix.lower() == '.pdf':
                raise SourceUnavailable('PDF extraction is not configured; supply text or SourceBlocks')
            text = path.read_text(encoding='utf-8-sig')
            if not text.strip():
                raise SourceUnavailable('Local source is empty')
            if path.suffix.lower() in ('.html', '.htm'):
                return SourceDocument(source_url=case.source_url, raw_text=text, blocks=_html_blocks(text), origin='local')
            return SourceDocument(source_url=case.source_url, raw_text=text, origin='local')
        except (OSError, UnicodeError) as exc:
            raise SourceUnavailable('Local source could not be read') from exc
    if allow_url and parsed.scheme in ('https', 'http'):
        try:
            def download():
                response = (fetch or requests.get)(case.source_url, timeout=timeout, stream=True)
                try:
                    if response.status_code != 200:
                        raise SourceUnavailable(f'Source fetch returned HTTP {response.status_code}')
                    if hasattr(response, 'iter_content'):
                        chunks = []
                        size = 0
                        for chunk in response.iter_content(chunk_size=8192):
                            size += len(chunk)
                            if size > max_bytes:
                                raise SourceUnavailable('Fetched source exceeds size limit')
                            chunks.append(chunk)
                        content = b''.join(chunks)
                    else:
                        content = response.content
                        if len(content) > max_bytes:
                            raise SourceUnavailable('Fetched source exceeds size limit')
                    return content, response.encoding, response.headers
                finally:
                    if hasattr(response, 'close'):
                        response.close()
            content, encoding, headers = call_with_timeout(download, timeout)
            if content.startswith(b'%PDF'):
                raise SourceUnavailable('PDF extraction is not configured; supply text or SourceBlocks')
            text = content.decode(encoding or 'utf-8')
            if not text.strip():
                raise SourceUnavailable('Fetched source is empty')
            if 'html' in headers.get('Content-Type', '').lower():
                return SourceDocument(source_url=case.source_url, raw_text=text, blocks=_html_blocks(text), origin='url')
            return SourceDocument(source_url=case.source_url, raw_text=text, origin='url')
        except (requests.RequestException, UnicodeError, BudgetExceeded) as exc:
            raise SourceUnavailable('Source URL could not be fetched') from exc
    raise SourceUnavailable('Supply excerpt/source_text/content/paper_excerpt or source_path; URL fetching is disabled unless configured')


def normalize_source(document: SourceDocument) -> list[SourceBlock]:
    if document.blocks:
        blocks = sorted(_blocks(document.blocks), key=lambda b: b.order)
    else:
        parts = re.split(r'\n\s*\n', (document.raw_text or '').replace('\r\n', '\n'))
        items = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Split Markdown headings from immediately following prose.
            lines = part.splitlines()
            if re.match(r'^#{1,6}\s+', lines[0]):
                items.append(dict(type='heading', text=re.sub(r'^#{1,6}\s+', '', lines[0])))
                part = '\n'.join(lines[1:]).strip()
                if not part:
                    continue
            kind = ('algorithm' if part.startswith('```') else
                    'equation' if part.startswith(('$$', '\\[')) else
                    'list' if re.match(r'^(?:[-*+] |\d+\. )', part) else
                    'table' if part.startswith('|') else
                    'caption' if re.match(r'^(?:Figure|Table)\s+\d+', part) else 'paragraph')
            items.append(dict(type=kind, text=part))
        blocks = _blocks(items)
    section = None
    section_number = None
    normalized = []
    for i, block in enumerate(blocks):
        if block.type == 'heading':
            section = block.text
            match = re.match(r'^(?:Section\s+)?(\d+(?:\.\d+)*)[.)]?\s+\S', block.text, re.I)
            section_number = block.section_number or (match.group(1) if match else None)
        normalized.append(block.model_copy(update={'id': f'b{i:04d}', 'text': block.text.strip(),
            'section': block.section or section, 'section_number': block.section_number or section_number}))
    if not normalized:
        raise SourceUnavailable('Source contains no nonempty blocks')
    document.blocks = normalized
    document.structural_map = build_structural_map(normalized)
    return normalized


def build_structural_map(blocks: list[SourceBlock]) -> dict[str, Any]:
    """An index of original regions and explicit numbered references, not a summary."""
    sections = []
    equations = {}
    algorithms = {}
    definitions = {}
    current = None
    for block in blocks:
        if (current is None or block.type == 'heading' or
                block.section and block.section != current['title']):
            current = dict(id=block.id, title=block.section or '', section_number=block.section_number,
                           page=block.page, block_ids=[])
            sections.append(current)
        current['block_ids'].append(block.id)
        if block.equation_number:
            equations[str(block.equation_number)] = block.id
        elif block.type == 'equation':
            match = re.search(r'^(?:Eq\.?|Equation)\s*\(?([0-9]+(?:\.[0-9]+)*)\)?|\(([0-9]+)\)\s*$', block.text, re.I)
            if match:
                equations[match.group(1) or match.group(2)] = block.id
        if block.type == 'algorithm':
            match = re.search(r'Algorithm\s+([0-9]+)', block.text, re.I)
            if match:
                algorithms[match.group(1)] = block.id
        for match in re.finditer(r'\b(?:where\s+(\w+)\s+denotes|we\s+define\s+(\w+)|let\s+(\w+)\s+be)\b', block.text, re.I):
            symbol = next(group for group in match.groups() if group).lower()
            definitions.setdefault(symbol, []).append(block.id)
    return dict(sections=sections, equations=equations, algorithms=algorithms,
                definitions=definitions, block_order=[b.id for b in blocks])
