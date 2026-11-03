"""
Client for the cloudrevel-lab/collig-personas market.

The market is data-only: index.json plus Markdown/JSON dossiers.  Installation
never executes remote content.  Every downloaded file is checked against the
SHA-256 in index.json, size-capped, parsed and scanned for obvious credentials
before it is moved into ~/.collig/personalities/<slug>/.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

DEFAULT_REPO = "cloudrevel-lab/collig-personas"
DEFAULT_REF = "main"

REQUIRED_FILES = ("PERSONALITY.md", "meta.json")
ALLOWED_FILES = {"PERSONALITY.md", "meta.json", "sources.md"}
MAX_BYTES = {
    "PERSONALITY.md": 512 * 1024,
    "meta.json": 128 * 1024,
    "sources.md": 1024 * 1024,
}
MAX_TOTAL = 2 * 1024 * 1024
MAX_PERSONAS = 500

SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)


class MarketError(RuntimeError):
    """The market is unreachable or a persona cannot be installed safely."""


def _safe_slug(slug: Any) -> str:
    text = str(slug or "")
    if not text or text in {".", ".."} or text.startswith("."):
        raise MarketError("invalid persona slug")
    if len(text) > 80 or "/" in text or "\\" in text:
        raise MarketError("invalid persona slug")
    if any(ord(char) < 32 for char in text) or text != text.strip():
        raise MarketError("invalid persona slug")
    return text


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _secret_hits(text: str) -> List[str]:
    return [name for name, pattern in SECRET_PATTERNS if pattern.search(text)]


def _validate_catalog(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MarketError("market index is not a JSON object")
    personas = payload.get("personas")
    if not isinstance(personas, list) or not personas:
        raise MarketError("market index has no personas")
    if len(personas) > MAX_PERSONAS:
        raise MarketError("market index is too large")
    seen = set()
    for entry in personas:
        if not isinstance(entry, dict):
            raise MarketError("market entry is not an object")
        slug = _safe_slug(entry.get("slug"))
        if slug in seen:
            raise MarketError("market index contains duplicate slug " + slug)
        seen.add(slug)
        files = entry.get("files")
        if not isinstance(files, dict) or not files:
            raise MarketError("market entry has no file checksums: " + slug)
        for name, digest in files.items():
            if name not in ALLOWED_FILES:
                raise MarketError("market entry has unexpected file " + str(name))
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise MarketError("market entry has invalid checksum for " + slug + "/" + str(name))
        if "meta.json" not in files or "PERSONALITY.md" not in files:
            raise MarketError("market entry is missing required files: " + slug)
        if entry.get("updated_at") is not None and not isinstance(entry.get("updated_at"), str):
            raise MarketError("market entry has invalid updated_at: " + slug)
    return payload


class PersonaMarket:
    def __init__(
        self,
        repo: str = DEFAULT_REPO,
        ref: str = DEFAULT_REF,
        *,
        root: Optional[Path | str] = None,
        cache_path: Optional[Path | str] = None,
        fetch: Optional[Callable[[str], bytes]] = None,
        timeout: int = 15,
        manager: Any = None,
    ):
        self.repo = (repo or DEFAULT_REPO).strip()
        self.ref = (ref or DEFAULT_REF).strip()
        if root is None:
            from core.paths import paths

            root = os.path.join(paths.home, "personalities")
        self.root = Path(root)
        if cache_path is None:
            from core.paths import paths

            cache_path = os.path.join(paths.home, "personas-market", "index.json")
        self.cache_path = Path(cache_path)
        self.timeout = timeout
        self._fetch = fetch or self._http_fetch
        self._manager = manager
        self.last_error = ""
        self.used_cache = False

    # ------------------------------------------------------------------
    # fetching / cache
    # ------------------------------------------------------------------
    @property
    def index_url(self) -> str:
        return f"https://raw.githubusercontent.com/{self.repo}/{self.ref}/index.json"

    def raw_url(self, relative: str) -> str:
        return f"https://raw.githubusercontent.com/{self.repo}/{self.ref}/" + relative.lstrip("/")

    def _http_fetch(self, url: str) -> bytes:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise MarketError("requests is not installed") from exc
        response = requests.get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": "collig-persona-market/1.0"},
        )
        if response.status_code != 200:
            raise MarketError(f"GitHub returned HTTP {response.status_code} for {url}")
        if len(response.content) > MAX_TOTAL:
            raise MarketError("market response is too large")
        return response.content

    def _read_cache(self) -> Optional[Dict[str, Any]]:
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or raw.get("repo") != self.repo or raw.get("ref") != self.ref:
            return None
        index = raw.get("index")
        try:
            return _validate_catalog(index)
        except MarketError:
            return None

    def _write_cache(self, index: Dict[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(
                    {
                        "repo": self.repo,
                        "ref": self.ref,
                        "fetched_at": time.time(),
                        "index": index,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def cached_catalog(self) -> Optional[Dict[str, Any]]:
        return self._read_cache()

    def catalog(self, refresh: bool = False) -> Dict[str, Any]:
        self.last_error = ""
        self.used_cache = False
        if not refresh:
            cached = self._read_cache()
            if cached is not None:
                return cached
        try:
            raw = self._fetch(self.index_url)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise MarketError("market index is not valid JSON") from exc
            index = _validate_catalog(payload)
            self._write_cache(index)
            return index
        except Exception as exc:
            cached = self._read_cache()
            if cached is not None:
                self.last_error = str(exc)
                self.used_cache = True
                return cached
            if isinstance(exc, MarketError):
                raise
            raise MarketError(f"could not fetch {self.index_url}: {exc}") from exc

    # ------------------------------------------------------------------
    # listing / resolution
    # ------------------------------------------------------------------
    def _local(self) -> Dict[str, Dict[str, Any]]:
        try:
            if self._manager is not None:
                return {str(item.get("slug")): item for item in self._manager.list()}
            from core.personality import get_personality_manager

            return {str(item.get("slug")): item for item in get_personality_manager().list()}
        except Exception:
            return {}

    def _local_current(self, slug: str, files: Dict[str, str]) -> bool:
        folder = self.root / slug
        if not folder.is_dir():
            return False
        for name, expected in files.items():
            path = folder / name
            try:
                if not path.is_file() or _sha256(path.read_bytes()) != expected:
                    return False
            except OSError:
                return False
        return True

    def list_personas(self, refresh: bool = False) -> List[Dict[str, Any]]:
        catalog = self.catalog(refresh=refresh)
        local = self._local()
        output = []
        for position, entry in enumerate(catalog.get("personas") or [], 1):
            slug = _safe_slug(entry.get("slug"))
            installed = slug in local
            current = installed and self._local_current(slug, entry.get("files") or {})
            output.append(
                {
                    **entry,
                    "number": position,
                    "installed": installed,
                    "update_available": bool(installed and not current),
                    "current": bool(current),
                    "local_path": str(self.root / slug),
                }
            )
        return output

    def resolve(self, selector: str, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if catalog is None:
            catalog = self.catalog()
        entries = catalog.get("personas") or []
        text = str(selector or "").strip()
        if not text:
            raise MarketError("choose a persona by number or name")
        if text.isdigit():
            number = int(text)
            if 1 <= number <= len(entries):
                return entries[number - 1]
            raise MarketError("there is no persona number " + text)

        lowered = text.casefold()
        exact = []
        for entry in entries:
            values = [entry.get("slug"), entry.get("name"), entry.get("display_name"), entry.get("canonical_name")]
            aliases = entry.get("aliases")
            if isinstance(aliases, list):
                values.extend(aliases)
            if any(str(value or "").strip().casefold() == lowered for value in values if value):
                exact.append(entry)
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            names = ", ".join(str(item.get("display_name") or item.get("name")) for item in exact)
            raise MarketError("ambiguous persona name; choose one of: " + names)

        prefix = [
            entry
            for entry in entries
            if any(
                str(value or "").strip().casefold().startswith(lowered)
                for value in [
                    entry.get("slug"),
                    entry.get("name"),
                    entry.get("display_name"),
                    entry.get("canonical_name"),
                ]
                if value
            )
        ]
        if len(prefix) == 1:
            return prefix[0]
        if len(prefix) > 1:
            names = ", ".join(str(item.get("display_name") or item.get("name")) for item in prefix)
            raise MarketError("ambiguous persona name; choose one of: " + names)
        raise MarketError("no persona matches " + repr(text) + "; use /load-personas to list the market")

    def search(self, query: str, refresh: bool = False) -> List[Dict[str, Any]]:
        needle = str(query or "").strip().casefold()
        if not needle:
            return self.list_personas(refresh=refresh)
        results = []
        for entry in self.list_personas(refresh=refresh):
            fields = [
                entry.get("slug"),
                entry.get("name"),
                entry.get("display_name"),
                entry.get("canonical_name"),
                entry.get("description"),
            ]
            aliases = entry.get("aliases")
            if isinstance(aliases, list):
                fields.extend(aliases)
            if any(needle in str(value or "").casefold() for value in fields if value):
                results.append(entry)
        return results

    # ------------------------------------------------------------------
    # installation
    # ------------------------------------------------------------------
    def _download_entry(self, entry: Dict[str, Any]) -> Dict[str, bytes]:
        slug = _safe_slug(entry.get("slug"))
        files = entry.get("files")
        if not isinstance(files, dict):
            raise MarketError("market entry has no file checksums: " + slug)
        missing = [name for name in REQUIRED_FILES if name not in files]
        if missing:
            raise MarketError("market entry is missing " + ", ".join(missing) + ": " + slug)
        downloaded: Dict[str, bytes] = {}
        total = 0
        for name, expected in files.items():
            if name not in ALLOWED_FILES:
                raise MarketError("unexpected file in persona: " + str(name))
            raw = self._fetch(self.raw_url("personas/" + quote(slug, safe="") + "/" + name))
            limit = MAX_BYTES.get(name, MAX_TOTAL)
            if len(raw) > limit:
                raise MarketError("file is too large: " + slug + "/" + name)
            total += len(raw)
            if total > MAX_TOTAL:
                raise MarketError("persona is too large: " + slug)
            if _sha256(raw) != expected:
                raise MarketError("checksum mismatch for " + slug + "/" + name)
            downloaded[name] = raw
        return downloaded

    def _validate_download(self, slug: str, files: Dict[str, bytes]) -> None:
        try:
            meta = json.loads(files["meta.json"].decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise MarketError("persona meta.json is invalid: " + slug) from exc
        if not isinstance(meta, dict):
            raise MarketError("persona meta.json is not an object: " + slug)
        if str(meta.get("slug") or "") != slug:
            raise MarketError("persona meta.json slug does not match the folder: " + slug)
        if not str(meta.get("name") or "").strip():
            raise MarketError("persona meta.json has no name: " + slug)
        if not str(meta.get("updated_at") or "").strip():
            raise MarketError("persona meta.json has no updated_at: " + slug)
        try:
            dossier = files["PERSONALITY.md"].decode("utf-8").lstrip("\ufeff").strip()
        except UnicodeDecodeError as exc:
            raise MarketError("PERSONALITY.md is not UTF-8: " + slug) from exc
        if not dossier.startswith("# "):
            raise MarketError("PERSONALITY.md must start with a level-1 heading: " + slug)
        combined = "\n".join(raw.decode("utf-8", "ignore") for raw in files.values())
        hits = _secret_hits(combined)
        if hits:
            raise MarketError("persona contains possible credential material (" + ", ".join(hits) + "): " + slug)

    def install(self, selector: str, force: bool = False, refresh: bool = False) -> Dict[str, Any]:
        catalog = self.catalog(refresh=refresh)
        entry = self.resolve(selector, catalog)
        slug = _safe_slug(entry.get("slug"))
        target = self.root / slug
        if target.is_symlink():
            raise MarketError("refusing to replace a symlinked personality folder: " + slug)
        if target.exists() and not force:
            raise MarketError(
                "persona " + slug + " is already installed; use /load-personas --force " + slug + " to replace it"
            )

        files = self._download_entry(entry)
        self._validate_download(slug, files)

        self.root.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=".install-", dir=self.root))
        backup = None
        try:
            for name, raw in files.items():
                path = temp_dir / name
                path.write_bytes(raw)
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
            if target.exists():
                backup = self.root / (".backup-" + slug + "-" + str(int(time.time())))
                target.rename(backup)
            temp_dir.rename(target)
            temp_dir = None
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)
        except Exception:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
            if backup is not None and backup.exists() and not target.exists():
                backup.rename(target)
            raise

        display = str(entry.get("display_name") or entry.get("name") or slug)
        return {
            "ok": True,
            "slug": slug,
            "name": display,
            "path": str(target),
            "message": "Installed " + display + " to " + str(target) + ". Activate with /chatto " + display,
        }

    def install_all(self, force: bool = False, refresh: bool = False) -> List[Dict[str, Any]]:
        catalog = self.catalog(refresh=refresh)
        results = []
        for entry in catalog.get("personas") or []:
            slug = str(entry.get("slug") or "")
            if not force and self._local_current(slug, entry.get("files") or {}):
                results.append(
                    {
                        "ok": True,
                        "skipped": True,
                        "slug": slug,
                        "message": "already installed and current",
                    }
                )
                continue
            if not force and (self.root / slug).exists():
                results.append(
                    {
                        "ok": False,
                        "skipped": True,
                        "slug": slug,
                        "message": "installed copy differs; use --force to update",
                    }
                )
                continue
            try:
                results.append(self.install(slug, force=force, refresh=False))
            except MarketError as exc:
                results.append({"ok": False, "slug": slug, "message": str(exc)})
        return results

    # ------------------------------------------------------------------
    # formatting
    # ------------------------------------------------------------------
    def format_catalog(self, refresh: bool = False) -> str:
        try:
            entries = self.list_personas(refresh=refresh)
        except MarketError as exc:
            return "Persona market unavailable: " + str(exc)
        lines = ["Collig Persona Market  " + self.repo + "@" + self.ref, ""]
        for entry in entries:
            if entry.get("current"):
                status = "installed"
            elif entry.get("update_available"):
                status = "update available"
            else:
                status = "available"
            name = str(entry.get("display_name") or entry.get("name") or entry.get("slug"))
            line = f"{entry['number']:>2}. {name}  [{status}]"
            canonical = str(entry.get("canonical_name") or "")
            if canonical and canonical.casefold() != name.casefold():
                line += "  · " + canonical
            lines.append(line)
            description = str(entry.get("description") or "").strip()
            if description:
                lines.append("    " + description[:140])
        lines.extend(
            [
                "",
                "Install one:  /load-personas <number|name>",
                "All:          /load-personas --all",
                "Refresh:      /load-personas refresh",
                "Search:       /load-personas search <text>",
                "Replace:      /load-personas --force <name>",
            ]
        )
        if self.used_cache:
            lines.append("")
            lines.append("Using cached catalogue (" + self.last_error + ")")
        return "\n".join(lines)


_MARKET: Optional[PersonaMarket] = None


def get_persona_market() -> PersonaMarket:
    global _MARKET
    if _MARKET is None:
        _MARKET = PersonaMarket(
            repo=os.environ.get("COLLIG_PERSONAS_REPO", DEFAULT_REPO),
            ref=os.environ.get("COLLIG_PERSONAS_REF", DEFAULT_REF),
        )
    return _MARKET


def reset_persona_market(**kwargs: Any) -> PersonaMarket:
    global _MARKET
    _MARKET = PersonaMarket(**kwargs)
    return _MARKET
