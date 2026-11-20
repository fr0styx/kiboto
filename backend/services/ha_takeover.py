"""High availability, fourth step: the second NAS takes over (the owner's decisions of 19 Nov 2026:
by a button; only the name moves; the kept copy of people and settings is applied then; going back
is done by hand).

What a takeover brings from the first NAS is its people: their sign-in, roles and two-factor
(users.db), their sign-in over the network (Samba's own list), who may open which of the folders
this NAS keeps, and the name the family types. Everything else in the copy belongs to the first
NAS's hardware (its network address, drives and fans) or to its apps, machines and backups, and
stays where it is.

The people are staged like any settings restore and applied at the next start, before a database
is opened; what this box had is saved first. A box that took over stops fetching. When the first
NAS comes back it asks before it answers to its name, and holds the name back if the second one
took over. "Take the name back" on the first NAS ends that; files and people changed on the second
NAS in between are not copied back: that is done by hand.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import zipfile
from typing import Any

from backend import secret_box
from backend.config import logger
from backend.fsutil import atomic_write_json, read_json
from backend.services import ha_bring, ha_link, ha_state
from backend.services.ha_link import LinkError

# what a takeover takes out of the copy; the rest of it stays the first NAS's own
PEOPLE_FILES = ("users.db", "vapid.json")
PEOPLE_FOLDERS = ("samba/private/",)
ACCESS = "share_access.json"
NAME = "nas_name.json"
KEY = "secret.key"
ASK_EVERY = 900  # a first NAS asks its second one every quarter of an hour whether it took over

_asked = {"at": 0.0}


def took_over() -> dict[str, Any] | None:
    """On the second NAS: when it took over, from whom, and the name it answers to since."""
    found = ha_link._state().get("took_over")
    return found if isinstance(found, dict) else None


def stood_down() -> dict[str, Any] | None:
    """On the first NAS: since when it holds its name back, because the second one took over."""
    found = ha_link._state().get("stood_down")
    return found if isinstance(found, dict) else None


# --- staging the people ---------------------------------------------------------------------------
def _text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _reseal_two_factor(db_path: str, their_key: str) -> int:
    """Two-factor secrets in the staged people are sealed with the first NAS's key. They are sealed
    again with this box's own, so everyone keeps the authenticator app they have. How many."""
    done = 0
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, mfa_secret FROM users WHERE mfa_secret IS NOT NULL AND mfa_secret != ''"
        ).fetchall()
        for user_id, value in rows:
            if secret_box.is_sealed(str(value)):
                plain = secret_box.unseal_with(str(value), their_key)
                conn.execute("UPDATE users SET mfa_secret = ? WHERE id = ?", (secret_box.seal(plain), user_id))
                done += 1
        conn.commit()
    finally:
        conn.close()
    return done


def _people(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    finally:
        conn.close()


def _access(data_dir: str, theirs: Any, folders: list[str]) -> dict[str, Any]:
    """This box's list of who may open which shared folder, with the first NAS's word for the
    folders kept in step. The other folders here keep the access they have."""
    own = read_json(os.path.join(data_dir, ACCESS), {})
    own = own if isinstance(own, dict) else {}
    had = own.get("shares")
    shares: dict[str, Any] = had if isinstance(had, dict) else {}
    said = theirs.get("shares") if isinstance(theirs, dict) else None
    their_shares: dict[str, Any] = said if isinstance(said, dict) else {}
    for name in folders:
        if isinstance(their_shares.get(name), dict):
            shares[name] = their_shares[name]
    own["shares"] = shares
    return own


def _read_staged(staged: str, manifest: str) -> dict[str, Any]:
    listed = read_json(manifest, [])
    listed = [rel for rel in listed if isinstance(rel, str)] if isinstance(listed, list) else []
    name = read_json(os.path.join(staged, NAME), {})
    name = name if isinstance(name, dict) else {}
    return {
        "listed": listed,
        "keep": [rel for rel in listed if rel in PEOPLE_FILES or rel.startswith(PEOPLE_FOLDERS)],
        "key": _text(os.path.join(staged, KEY)),
        "name": str(name.get("name") or "").lower(),
        "name_on": bool(name.get("enabled")),
        "access": read_json(os.path.join(staged, ACCESS), {}),
    }


def _stage(folders: list[str], bring: tuple[str, ...] = ()) -> dict[str, Any]:
    """Stages the first NAS's people out of the kept copy, for the next start to apply, and what
    else was asked for (`bring`: see ha_bring). Returns the name the first NAS answered to, whether
    it did, how many people and two-factor secrets came, and what was brought along."""
    from backend.services import backup_engine as be

    opens = ha_state.passphrase()
    if not opens or ha_state.info() is None:
        raise LinkError("no_copy", "There is no copy of the first NAS's people yet. Fetch it first.")
    data_dir = os.path.abspath(be.DATA_DIR)
    staged = os.path.join(data_dir, be.STAGED_RESTORE_DIR)
    manifest = os.path.join(staged, be.STAGED_MANIFEST)
    try:
        with open(os.path.join(ha_state.DIR, ha_state.COPY), "rb") as f:
            be.restore_backup_archive(f, passphrase=opens, snapshot=True, staged=True)
        found = _read_staged(staged, manifest)
        if "users.db" not in found["keep"]:
            raise ValueError("it has no people in it")
        theirs = ha_bring.read_backups(staged) if "backups" in bring else None
        for rel in found["listed"]:
            if rel not in found["keep"]:
                os.remove(os.path.join(staged, rel))  # the first NAS's own: its key, network, apps
        resealed = _reseal_two_factor(os.path.join(staged, "users.db"), found["key"])
        people = _people(os.path.join(staged, "users.db"))
        extra: list[str] = []
        brought: dict[str, int] = {}
        if theirs is not None:
            plan, brought = ha_bring.plan_backups(
                theirs, ha_bring.read_backups(data_dir), found["key"], folders, ha_bring.here()
            )
            extra = ha_bring.write_backups(staged, plan, brought)
        atomic_write_json(os.path.join(staged, ACCESS), _access(data_dir, found["access"], folders))
        atomic_write_json(manifest, [*found["keep"], ACCESS, *extra])
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile) as e:
        be.discard_staged_restore(data_dir)
        raise LinkError("bad_copy", f"The kept copy could not be used: {e}") from e
    return {
        "name": found["name"],
        "name_on": found["name_on"],
        "people": people,
        "two_factor": resealed,
        "brought": brought,
    }


# --- on the second NAS: taking over ----------------------------------------------------------------
def take_over(
    actor: str = "",
    even_if_answering: bool = False,
    bring: tuple[str, ...] = (),
    send: ha_link.Sender = ha_link._post,
) -> dict[str, Any]:
    """The second NAS becomes the one the family uses. Refused while the first NAS still answers,
    unless that is said to be known: two boxes would answer to one name. `bring` names what else
    the person asked to come along (ha_bring.CHOICES); it arrives switched off."""
    from backend.services import box_restore, ha_folders, nas_name

    if ha_link.role() != "second":
        raise LinkError("not_second", "Only the second NAS of a pair takes over.")
    if ha_state.info() is None:
        raise LinkError("no_copy", "There is no copy of the first NAS's people yet. Fetch it first.")
    answers = bool((ha_link.check(send=send).get("peer") or {}).get("reachable"))
    if answers and not even_if_answering:
        raise LinkError("first_answers", "The first NAS still answers. Turn it off first, or take over anyway.")
    first = ha_link.peer() or {}
    staged = _stage(ha_folders.chosen(), tuple(b for b in bring if b in ha_bring.CHOICES))
    if answers:
        try:
            ha_link.call("stand_down", send=send)  # it stops answering to the name, at once
        except LinkError as e:
            logger.warning("[HA] the first NAS was not told to hold its name back: %s", e)
    own = nas_name.config()
    took = {
        "at": time.time(),
        "from": str(first.get("name") or ""),
        "name": staged["name"] if staged["name_on"] and nas_name.valid(staged["name"]) else "",
        "own_name": own["name"],
        "own_enabled": own["enabled"],
        "by": actor,
        "people": staged["people"],
        "brought": staged["brought"],
    }
    ha_link._change(lambda d: d.update(took_over=took))
    if took["name"]:
        nas_name.save(enabled=True, name=took["name"])
    ha_link.audit(
        "takeover", f"took over from {took['from']}: {took['people']} people, name {took['name'] or '-'}", actor
    )
    logger.warning("[HA] this NAS took over from %s", took["from"])
    return {"took_over": took, **box_restore.restart_to_apply()}


def _release(_args: dict[str, Any]) -> dict[str, Any]:
    """On a second NAS that took over: the first one takes its name back."""
    from backend.services import nas_name

    took = took_over()
    if took is None:
        raise LinkError("refused", "This NAS did not take over.")
    ha_link._change(lambda d: d.pop("took_over", None))
    if took.get("name"):
        nas_name.give_up(str(took["name"]), str(took.get("own_name") or ""), bool(took.get("own_enabled")))
    ha_link.audit("released", "the first NAS took its name back", "")
    return {"ok": True}


# --- on the first NAS: holding the name back, and taking it back ------------------------------------
def _hold(why: str) -> None:
    from backend.services import nas_name

    if stood_down() is None:
        ha_link._change(lambda d: d.update(stood_down={"at": time.time()}))
        ha_link.audit("stood_down", why, "")
        logger.warning("[HA] %s; this NAS does not answer to its name until it is taken back", why)
    nas_name.hold(True)


def _stand_down(_args: dict[str, Any]) -> dict[str, Any]:
    """On the first NAS: the second one is taking over."""
    if ha_link.role() != "first":
        raise LinkError("refused", "Only a first NAS stands down.")
    _hold("the second NAS is taking over")
    return {"ok": True}


def noticed(said: dict[str, Any]) -> None:
    """After every hello: a first NAS that hears its second one took over holds its name back."""
    if said.get("role") == "took_over" and ha_link.role() == "first":
        _hold("the second NAS took over while this one was away")


def take_back(
    actor: str = "", even_if_unreachable: bool = False, send: ha_link.Sender = ha_link._post
) -> dict[str, Any]:
    """On the first NAS: it answers to its name again, and the second one stops. When the second one
    cannot be told, that has to be said to be known: it may still answer to the name."""
    from backend.services import nas_name

    if ha_link.role() != "first" or stood_down() is None:
        raise LinkError("not_held", "This NAS is not holding its name back.")
    try:
        ha_link.call("release", send=send)
    except LinkError as e:
        if e.key != "refused" and not even_if_unreachable:  # refused: it holds nothing any more
            raise LinkError("second_unreachable", "The second NAS did not answer, so it may still use the name.") from e
    ha_link._change(lambda d: d.pop("stood_down", None))
    nas_name.hold(False)
    ha_link.audit("took_back", "this NAS answers to its name again", actor)
    return view()


def watch(now: float | None = None) -> bool:
    """Called every minute: a first NAS asks its second one now and then (noticed() acts on the answer)."""
    now = time.time() if now is None else now
    if now - _asked["at"] < ASK_EVERY or ha_link.role() != "first":
        return False
    _asked["at"] = now
    threading.Thread(target=ha_link.check, name="ha-ask", daemon=True).start()
    return True


def name_at_start() -> None:
    """At start, on a thread: a first NAS asks its second one before it answers to its name. A box
    that is not a first NAS starts the name service as always."""
    from backend.services import nas_name

    def run() -> None:
        try:
            if ha_link.role() == "first":
                _asked["at"] = time.time()
                ha_link.check()
            nas_name.ensure()
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("[HA] could not check the name service at start", exc_info=True)

    threading.Thread(target=run, name="nas-name", daemon=True).start()


def forget() -> None:
    """Unpaired: neither box holds anything for the other. The name each has now stays."""
    from backend.services import nas_name

    held = stood_down() is not None

    def change(data: dict[str, Any]) -> None:
        data.pop("took_over", None)
        data.pop("stood_down", None)

    ha_link._change(change)
    if held:
        nas_name.hold(False)


def view() -> dict[str, Any]:
    """What the screen adds to the link's status."""
    took, held = took_over(), stood_down()
    return {
        "took_over": {k: took.get(k) for k in ("at", "from", "name", "people", "brought")} if took else None,
        "stood_down": {"at": held.get("at")} if held else None,
    }


ha_link.HANDLERS.update(stand_down=_stand_down, release=_release)
ha_link.ON_HELLO.append(noticed)
ha_link.ON_UNPAIR.append(forget)
