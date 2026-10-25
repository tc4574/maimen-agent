"""Read private local settings without exporting values to clients or logs."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def settings():
    values = {}
    for filename in ('.env', '.env.deepseek'):
        path = ROOT / filename
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                key, sep, value = line.partition('=')
                if sep and not key.strip().startswith('#'):
                    values[key.strip()] = value.strip().strip('\"\'')
    values.update(os.environ)
    return values


def model_config():
    values = settings()
    return {
        'key': values.get('DEEPSEEK_API_KEY', '').strip(),
        'base_url': values.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/'),
        'model': values.get('DEEPSEEK_MODEL', 'deepseek-flash'),
    }
