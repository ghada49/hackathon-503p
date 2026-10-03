"""Cheap static packaging checks; scientific and browser checks remain separate."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re

REQUIRED_IDS = frozenset({
    'main', 'concept-title', 'idea', 'why', 'mental-model', 'symbols',
    'controls', 'main-visual', 'intermediates', 'changes', 'explorations',
    'limitations', 'source', 'playground-data',
})


class _ArtifactParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.data = []
        self.in_payload = False
        self.script_count = 0
        self.styles = []
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        identifier = attrs.get('id')
        if identifier:
            if identifier in self.ids:
                raise ValueError('Artifact contains duplicate element IDs')
            self.ids.add(identifier)
        resource_keys = {'src', 'srcset', 'poster', 'data'} if tag in {
            'script', 'img', 'audio', 'video', 'source', 'iframe', 'embed', 'object', 'input',
        } else {'href'} if tag == 'link' else set()
        for key in resource_keys:
            resource = attrs.get(key)
            if resource and not resource.startswith(('data:', '#')):
                raise ValueError('Artifact requires an external resource')
        if tag == 'script':
            self.script_count += 1
            self.in_payload = identifier == 'playground-data' and attrs.get('type') == 'application/json'
        if tag == 'style':
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_payload = False
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if self.in_payload:
            self.data.append(data)
        if self.in_style:
            self.styles.append(data)


def validate_artifact(path: str | Path) -> dict:
    """Reject missing core mounts, invalid embedded JSON, or remote resources.

    Does not execute JavaScript or establish visual presence/scientific fidelity;
    Chromium acceptance tests cover runtime behavior and rendered content.
    User-initiated source hyperlinks are allowed.
    """
    html = Path(path).read_text(encoding='utf-8')
    parser = _ArtifactParser()
    parser.feed(html)
    parser.close()
    if not REQUIRED_IDS <= parser.ids or parser.script_count < 2:
        raise ValueError('Artifact is missing required sections or embedded runtime')
    if re.search(r'@import\s|url\(\s*[\"\x27]?\s*(?:https?:|//)', ''.join(parser.styles), re.I):
        raise ValueError('Artifact requires external styling')

    def reject_constant(value):
        raise ValueError('Artifact contains nonfinite JSON')

    payload = json.loads(''.join(parser.data), parse_constant=reject_constant)
    if not isinstance(payload, dict) or not isinstance(payload.get('ir'), dict):
        raise ValueError('Artifact is missing scientific data')
    if not payload['ir'].get('controls') or not payload['ir'].get('computation', {}).get('nodes'):
        raise ValueError('Artifact is missing controls or computations')
    if payload.get('experience', {}).get('mode') not in {'canonical', 'directed'}:
        raise ValueError('Artifact has no usable presentation plan')
    return {'artifact': 'index.html', 'required_sections': True, 'embedded_data': True,
            'self_contained_resources': True, 'checks': 'static_packaging'}
