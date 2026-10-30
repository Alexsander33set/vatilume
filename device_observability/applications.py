"""Conservative local application labels from stat names and sampled parent links.

This is identification by a published rule, not executable authentication. No
argv, executable paths, desktop files, environment or network lookup is used.
Only retained process rows are summed; application totals remain unknown.
"""
from __future__ import annotations

CATALOG_VERSION = 1
MAX_ANCESTORS = 16
# Exact comm-name rules; never infer an application from a generic helper alone.
CATALOG = {
    'aces': ('war-thunder', 'War Thunder'),
    'zen': ('zen', 'Zen Browser'),
    'firefox': ('firefox', 'Mozilla Firefox'),
    'firefox-bin': ('firefox', 'Mozilla Firefox'),
    'chrome': ('chrome', 'Google Chrome'),
    'chromium': ('chromium', 'Chromium'),
    'chromium-browse': ('chromium', 'Chromium'),
    'chatgpt': ('chatgpt-codex', 'ChatGPT / Codex'),
    'steam': ('steam', 'Steam'),
    'steamwebhelper': ('steam', 'Steam'),
    'gameoverlayui': ('steam', 'Steam'),
    'insync': ('insync', 'Insync'),
    'zapzap': ('zapzap', 'ZapZap'),
    'discord': ('discord', 'Discord'),
    'code': ('vscode', 'Visual Studio Code'),
    'code-insiders': ('vscode-insiders', 'Visual Studio Code Insiders'),
    'kitty': ('kitty', 'Kitty'),
    'nautilus': ('files', 'Arquivos (GNOME)'),
    'obs': ('obs', 'OBS Studio'),
    'gnome-shell': ('gnome-shell', 'Área de trabalho (GNOME)'),
}
HELPERS = frozenset(name.casefold() for name in (
    'Isolated Web Co', 'Web Content', 'Privileged Cont', 'WebExtensions',
    'Socket Process', 'RDD Process', 'Utility Process', 'QtWebEngineProc',
    'chrome_crashpad', 'crashpad_handler'))
WRAPPERS = frozenset(('bwrap', 'srt-bwrap', 'zypak-helper', 'zypak-sandbox', 'forkserver'))
METHODS = {'name_rule': 'Regra de nome', 'parent_rule': 'Auxiliar ligado por parentesco',
           'unidentified': 'Aplicativo não identificado'}


def capture_ancestors(entry, rows):
    """Snapshot only needed parent metadata, using the already-read stat rows."""
    if entry['name'].casefold() not in HELPERS:
        return []
    chain, seen, current = [], {entry['pid']}, entry
    for _ in range(MAX_ANCESTORS):
        parent = rows.get(current.get('ppid'))
        if not parent or parent['pid'] in seen or parent['start_ticks'] > current['start_ticks']:
            break
        seen.add(parent['pid'])
        chain.append({k: parent[k] for k in ('pid', 'ppid', 'start_ticks', 'name')})
        name = parent['name'].casefold()
        if name in CATALOG or name not in HELPERS | WRAPPERS:
            break
        current = parent
    return chain


def identify(entry):
    """Rebuild the label locally; stored labels can never invent an app name."""
    direct = CATALOG.get(entry['name'].casefold())
    if direct:
        return {'id': 'app:'+direct[0], 'name': direct[1], 'method': 'name_rule',
                'recognized': True, 'catalog_version': CATALOG_VERSION}
    if entry['name'].casefold() in HELPERS:
        current, seen = entry, {entry['pid']}
        for parent in entry.get('ancestors', [])[:MAX_ANCESTORS]:
            if (type(parent.get('pid')) is not int or type(parent.get('start_ticks')) is not int
                or not isinstance(parent.get('name'), str) or parent['pid'] in seen
                or parent['pid'] != current.get('ppid') or parent['start_ticks'] > current['start_ticks']):
                break
            seen.add(parent['pid'])
            name = parent['name'].casefold()
            known = CATALOG.get(name)
            # A desktop shell launches unrelated applications; never adopt them.
            if known and name != 'gnome-shell':
                return {'id': 'app:'+known[0], 'name': known[1], 'method': 'parent_rule',
                        'recognized': True, 'catalog_version': CATALOG_VERSION}
            if name not in HELPERS | WRAPPERS:
                break
            current = parent
    return {'id': f"process:{entry['pid']}:{entry['start_ticks']}", 'name': entry['name'],
            'method': 'unidentified', 'recognized': False, 'catalog_version': CATALOG_VERSION}


def group_entries(entries):
    groups = {}
    seen = set()
    for entry in entries[:20]:
        identity = (entry['pid'], entry['start_ticks'])
        if identity in seen:
            continue
        seen.add(identity)
        app = identify(entry)
        group = groups.setdefault(app['id'], {**app, 'cpu_percent': None, 'rss_bytes': 0,
            'observed_processes': 0, 'cpu_known_processes': 0, 'methods': [], 'entries': [],
            'members_only': True})
        group['observed_processes'] += 1
        group['rss_bytes'] += entry['rss_bytes']
        if entry['cpu_percent'] is not None:
            group['cpu_percent'] = (group['cpu_percent'] or 0) + entry['cpu_percent']
            group['cpu_known_processes'] += 1
        if app['method'] not in group['methods']:
            group['methods'].append(app['method'])
        group['entries'].append({**entry, 'application': app})
    return sorted(groups.values(), key=lambda group: (-(group['cpu_percent'] if group['cpu_percent'] is not None else -1), -group['rss_bytes'], group['id']))
