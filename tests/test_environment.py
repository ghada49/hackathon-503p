from pathlib import Path
import subprocess


def test_env_files_ignored_but_example_available():
    root = Path(__file__).resolve().parents[1]
    command = ['git', '-c', f'safe.directory={root.as_posix()}', 'check-ignore', '--no-index', '--stdin']
    result = subprocess.run(command, input=b'.env\n.env.test\n.env.example\n', capture_output=True, cwd=root)
    assert result.returncode == 0
    assert set(result.stdout.decode().splitlines()) == {'.env', '.env.test'}


def test_example_contains_empty_key_only():
    # Inspect only the intentionally public template, never the real secret file.
    example = Path(__file__).resolve().parents[1] / '.env.example'
    assert example.read_text(encoding='utf-8') == 'OPENROUTER_API_KEY=\n'
