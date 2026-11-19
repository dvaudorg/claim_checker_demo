"""Add-ons: what an app built on ENLENS adds, in files of its own (0.13.5). See docs/EXTENDING.md.

An add-on is a Python module. It comes from one of two places, and ENLENS reads both:

- a **fork** fills in `enlens_claims/gui/extensions.py`, which ENLENS ships holding only a docstring;
- a **separate package** names its module under the entry point group `enlens.extensions`, in its pyproject.toml:

      [project.entry-points."enlens.extensions"]
      fieldnotes = "fieldnotes_addon"

ENLENS reads only the names an add-on defines and uses its own default for every other one, so ENLENS alone (no
add-on) behaves exactly as before. The names (each one optional):

- `BRAND`: a dict over `static/brand.json` (name, tagline, welcome_title, welcome_text, description, logo).
- `STATIC`: a folder of the add-on's page files, served at `/static/addons/<add-on>/`. Its `site.css`, when there
  is one, is added to `/static/site.css` after the installation's own.
- 0.13.6: `ROUTES`: (method, pattern, handler) tried after ENLENS's own routes. The pattern is a regular expression for
  the whole path (`/api/...`); the handler is a function `handler(h, *groups, q)` (`h` is the request handler: `h.app`
  the app, `h._body()` the JSON body) or the name of a Handler method. It returns a dict (sent as JSON) or None.
- 0.13.6: `DOWNLOADS`: the names of handlers that a plain link may call with `?token=`.
- 0.13.6: `state(app)` and `overview(ws)`: extra keys for `GET /api/state` and a project's Overview. They never replace
  one of ENLENS's keys.
- 0.13.6: `SCHEMA` (SQL run after ENLENS's own, `CREATE TABLE IF NOT EXISTS ...`), `MIGRATIONS` ((table, column,
  type), added when missing) and `INDEXES` (SQL run after them), in every project as it is opened.

ENLENS's standing rules apply to anything an add-on adds: `home.local_only()`, the per-document AI settings and the
quote check are checked by ENLENS, never by the add-on.

An add-on that fails to load is left out (ENLENS still starts) and its error is kept in `errors()`.
"""
from __future__ import annotations

import importlib
import json
import re
import sqlite3
import sys
import traceback
from importlib import metadata
from pathlib import Path
from types import ModuleType

GROUP = "enlens.extensions"
LOCAL = "enlens_claims.gui.extensions"
STATIC = Path(__file__).with_name("gui") / "static"
BRAND_FILE = STATIC / "brand.json"
BRAND_KEYS = ("name", "tagline", "welcome_title", "welcome_text", "description", "logo")

_loaded: list[tuple[str, ModuleType]] | None = None
_errors: list[dict] = []
# hunt phase 1.5 (review of wave 1): an add-on whose tables failed in ONE project is left out of that project only:
# {project folder: {add-on: why}}
_failed_in: dict[str, dict[str, str]] = {}


def _entry_points() -> list:
    try:
        return sorted(metadata.entry_points(group=GROUP), key=lambda ep: ep.name)
    except Exception:  # a broken installed package must not stop ENLENS
        return []


def load(refresh: bool = False) -> list[tuple[str, ModuleType]]:
    """The add-ons, as (name, module): the fork's gui/extensions.py first, then each package's, by name."""
    global _loaded
    if _loaded is not None and not refresh:
        return _loaded
    out: list[tuple[str, ModuleType]] = []
    _errors.clear()
    try:
        out.append(("local", importlib.import_module(LOCAL)))
    except Exception as e:  # noqa: BLE001: a fork's broken file is reported, not fatal
        _errors.append({"addon": "local", "error": f"{type(e).__name__}: {e}"})
        traceback.print_exc()
    for ep in _entry_points():
        try:
            mod = ep.load()
        except Exception as e:  # noqa: BLE001
            _errors.append({"addon": ep.name, "error": f"{type(e).__name__}: {e}"})
            print(f"ENLENS: the add-on {ep.name} could not be loaded: {e}", file=sys.stderr)
            continue
        out.append((ep.name, mod))
    _loaded = out
    return out


def _key(where) -> str:
    root = where if isinstance(where, (str, Path)) else getattr(where, "root", where)  # (a Path's own .root is "/")
    return str(Path(root).expanduser().resolve())


def errors(where=None) -> list[dict]:
    """The add-ons' problems: those that could not be loaded (every project) and, with `where` (a project or its
    folder), those left out of that project ({"addon", "error", "project": its folder's name}); without `where`, every
    project's."""
    load()
    # (without `where`, only projects still there: a new project's empty database is set up once in a temporary
    # folder, store._copy_empty_database, and its failures are the same project's again)
    keys = [_key(where)] if where is not None else [k for k in list(_failed_in) if Path(k).exists()]
    return list(_errors) + [{"addon": n, "error": e, "project": Path(k).name}
                            for k in keys for n, e in sorted(_failed_in.get(k, {}).items())]


def failed(name: str, error: str, where=None) -> None:
    """Hunt phase 1.5: an add-on that loaded but failed later is left out, printed and kept: with `where` (a project
    or its folder: its tables could not be set up there) for that project only; without, for every project (a name
    it cannot use anywhere). Printed once per add-on, project and message."""
    load()
    if where is not None:
        here = _failed_in.setdefault(_key(where), {})
        if here.get(name) == error:
            return
        here[name] = error
        print(f"ENLENS: the add-on {name} was left out of the project {Path(_key(where)).name}: {error}",
              file=sys.stderr)
        return
    row = {"addon": name, "error": error}
    if row not in _errors:
        _errors.append(row)
        print(f"ENLENS: the add-on {name} was left out: {error}", file=sys.stderr)


def set_up(name: str, where) -> None:
    """The add-on's tables were set up in this project (again): a failure noted before is forgotten."""
    _failed_in.get(_key(where), {}).pop(name, None)


def left_out(where) -> set[str]:
    """The add-ons left out of a project (a Workspace, its folder, or a connection to its database)."""
    if isinstance(where, sqlite3.Connection):  # a connection: its database's folder
        try:
            where = Path(where.execute("PRAGMA database_list").fetchone()[2]).parent
        except Exception:  # noqa: BLE001 - an in-memory database belongs to no project
            return set()
    return set(_failed_in.get(_key(where), {})) if _failed_in else set()


def owner_of(handler) -> str | None:
    """The add-on whose ROUTES hold `handler`, or None (one of ENLENS's own)."""
    for n, m in load():
        for r in getattr(m, "ROUTES", None) or []:
            try:
                if r[2] is handler:
                    return n
            except (IndexError, TypeError):
                continue
    return None


def kind_left_out(where, kind) -> str:
    """Words when `kind` (an add-on's kind of task: its store function lives in the add-on's module) belongs to an
    add-on left out of this project (`where`: a connection, a Workspace or a folder); "" otherwise. Its answers are
    then not stored there: the add-on's tables were not set up."""
    out = left_out(where)
    if not out:
        return ""
    mod = getattr(getattr(kind, "store", None), "__module__", "") or ""
    for n, m in load():
        if n in out and (mod == m.__name__ or mod.startswith(m.__name__ + ".")):
            return (f"The add-on {n} is left out of this project (its tables could not be set up here), so an answer "
                    f"of its kind {getattr(kind, 'name', '')!r} cannot be stored in it. Leave this task for now.")
    return ""


def refused_here(handler, project_folder) -> str:
    """Words for a call of an add-on's route in a project the add-on is left out of; "" when it may run."""
    n = owner_of(handler)
    if not n or n not in left_out(project_folder):
        return ""
    why = _failed_in.get(_key(project_folder), {}).get(n, "")
    return (f"The add-on {n} is left out of the project {Path(_key(project_folder)).name}: its tables could not be "
            f"set up there ({why}). Its other projects are not affected.")


def names() -> list[str]:
    """The add-ons in use, apart from an empty local layer."""
    return [n for n, m in load() if n != "local" or defines(m)]


def defines(mod: ModuleType) -> bool:
    """Whether a module defines anything an add-on can (an empty gui/extensions.py does not)."""
    return any(not k.startswith("_") and k.isupper() or k in HOOKS for k in vars(mod))


HOOKS = ("state", "overview")  # functions an add-on may define


def values(attr: str) -> list:
    """Every add-on's `attr`, in load order (add-ons that do not define it are skipped)."""
    return [getattr(m, attr) for _n, m in load() if getattr(m, attr, None) is not None]


# -------------------------------------------------------------------------------------------------- branding
def brand() -> dict:
    """The app's name and words: static/brand.json, then each add-on's BRAND over it. Only known keys, as text."""
    try:
        out = json.loads(BRAND_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        out = {}
    out = {k: str(out[k]) for k in BRAND_KEYS if isinstance(out.get(k), str) and out[k].strip()}
    for b in values("BRAND"):
        if isinstance(b, dict):
            out.update({k: str(v) for k, v in b.items() if k in BRAND_KEYS and isinstance(v, str) and v.strip()})
    out.setdefault("name", "ENLENS")
    out.setdefault("logo", "/static/logo.svg")
    return out


# -------------------------------------------------------------------------------------------------- page files
def static_dirs() -> dict[str, Path]:
    """Each add-on's folder of page files, by add-on name (a fork keeps its files in static/ itself)."""
    out = {}
    for n, m in load():
        d = getattr(m, "STATIC", None)
        if d and n != "local" and Path(d).is_dir():
            out[n] = Path(d)
    return out


def static_file(rel: str) -> Path | None:
    """The add-on file served at /static/addons/<add-on>/<path>, or None. Never outside the add-on's folder."""
    name, _, rest = rel.partition("/")
    base = static_dirs().get(name)
    if not base or not rest:
        return None
    target = (base / rest).resolve()
    return target if target.is_relative_to(base.resolve()) and target.is_file() else None


def site_css() -> bytes:
    """/static/site.css: the installation's own (static/site.css), then each add-on's site.css."""
    parts = [(STATIC / "site.css").read_bytes()] if (STATIC / "site.css").is_file() else []
    for n, d in static_dirs().items():
        f = d / "site.css"
        if f.is_file():
            parts.append(f"\n/* add-on: {n} */\n".encode() + f.read_bytes())
    return b"".join(parts)


# -------------------------------------------------------------------------------------------------- 0.13.6: the server
def routes() -> list[tuple[str, re.Pattern, object]]:
    """Every add-on's routes, compiled: (method, pattern for the whole path, handler)."""
    out = []
    for n, m in load():
        for r in getattr(m, "ROUTES", None) or []:
            try:
                method, pattern, handler = r
                out.append((str(method).upper(), re.compile("^" + pattern.lstrip("^").rstrip("$") + "$"), handler))
            except (ValueError, TypeError, re.error) as e:
                _errors.append({"addon": n, "error": f"a route could not be read ({r!r}): {e}"})
    return out


def handler_name(handler) -> str:
    return handler if isinstance(handler, str) else getattr(handler, "__name__", "")


def downloads() -> set[str]:
    out: set[str] = set()
    for d in values("DOWNLOADS"):
        out |= {handler_name(x) for x in d}
    return out


def _extra(hook: str, arg, taken, skip: set[str] = frozenset()) -> dict:
    """The keys each add-on's `hook(arg)` adds; a key ENLENS (or an earlier add-on) has is left out. An add-on whose
    hook fails adds nothing: the page still opens. `skip`: add-ons left out (of the project `arg`)."""
    out: dict = {}
    for n, m in load():
        if n in skip:
            continue
        fn = getattr(m, hook, None)
        if not callable(fn):
            continue
        try:
            got = fn(arg) or {}
        except Exception as e:  # noqa: BLE001
            print(f"ENLENS: the add-on {n} failed in {hook}(): {e}", file=sys.stderr)
            continue
        for k, v in (got.items() if isinstance(got, dict) else ()):
            if k not in taken and k not in out:
                out[k] = v
    return out


def state(app, taken) -> dict:
    """Extra keys for GET /api/state."""
    return _extra("state", app, taken)


def overview(ws, taken) -> dict:
    """Extra keys for a project's Overview (none from an add-on left out of that project)."""
    return _extra("overview", ws, taken, left_out(ws))


# -------------------------------------------------------------------------------------------------- 0.13.6: the database
# hunt phase 1 (INSTALL-8): matched whole (`fullmatch`): with `match` and `$`, a name ending in a line break passed
# ("ai_note\n"), SQLite added the column as "ai_note", and every later opening tried to add it again and failed with
# "duplicate column name", so no project could be opened or made, in words that named no add-on
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TYPE = re.compile(r"[A-Za-z0-9_ ()'.,-]+")


def database() -> list[dict]:
    """Each add-on's SCHEMA, MIGRATIONS and INDEXES, in load order (only add-ons that define one of them). Hunt phase
    1.5 (the owner's rule): an add-on with a column ENLENS cannot add is left out and named in `errors()`; it raised,
    and the ValueError stopped every project from opening."""
    out = []
    for n, m in load():
        schema, migrations, indexes = (getattr(m, k, None) for k in ("SCHEMA", "MIGRATIONS", "INDEXES"))
        if not (schema or migrations or indexes):
            continue
        cols, bad = [], None
        for mg in migrations or []:
            table, col, typ = mg if isinstance(mg, (tuple, list)) and len(mg) == 3 else (None, None, None)
            if not (isinstance(table, str) and isinstance(col, str) and isinstance(typ, str)
                    and _NAME.fullmatch(table) and _NAME.fullmatch(col) and _TYPE.fullmatch(typ)):
                bad = f"The add-on {n} names a column ENLENS cannot add: {mg!r}"
                break
            cols.append((table, col, typ))
        if bad:
            failed(n, bad)
            continue
        out.append({"addon": n, "schema": schema or "", "migrations": cols, "indexes": indexes or ""})
    return out


# Statements that cannot run inside the savepoint each add-on's SQL runs in (store._setup_addons): they manage the
# transaction or the database file themselves. `executescript` ran them before hunt phase 1.5; now the add-on is
# refused with words that name the statement (docs/EXTENDING.md).
_OWN_TRANSACTION = re.compile(r"\s*(BEGIN|COMMIT|END|ROLLBACK|SAVEPOINT|RELEASE|VACUUM|ATTACH|DETACH|"
                              r"PRAGMA\s+(\w+\.)?journal_mode)\b", re.I)


def transaction_statement(stmt: str) -> str:
    """The words of `stmt`'s start when it manages the transaction or the file itself (BEGIN, COMMIT, VACUUM, PRAGMA
    journal_mode...), else ""."""
    m = _OWN_TRANSACTION.match(stmt)
    return " ".join(m.group(1).split()) if m else ""


def statements(script: str) -> list[str]:
    """The SQL statements of a script, one by one (a trigger's body stays whole), so they can run inside a savepoint
    one `execute` at a time (`executescript` commits what came before it first)."""
    import sqlite3

    out, buf = [], ""
    for piece in script.split(";"):
        buf += piece + ";"
        if sqlite3.complete_statement(buf):
            if buf.strip().strip(";").strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip().strip(";").strip():
        out.append(buf.strip().rstrip(";"))  # an unfinished statement: SQLite says what is wrong with it
    return out


# -------------------------------------------------------------------------------------------------- 0.13.6: the page
def page_modules() -> list[str]:
    """The page modules of add-on packages that have one (STATIC/extensions.js), as the page imports them."""
    return [f"/static/addons/{n}/extensions.js" for n, d in static_dirs().items() if (d / "extensions.js").is_file()]
