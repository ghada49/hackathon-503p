"""Offline-first source adapters extending the authoritative shared source models."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup, Comment, NavigableString
from pydantic import Field, model_validator
from playground.budget import BudgetExceeded, call_with_timeout
from playground.models import Case, SourceBlock, FocusedEvidence, SourceDocument as SharedSourceDocument


class SourceDocument(SharedSourceDocument):
    """Person 1 source preservation metadata extends the shared source envelope."""
    raw_source: str | list[dict[str, Any]] | None = None
    structural_map: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def preserve_raw_source(self):
        if self.raw_source is None:
            self.raw_source = self.raw_text if self.raw_text is not None else [b.model_dump() for b in self.blocks]
        return self


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


def _math_text(tag) -> tuple[str, bool]:
    """Small bounded presentation-MathML adapter, retaining unknown text conservatively."""
    faithful = True
    visited = 0

    def render(node, depth=0):
        nonlocal faithful, visited
        visited += 1
        if isinstance(node, Comment):
            return ''
        if isinstance(node, NavigableString):
            return str(node).strip()
        if depth > 32 or visited > 1000:
            faithful = False
            return node.get_text(' ', strip=True)
        if node.name in ('math', 'semantics'):
            for annotation in node.find_all('annotation', recursive=False):
                if re.search(r'(?:tex|latex)', str(annotation.get('encoding', '')), re.I):
                    value = annotation.get_text().strip()
                    if value:
                        return value
        children = [child for child in node.children if not isinstance(child, Comment)
                    and (not isinstance(child, NavigableString) or str(child).strip())]
        name = node.name
        if name in ('mi', 'mn', 'mo', 'mtext', 'ms'):
            return node.get_text(' ', strip=True)
        values = [render(child, depth + 1) for child in children]
        base = values[0] if values else ''
        if children and not isinstance(children[0], NavigableString) and children[0].name not in ('mi', 'mn', 'mo', 'mtext', 'ms'):
            base = f'({base})'
        if name == 'mfrac' and len(values) == 2:
            return f'({values[0]})/({values[1]})'
        if name in ('msup', 'msub') and len(values) == 2:
            return f'{base}{"^" if name == "msup" else "_"}({values[1]})'
        if name == 'msubsup' and len(values) == 3:
            return f'{base}_({values[1]})^({values[2]})'
        if name == 'msqrt' and values:
            return f'sqrt({" ".join(values)})'
        if name == 'mroot' and len(values) == 2:
            return f'root({values[0]},{values[1]})'
        if name not in ('math', 'mrow', 'semantics', 'mstyle'):
            faithful = False
        return ' '.join(value for value in values if value)

    return render(tag), faithful


def _html_blocks(text: str, *, metadata: dict | None = None) -> list[SourceBlock]:
    soup = BeautifulSoup(text, 'html.parser')
    # MathJax's TeX script tags carry scientific text, not executable instructions.
    for script in soup.find_all('script'):
        if str(script.get('type', '')).lower().startswith('math/tex'):
            equation = soup.new_tag('math')
            equation.string = str(script.string or script.get_text())
            script.replace_with(equation)
    for tag in soup(['script', 'style', 'nav']):
        tag.decompose()
    faithful = True
    for math in soup.find_all('math'):
        if math.find_parent('math'):
            continue
        value, supported = _math_text(math)
        faithful = faithful and supported
        math.clear()
        math.string = value
    if metadata is not None:
        metadata.update(extraction_faithful=faithful, representation='html_scientific_text')
    names = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre', 'table', 'ul', 'ol', 'figcaption'}

    def is_equation(tag):
        return tag.name == 'math' or any(re.search(r'equation|formula|math-display', str(cls), re.I) for cls in tag.get('class', []))

    def selected(tag):
        return tag.name in names or is_equation(tag)

    items = []
    pending = []

    def flush():
        value = ' '.join(pending).strip()
        pending.clear()
        if value:
            items.append(dict(type='paragraph', text=value))

    def walk(node):
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            value = str(node).strip()
            if value:
                pending.append(value)
            return
        if selected(node):
            flush()
            kind = ('equation' if is_equation(node) else 'heading' if node.name.startswith('h') else
                    {'pre': 'algorithm', 'table': 'table', 'ul': 'list', 'ol': 'list', 'figcaption': 'caption'}.get(node.name, 'paragraph'))
            items.append(dict(type=kind, text=node.get_text(' ', strip=True)))
            return
        for child in node.children:
            walk(child)

    walk(soup.body or soup)
    flush()
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
                metadata = {}
                blocks = _html_blocks(text, metadata=metadata)
                return SourceDocument(source_url=case.source_url, raw_text=text, blocks=blocks, metadata=metadata, origin='local')
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
                metadata = {}
                blocks = _html_blocks(text, metadata=metadata)
                return SourceDocument(source_url=case.source_url, raw_text=text, blocks=blocks, metadata=metadata, origin='url')
            return SourceDocument(source_url=case.source_url, raw_text=text, origin='url')
        except (requests.RequestException, UnicodeError, BudgetExceeded) as exc:
            raise SourceUnavailable('Source URL could not be fetched') from exc
    raise SourceUnavailable('Supply excerpt/source_text/content/paper_excerpt or source_path; URL fetching is disabled unless configured')


def normalize_source(document: SourceDocument) -> list[SourceBlock]:
    supplied_blocks = bool(document.blocks)
    if document.blocks:
        blocks = sorted(_blocks(document.blocks), key=lambda b: b.order)
    else:
        items = []
        pending = []
        fence = None

        def flush(kind=None):
            part = '\n'.join(pending).strip()
            pending.clear()
            if not part:
                return
            kind = kind or ('equation' if part.startswith(('$$', '\\[')) else
                            'list' if re.match(r'^(?:[-*+] |\d+\. )', part) else
                            'table' if part.startswith('|') else
                            'caption' if re.match(r'^(?:Figure|Table)\s+\d+', part) else 'paragraph')
            items.append(dict(type=kind, text=part))

        for line in (document.raw_text or '').replace('\r\n', '\n').splitlines():
            if fence:
                pending.append(line)
                if re.fullmatch(r'\s{0,3}' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}\s*', line):
                    flush('algorithm')
                    fence = None
                continue
            opener = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
            heading = re.match(r'^\s{0,3}#{1,6}\s+(.+)', line)
            if opener:
                flush()
                fence = opener.group(1)
                pending.append(line)
            elif heading:
                flush()
                items.append(dict(type='heading', text=heading.group(1)))
            elif not line.strip():
                flush()
            else:
                pending.append(line)
        flush('algorithm' if fence else None)
        blocks = _blocks(items)
    section = None
    section_number = None
    normalized = []
    def section_label(value):
        return re.sub(r'^(?:Section\s+)?\d+(?:\.\d+)*[.)]?\s+', '', value, flags=re.I).strip().casefold()

    for i, block in enumerate(blocks):
        if block.type == 'heading':
            section = block.section or block.text
            match = re.match(r'^(?:Section\s+)?(\d+(?:\.\d+)*)[.)]?\s+\S', block.text, re.I)
            section_number = block.section_number or (match.group(1) if match else None)
        label = block.section or section
        if section and label and section_label(label) == section_label(section):
            label = section
        normalized.append(block.model_copy(update={'id': f'b{i:04d}', 'text': block.text.strip(),
            'section': label, 'section_number': block.section_number or section_number}))
    if not normalized:
        raise SourceUnavailable('Source contains no nonempty blocks')
    document.blocks = normalized
    if supplied_blocks and document.raw_text and document.metadata.get('representation') != 'html_scientific_text':
        raw_prose = re.sub(r'(?m)^\s{0,3}#{1,6}\s+', '', document.raw_text)
        represented = ' '.join(block.text for block in normalized)
        faithful = ' '.join(raw_prose.split()) == ' '.join(represented.split())
        document.metadata['extraction_faithful'] = faithful and document.metadata.get('extraction_faithful', True)
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
