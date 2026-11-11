"""
Collections: batches you make yourself, by moving images and films into them from Output, one at a time.

An item moved keeps its file where it is and everything that made it (an image its kept setup, a film its run), so all
it could do before (open, upscale, more like this, prompts, redo, download) it still does; it is only shown in its
collection, not where it was. A collection holds both kinds, each as an album of its own, in the order they came.

Kept in logs/collections.json:
    {"collections": [{"id": "c_20261109_181500", "name": "Portraits", "items": [
        {"kind": "image", "run": "image_20261109_121447", "file": "..._004.png"}, {"kind": "film", "name": "Film.mp4"}]}]}
"""
import json
import os
import threading
from datetime import datetime

from flask import request

from panel import server
from panel.server import FOLDERS, LOGS_DIR, PIPELINES, _runs_cache, app, password_required, run_queue
from pipelines.image import paths as image_paths

PATH = os.path.join(LOGS_DIR, "collections.json")
MOST_NAME = 80
_lock = threading.Lock()


def _read():
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    found = data.get("collections") if isinstance(data, dict) else None
    return [c for c in found if isinstance(c, dict) and c.get("id") and isinstance(c.get("items"), list)] if isinstance(found, list) else []


def _write(collections):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    temp = PATH + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump({"collections": collections}, f, ensure_ascii=False, indent=1)
    os.replace(temp, PATH)


def _key(item):
    return (item["kind"], item.get("run"), item.get("file")) if item.get("kind") == "image" else ("film", item.get("name"))


def _clean_name(name):
    name = " ".join(str(name or "").split())[:MOST_NAME]
    if not name:
        raise ValueError("Give the collection a name.")
    return name


def membership():
    """{item key: collection id} for every item in a collection."""
    with _lock:
        return {_key(item): collection["id"] for collection in _read() for item in collection["items"]}


# --- What Output shows: items in a collection are only shown there ---

def apply(payload):
    """
    Marks what is in a collection ("collection" on each image and film), and lists the collections with their items
    in the order they came, dropping any whose file is gone. A collection is NSFW if any of its items is.
    """
    images = {(image_set["id"], image.get("file")): (image_set, image)
              for image_set in payload.get("image_sets", []) for image in image_set.get("images", [])}
    films = {film["name"]: film for film in payload.get("videos", {}).get("video", [])}
    with _lock:
        collections = _read()
        changed = False
        for collection in collections:
            # Only what is really gone from the disk: a list that came out short for a moment (the sets still being
            # read just after a restart, say) once dropped every image from every collection.
            kept = [item for item in collection["items"] if not _gone(item)]
            if len(kept) != len(collection["items"]):
                collection["items"] = kept
                changed = True
        if changed:
            _write(collections)
    shown = []
    for collection in collections:
        items, nsfw = [], False
        for item in collection["items"]:
            if item.get("kind") == "image" and (item.get("run"), item.get("file")) in images:
                image_set, image = images[(item["run"], item["file"])]
                image["collection"] = collection["id"]
                nsfw = nsfw or bool(image_set.get("nsfw"))
                items.append({"kind": "image", "set": image_set["id"], "file": item["file"]})
            elif item.get("kind") == "film" and item.get("name") in films:
                films[item["name"]]["collection"] = collection["id"]
                nsfw = nsfw or bool(films[item["name"]].get("nsfw"))
                items.append({"kind": "film", "name": item["name"]})
        shown.append({"id": collection["id"], "name": collection.get("name") or "Collection", "nsfw": nsfw, "items": items,
                      "folded": bool(collection.get("folded"))})
    payload["collections"] = shown


def _gone(item):
    """Whether an item's own file is gone from the disk (deleted, or its set with it): asked of the disk, not a list."""
    from panel import image as image_panel
    if item.get("kind") == "image":
        state = image_panel.RunState.load(item.get("run"))
        shot = next((s for s in (state.shots if state else []) if s.get("file") == item.get("file")), None)
        if state is None and os.path.isdir(os.path.join(image_paths.RUNS_DIR, str(item.get("run")))):
            return False  # Its run is there but can't be read just now (being written): not gone
        return not shot or not os.path.isfile(state.image_path(shot))
    if item.get("kind") == "film":
        return not os.path.isfile(os.path.join(FOLDERS["video"], str(item.get("name"))))
    return True


# --- Changing them ---

def _find(collections, collection_id):
    return next((c for c in collections if c["id"] == collection_id), None)


@app.route("/api/collections", methods=["POST"])
@password_required
def create_collection():
    try:
        name = _clean_name((request.get_json(silent=True) or {}).get("name"))
    except ValueError as e:
        return {"ok": False, "error": str(e)}, 400
    with _lock:
        collections = _read()
        collection = {"id": f"c_{datetime.now():%Y%m%d_%H%M%S_%f}", "name": name, "items": []}
        collections.append(collection)
        _write(collections)
    return {"ok": True, "collection": collection}


@app.route("/api/collections/<collection_id>/rename", methods=["POST"])
@password_required
def rename_collection(collection_id):
    try:
        name = _clean_name((request.get_json(silent=True) or {}).get("name"))
    except ValueError as e:
        return {"ok": False, "error": str(e)}, 400
    with _lock:
        collections = _read()
        collection = _find(collections, collection_id)
        if not collection:
            return {"ok": False, "error": "That collection is gone."}, 404
        collection["name"] = name
        _write(collections)
    return {"ok": True}


def _why_not_movable(item):
    """Why this item can't move now (being made, or an upscale of it waits), as a reply, or None if it's gone."""
    from panel import image as image_panel
    if item["kind"] == "image":
        state = image_panel.RunState.load(item["run"])
        shot = next((s for s in (state.shots if state else []) if s.get("file") == item["file"]), None)
        if not shot:
            return {"ok": False, "error": "That image is no longer there."}, 404
        refused = image_panel.upscales_in_the_way(item["run"], shot)
        if refused:
            body, status = refused
            return {"ok": False, "error": body["error"].replace("Delete images", "Move it").replace("delete images", "move it")}, status
        return None
    if not os.path.isfile(os.path.join(FOLDERS["video"], item["name"])):
        return {"ok": False, "error": "That film is no longer there."}, 404
    run = server.run_of_film(item["name"])
    if run and run in server.busy_runs():
        return {"ok": False, "error": "That film's run is in the queue or going: move it once it's done."}, 409
    if any(item["name"] in (job.get("argv") or []) for job in run_queue.pending()):
        return {"ok": False, "error": "An upscale of this film waits in the queue: move it once it's done."}, 409
    return None


def _item_from(data):
    """The item asked for: an image by its set and file, or a film by its name in Videos. ValueError if neither."""
    if data.get("kind") == "image" and isinstance(data.get("run"), str) and isinstance(data.get("file"), str):
        return {"kind": "image", "run": data["run"], "file": os.path.basename(data["file"])}
    if data.get("kind") == "film" and isinstance(data.get("name"), str):
        return {"kind": "film", "name": os.path.basename(data["name"])}
    raise ValueError("Say which image or film to move.")


@app.route("/api/collections/move", methods=["POST"])
@password_required
def move_to_collection():
    """
    Moves one image or film into a collection, out of wherever it was (its set or Videos, or another collection).
    to: a collection's id, or new: the name of one to make for it. Only ever into a collection.
    """
    data = request.get_json(silent=True) or {}
    try:
        item = _item_from(data)
        new_name = _clean_name(data["new"]) if data.get("new") else None
    except ValueError as e:
        return {"ok": False, "error": str(e)}, 400
    with run_queue.lock:
        refused = _why_not_movable(item)
        if refused:
            return refused
        with _lock:
            collections = _read()
            if new_name:
                target = {"id": f"c_{datetime.now():%Y%m%d_%H%M%S_%f}", "name": new_name, "items": []}
                collections.append(target)
            else:
                target = _find(collections, data.get("to"))
                if not target:
                    return {"ok": False, "error": "That collection is gone."}, 404
            for collection in collections:
                collection["items"] = [i for i in collection["items"] if _key(i) != _key(item)]
            target["items"].append(item)
            _write(collections)
    _runs_cache["at"] = 0.0
    return {"ok": True, "collection": {"id": target["id"], "name": target["name"]}}


@app.route("/api/collections/<collection_id>/fold", methods=["POST"])
@password_required
def fold_collection(collection_id):
    """Keeps a collection folded or open in Output, so every device shows it as it was left."""
    folded = (request.get_json(silent=True) or {}).get("folded")
    if not isinstance(folded, bool):
        return {"ok": False, "error": "Say whether it is folded."}, 400
    with _lock:
        collections = _read()
        collection = _find(collections, collection_id)
        if not collection:
            return {"ok": False, "error": "That collection is gone."}, 404
        collection["folded"] = folded
        _write(collections)
    return {"ok": True}


@app.route("/api/collections/<collection_id>/order", methods=["POST"])
@password_required
def order_collection(collection_id):
    """
    Puts a collection's items in the order given (its thumbnail grid's arrange): the same items, each once. Its
    images and videos are albums of their own, so one album's order can come alone: the other keeps its own.
    """
    try:
        given = [_item_from(item) for item in (request.get_json(silent=True) or {}).get("items") or []]
    except (ValueError, TypeError, AttributeError) as e:
        return {"ok": False, "error": str(e) or "Say the order."}, 400
    with _lock:
        collections = _read()
        collection = _find(collections, collection_id)
        if not collection:
            return {"ok": False, "error": "That collection is gone."}, 404
        kinds = {item["kind"] for item in given}
        mine = [item for item in collection["items"] if item["kind"] in kinds]
        if sorted(map(_key, given)) != sorted(map(_key, mine)) or len(set(map(_key, given))) != len(given):
            return {"ok": False, "error": "That collection changed: open it again."}, 409
        rest = [item for item in collection["items"] if item["kind"] not in kinds]
        collection["items"] = [item for item in given if item["kind"] == "image"] + [item for item in rest if item["kind"] == "image"]             + [item for item in given if item["kind"] == "film"] + [item for item in rest if item["kind"] == "film"]
        _write(collections)
    return {"ok": True}


@app.route("/api/collections/order", methods=["POST"])
@password_required
def order_collections():
    """
    Puts the collections shown in the order given, {"ids": [...]}: they take each other's places, so those not in it
    (NSFW ones in the other view, empty ones) stay where they were. An id that is gone is left out.
    """
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(id_, str) for id_ in ids) or len(set(ids)) != len(ids):
        return {"ok": False, "error": "The order is a list of the collections' ids."}, 400
    with _lock:
        collections = _read()
        known = {c["id"]: c for c in collections}
        given = [known[id_] for id_ in ids if id_ in known]
        slots = [number for number, c in enumerate(collections) if c["id"] in {g["id"] for g in given}]
        for number, collection in zip(slots, given):
            collections[number] = collection
        _write(collections)
    return {"ok": True}


@app.route("/api/collections/<collection_id>/delete", methods=["POST"])
@password_required
def delete_collection(collection_id):
    """Deletes a collection and what is in it, as deleting each one would. Stops at the first that can't go now."""
    from panel import image as image_panel
    with _lock:
        collection = _find(_read(), collection_id)
    if not collection:
        return {"ok": False, "error": "That collection is gone."}, 404
    for item in list(collection["items"]):
        if item["kind"] == "image":
            state = image_panel.RunState.load(item["run"])
            position = next((i for i, s in enumerate(state.shots if state else [], 1) if s.get("file") == item["file"]), None)
            reply = image_panel.delete_image(item["run"], position) if position else {"ok": True}
        else:
            path = os.path.join(FOLDERS["video"], item["name"])
            reply = PIPELINES["video"].delete_video("video", path) if os.path.isfile(path) else {"ok": True}
            if (reply[0] if isinstance(reply, tuple) else reply).get("ok"):
                for queue in server.QUEUES.values():
                    queue.forget(film=item["name"])
        body = reply[0] if isinstance(reply, tuple) else reply
        if not body.get("ok"):
            return reply
        with _lock:
            collections = _read()
            left = _find(collections, collection_id)
            if left:
                left["items"] = [i for i in left["items"] if _key(i) != _key(item)]
                _write(collections)
    with _lock:
        _write([c for c in _read() if c["id"] != collection_id])
    _runs_cache["at"] = 0.0
    return {"ok": True}


# --- An upscale of an item in a collection goes in the same collection ---

def follow_upscale(item, outcome, state, position, film):
    """Called as a job ends (server.RECORD_HOOKS): an image or film upscaled from one in a collection joins it there."""
    if outcome != "done":
        return
    argv = item.get("argv") or []
    flag = lambda name: argv[argv.index(name) + 1] if name in argv[:-1] else None
    if "pipelines.image.upscale" in argv and state and flag("--file"):
        source = {"kind": "image", "run": state.id, "file": flag("--file")}
        # It goes in right after the image it was made from: the newest upscale of it is the one there.
        at = next((i for i, shot in enumerate(state.shots or []) if shot.get("file") == source["file"]), None)
        made = state.shots[at + 1].get("file") if at is not None and at + 1 < len(state.shots) else None
        added = {"kind": "image", "run": state.id, "file": made} if made else None
    elif "pipelines.video.upscale" in argv and film and flag("--film"):
        source, added = {"kind": "film", "name": flag("--film")}, {"kind": "film", "name": film}
    else:
        return
    with _lock:
        collections = _read()
        home = next((c for c in collections if any(_key(i) == _key(source) for i in c["items"])), None)
        if home and added and not any(_key(i) == _key(added) for i in home["items"]):
            home["items"].append(added)
            _write(collections)


server.RECORD_HOOKS.append(follow_upscale)
server.STATUS_HOOKS.append(apply)
