"""
What a run can change in an image workflow besides its prompt, images and size, and making the workflow with
those changes. Community workflows such as LatentHeart's Krea2 SFW/NSFW one are built for switching parts on
and off in ComfyUI's editor: groups that rgthree's Fast Groups Bypasser turns on and off (2nd pass, upscaler,
grain, sharpen...), a choice on a group's subgraph (the upscaler's resolution), LoRAs in rgthree's Power Lora
Loader, and the Krea2T Enhancer's prompt-adherence boost. ComfyUI's own templates put theirs on a subgraph's
face instead: Krea-2's enable_lora with its LoRA and strength, Qwen-Image-Edit's enable_turbo_mode. MiniMax H3's
template leaves a named Boolean on the canvas, Enable Lightning LoRA, that picks the turbo LoRA and its steps. And
any workflow whose sampler's (or scheduler's) steps can be found gets Steps. Each becomes an option on the form;
turbo and Steps are marked advanced, for the form's Advanced part, on every side.

The editor bypasses a group by setting its nodes' mode, and that changes which nodes the API gets, so a run
with options makes its workflow again from what was saved (core/saved_workflows.py keeps a copy for it).

Each option is {id, kind, label, default, ...}, and a run's choice is a string:
    switch    "1" or "0": a group on or off, or a switch on a subgraph's face
    choice    one of its choices: a value on a subgraph, shown with the switch it goes with
    number    a number: a strength that goes with a switch, or the sampler's steps
    strength  "0" for off, or the strength: a LoRA, or the Krea2T Enhancer
"""
import copy
import json
import os
import re

from core import lora_check, run_form
from core import saved_workflows as sw

BYPASSERS = ("Fast Groups Bypasser (rgthree)", "Fast Groups Muter (rgthree)")
# LiteGraph's group colours, as rgthree's matchColors names them.
COLOR_NAMES = {"red": "#a88", "brown": "#b06634", "green": "#8a8", "blue": "#88a", "pale_blue": "#3f789e",
               "cyan": "#8aa", "purple": "#a1309b", "yellow": "#b58b2a", "black": "#444"}
# The pipeline writes the prompt and sets the size itself, so the groups that would are its own to set: a prompt
# writer or enhancer stays off, and what sizes the image stays as saved.
PROMPT_GROUPS = re.compile(r"prompt", re.I)
SIZE_GROUPS = re.compile(r"image size|resolution", re.I)
LORA_LOADER = "Power Lora Loader (rgthree)"
ENHANCER = "ComfyUI-Krea2T-Enhancer"
CHOOSER = "CustomCombo"
ON, OFF = "1", "0"
BYPASSED = 4
# What a subgraph's face sets that isn't for the form: what the pipeline sets itself (prompt, size, seed), the
# settings of a prompt writer it keeps off, and which model files it loads.
FACE_SKIP = re.compile(r"prompt|enhance|refine|thinking|max_tok|max_length|width|height|seed|unet|clip|vae|ckpt|trigger"
                       r"|text.?to.?video|duration|length|frames|fps|audio", re.I)
# The two ways a workflow can write its own prompt, offered beside Gemini and the local model on the Image side: a prompt
# enhancer that expands yours, and image to prompt, which describes a picture. Each is a group, or for the enhancer
# a Refine Prompt switch as Krea-2's template has. On Video and Shorts the LLM always writes them, so they stay off.
ENHANCER_GROUP = re.compile(r"enhanc", re.I)
# A group's switch said as what it does, where its title in the workflow is a single word: the id stays the title's,
# so what was chosen and saved keeps working.
GROUP_LABELS = {"noise": "Add noise (film grain)"}
IMAGE_TO_PROMPT = re.compile(r"image.?to.?prompt|img.?2.?prompt|caption", re.I)
REFINE_SWITCH = re.compile(r"refine|enhance", re.I)
ROLES = ("prompt_enhancer", "image_to_prompt")
# "PE", ComfyUI's MiniMax H3 Image templates' name for their prompt enhancer: enable_pe on a face, a Boolean "PE?".
PE_SWITCH = re.compile(r"(?:^|[\s_])pe(?:$|[\s_?])", re.I)
# Said as the H3 one in the form, beside a workflow's other prompt writers.
H3_ENHANCER_LABEL = "Prompt enhancer H3"
# Words a switch's name has that say nothing about what it switches.
SWITCH_WORDS = {"enable", "enabled", "use", "mode", "on"}
MOST_STEPS = 150
# A switch left on the canvas as a named Boolean, as ComfyUI's MiniMax H3 template has "Boolean (Enable Lightning
# LoRA)": it picks the turbo LoRA and its step count through If/Else switches. Offered under Advanced, with Steps.
PRIMITIVE_SWITCH = "PrimitiveBoolean"
TYPE_IN_TITLE = re.compile(r"\s*(?:boolean|bool)\s*\((.+)\)\s*", re.I)
TURBO_WORDS = re.compile(r"lightning|lightx|turbo|\d+.?steps?\b", re.I)


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "option"


def _inside(node, group):
    x, y = (node.get("pos") or [0, 0])[:2]
    left, top, width, height = group["bounding"]
    return left <= x <= left + width and top <= y <= top + height


def _switched_groups(ui):
    """The groups a Fast Groups Bypasser in the workflow turns on and off: by title, colour, or both if it says both."""
    rules = []
    for node in ui["nodes"]:
        if node["type"] in BYPASSERS and not node.get("mode"):
            found = node.get("properties") or {}
            colors = [COLOR_NAMES.get(name.strip().lower(), name.strip().lower()) for name in (found.get("matchColors") or "").split(",") if name.strip()]
            rules.append((found.get("matchTitle") or "", colors))
    switched = []
    for group in ui.get("groups", []):
        title, color = group.get("title") or "", (group.get("color") or "").lower()
        for pattern, colors in rules:
            try:
                by_title = not pattern or re.search(pattern, title, re.I)
            except re.error:
                by_title = False
            # One with neither would switch every group, which isn't a part of the workflow worth offering.
            if (pattern or colors) and by_title and (not colors or color in colors):
                switched.append(group)
                break
    return switched


def _subgraphs(ui):
    return {subgraph["id"]: subgraph for subgraph in ui.get("definitions", {}).get("subgraphs", [])}


def _face_choices(instance, subgraph, prefix, label):
    """A choice set on a subgraph's face that feeds a Custom Combo inside it, with that combo's list."""
    found = []
    widgets = sw._face_widgets(instance, subgraph)
    combos = {node["id"]: node for node in subgraph.get("nodes", []) if node["type"] == CHOOSER}
    for link in map(sw._link_row, subgraph.get("links", [])):
        if link[1] != sw.SUBGRAPH_IN or link[3] not in combos:
            continue
        name = subgraph["inputs"][link[2]]["name"]
        values = combos[link[3]].get("widgets_values") or []
        choices = [value for value in values[2:] if isinstance(value, str) and value]
        if name in widgets and len(choices) > 1:
            found.append({"id": f"{prefix}.{_slug(name)}", "kind": "choice", "label": f"{label}: {name}", "default": str(widgets[name]),
                          "choices": choices, "parent": prefix, "node": instance["id"], "input": name})
    return found


def _words(label):
    return _spelled_out(" ".join(label.replace("_", " ").split()).capitalize().replace("Lora", "LoRA").replace("lora", "LoRA"))


def _spelled_out(label):
    """
    "PE" in ComfyUI's templates (MiniMax H3 Image's "enable_pe", "PE?") is the prompt enhancer: an LLM that rewrites the
    prompt. Said in full, without the question mark, starting with a capital.
    """
    label = re.sub(r"\bpe\b", "prompt enhancer", label, flags=re.I).rstrip("?").strip()
    return label[:1].upper() + label[1:]


def _inner_input(subgraph, slot):
    """The node type and input a subgraph's input feeds first, inside it."""
    nodes = {node["id"]: node for node in subgraph.get("nodes", [])}
    for link in map(sw._link_row, subgraph.get("links", [])):
        if link[1] == sw.SUBGRAPH_IN and link[2] == slot and link[3] in nodes:
            inputs = nodes[link[3]].get("inputs", [])
            if link[4] < len(inputs):
                return nodes[link[3]]["type"], inputs[link[4]]["name"]
    return None, None


def _face_settings(instance, subgraph, info):
    """
    The switches on a subgraph's face, as ComfyUI's templates have them (enable_lora, enable_turbo_mode), and what goes
    with each by name: lora_name and lora_strength with enable_lora. A value that goes with no switch isn't offered.
    """
    widgets = sw._face_widgets(instance, subgraph)
    # One a switch on the canvas feeds is that switch's to offer, not the face's own.
    driven = {entry["name"] for entry in instance.get("inputs", []) if entry.get("link") is not None}
    faced = [(slot, entry, entry.get("label") or entry["name"]) for slot, entry in enumerate(subgraph.get("inputs", []))
             if entry["name"] in widgets and entry["name"] not in driven and not FACE_SKIP.search(entry.get("label") or entry["name"])]
    switches = [{"id": f"face_{_slug(label)}", "kind": "switch", "label": _words(label), "default": ON if widgets[entry["name"]] else OFF,
                 "node": instance["id"], "input": entry["name"], **({"advanced": True, "speed": True} if TURBO_WORDS.search(label) else {})}
                for _, entry, label in faced if entry["type"] == "BOOLEAN" and isinstance(widgets[entry["name"]], bool)]
    # Its prompt enhancer's switch (MiniMax H3 Image's enable_pe) is chosen as what writes the prompts, not here; what
    # goes with it (its model) stays as the workflow has it.
    labels = {entry["name"]: entry.get("label") or entry["name"] for entry in subgraph.get("inputs", [])}
    enhancer = next((switch for switch in switches if PE_SWITCH.search(labels[switch["input"]])), None)
    found = [_role("prompt_enhancer", "Prompt enhancer") | {"node": switch["node"], "input": switch["input"]} if switch is enhancer else switch
             for switch in switches]
    for slot, entry, label in faced:
        words = set(_slug(label).split("_"))
        parent = next((switch for switch in switches if words & (set(switch["id"][5:].split("_")) - SWITCH_WORDS)), None)
        value = widgets[entry["name"]]
        if not parent or parent is enhancer or entry["type"] == "BOOLEAN":
            continue
        common = {"id": f"face_{_slug(label)}", "label": _words(label), "default": str(value), "parent": parent["id"],
                  "node": instance["id"], "input": entry["name"]}
        if entry["type"] == "FLOAT" and isinstance(value, (int, float)):
            found.append({**common, "kind": "number", "min": -2 if "strength" in label else 0, "max": 2 if "strength" in label else 100, "step": 0.05})
        elif entry["type"] == "COMBO":
            kind, name = _inner_input(subgraph, slot)
            spec = sw._input_spec(info.get(kind, {})).get(name) if kind else None
            choices = sw._options(spec) if spec else None
            if choices and len(choices) > 1:
                found.append({**common, "kind": "choice", "choices": [str(choice) for choice in choices]})
    return _face_lora(found, switches, labels)


def _face_lora(found, switches, labels):
    """
    A face's own LoRA (Krea-2's template: enable_lora, lora_name, lora_strength) as the LoRA setting every workflow has
    (style_lora): the same ids, under Advanced, its file listed by name.
    """
    switch = next((switch for switch in switches if FACE_LORA.fullmatch(labels[switch["input"]])), None)
    if not switch:
        return found
    children = [option for option in found if option.get("parent") == switch["id"]]
    name = next((option for option in children if option["kind"] == "choice"), None)
    strength = next((option for option in children if option["kind"] == "number"), None)
    if not name or not strength:
        return found
    trio = lora_options(switch["default"], name["default"], strength["default"], name["choices"])
    for option, place in zip(trio, (switch, name, strength)):
        option.update(node=place["node"], input=place["input"])
    return [option for option in found if option not in (switch, name, strength)] + trio


def _primitive_label(title):
    """'Boolean (Enable Lightning LoRA)' as 'Lightning LoRA (turbo)': what it switches, and that it's the fast way."""
    match = TYPE_IN_TITLE.fullmatch(title)
    words = (match.group(1) if match else title).split()
    while len(words) > 1 and words[0].lower() in SWITCH_WORDS:
        words = words[1:]
    label = _spelled_out(" ".join(words))
    return f"{label} (turbo)" if TURBO_WORDS.search(label) and "turbo" not in label.lower() else label


def _primitive_switches(ui):
    """The named Booleans on the canvas that something reads: each a switch. One for the prompt is the pipeline's."""
    used = {sw._link_row(link)[1] for link in ui.get("links", [])}
    found = []
    for node in ui["nodes"]:
        title = (node.get("title") or "").strip()
        values = node.get("widgets_values") or []
        if (node["type"] != PRIMITIVE_SWITCH or node.get("mode") or not title or node["id"] not in used
                or not values or not isinstance(values[0], bool) or REFINE_SWITCH.search(title) or FACE_SKIP.search(title)):
            continue
        if PE_SWITCH.search(title):
            # Its prompt enhancer's (MiniMax H3 Image's "PE?"): chosen as what writes the prompts.
            found.append(_role("prompt_enhancer", "Prompt enhancer") | {"node": node["id"], "primitive": True})
            continue
        label = _primitive_label(title)
        # A speed LoRA's (lightning, turbo, n-step): shown with the LoRA setting, as the other kind of LoRA.
        found.append({"id": f"switch_{_slug(label.replace('(turbo)', ''))}", "kind": "switch", "label": label,
                      "default": ON if values[0] else OFF, "node": node["id"], "primitive": True, "advanced": True,
                      **({"speed": True} if TURBO_WORDS.search(label) else {})})
    return found


def _role(role, label, group=None):
    return {"id": role, "kind": "switch", "role": "llm", "label": label, "default": OFF, **({"group": group} if group else {})}


def describe(ui, info=None, pipeline="image"):
    """The options this workflow offers, as saved. A problem with one is for the caller to find, by trying it."""
    options = []
    subgraphs = _subgraphs(ui)
    for node in ui["nodes"]:
        if node["type"] in subgraphs and not node.get("mode"):
            options += _face_settings(node, subgraphs[node["type"]], info or {})
    for group in _switched_groups(ui):
        title = group.get("title") or "Group"
        if PROMPT_GROUPS.search(title):
            role = "prompt_enhancer" if ENHANCER_GROUP.search(title) else "image_to_prompt" if IMAGE_TO_PROMPT.search(title) else None
            if pipeline == "image" and role and role not in [option["id"] for option in options]:
                options.append(_role(role, title, title))
            continue
        if SIZE_GROUPS.search(title):
            continue
        members = [node for node in ui["nodes"] if _inside(node, group) and node["type"] not in sw.NOTES + sw.EDITOR_ONLY]
        if not members:
            continue
        group_id = f"group_{_slug(title)}"
        options.append({"id": group_id, "kind": "switch", "label": GROUP_LABELS.get(title.strip().lower(), title), "default": OFF if all(node.get("mode") == BYPASSED for node in members) else ON})
        for node in members:
            if node["type"] in subgraphs:
                options += _face_choices(node, subgraphs[node["type"]], group_id, title)
    for node in ui["nodes"]:
        if node["type"] == LORA_LOADER and not node.get("mode"):
            loras = [value for value in node.get("widgets_values") or [] if isinstance(value, dict) and value.get("lora")]
            # Its first is the LoRA setting (style_lora), with the one it has as the one to start from; any more are
            # each a switch of their own, as before.
            if loras and not any(option["id"] == LORA for option in options):
                first = loras[0]
                trio = lora_options(ON if first.get("on") else OFF, _installed_lora(info or {}, first["lora"]), str(first.get("strength", 1) or 1),
                                    _lora_files(info or {}))
                for option in trio:
                    option.update(node=node["id"], entry="lora_1")
                options += trio
            for number, lora in enumerate(loras[1:], 2):
                name = os.path.splitext(os.path.basename(str(lora["lora"]).replace("\\", "/")))[0]
                options.append({"id": f"lora_{_slug(name)}", "kind": "strength", "label": f"LoRA: {name}", "node": node["id"], "entry": f"lora_{number}",
                                "default": str(lora.get("strength", 1)) if lora.get("on") else OFF, "min": -2, "max": 2, "step": 0.05,
                                "usual": str(lora.get("strength", 1) or 1)})
        elif node["type"] == ENHANCER and not node.get("mode"):
            enabled, strength = (list(node.get("widgets_values") or []) + [True, 1.0])[:2]
            options.append({"id": "prompt_boost", "kind": "strength", "label": "Krea2T Enhancer (prompt adherence)", "node": node["id"],
                            "default": str(strength) if enabled else OFF, "min": 0, "max": 2, "step": 0.05, "usual": str(strength or 1)})
    options += _primitive_switches(ui)
    every = list(ui["nodes"]) + [node for subgraph in subgraphs.values() for node in subgraph.get("nodes", [])]
    if pipeline == "image" and "prompt_enhancer" not in [option["id"] for option in options] and any(
            node["type"] == "PrimitiveBoolean" and REFINE_SWITCH.search(node.get("title") or "") for node in every):
        options.append(_role("prompt_enhancer", "Prompt enhancer"))
    if any(node["type"].startswith(H3_IMAGE) for node in every):
        for option in options:
            if option["id"] == "prompt_enhancer":
                option.update(label=H3_ENHANCER_LABEL, named=True)
    options += _turbo_lora(ui, options, info or {})
    return options


def _speed_loaders(ui):
    """
    The Load LoRA nodes of a workflow whose file is a speed LoRA (turbo, lightning, n-step), on the canvas or inside a
    subgraph: [(id of the subgraph holding it or None, node)].
    """
    found = [(None, node) for node in ui["nodes"]]
    found += [(subgraph["id"], node) for subgraph in ui.get("definitions", {}).get("subgraphs", []) for node in subgraph.get("nodes", [])]
    return [(scope, node) for scope, node in found if node["type"] in LORA_LOADERS and not node.get("mode")
            and isinstance(node.get("widgets_values"), list) and len(node["widgets_values"]) > 1
            and SPEED_LORA.search(str(node["widgets_values"][0]))]


def _turbo_lora(ui, options, info):
    """
    The turbo LoRA's file and strength, under its switch, as the LoRA setting has them under Use LoRA: the one the
    workflow has to start from, any speed LoRA installed to choose. For a workflow with one such switch and one such
    loader: it is the loader's file and strength that are set (lora_widget 0 and 1). Returns the options it adds.
    """
    switches = [option for option in options if option.get("speed") and option["kind"] == "switch"]
    loaders = _speed_loaders(ui)
    if len(switches) != 1 or len(loaders) != 1:
        return []
    switch, (scope, loader) = switches[0], loaders[0]
    linked = {entry["name"] for entry in loader.get("inputs", []) if entry.get("link") is not None}
    # A file or strength something else sets (a switch, a primitive) isn't this node's to choose.
    if "lora_name" in linked:
        return []
    name, strength = _installed_lora(info, loader["widgets_values"][0]), loader["widgets_values"][1]
    # Of the speed LoRAs installed, the ones for this model: a speed LoRA is made for one.
    choices = sorted({file for file in _lora_files(info) if SPEED_LORA.search(file)} | {name}, key=lambda file: lora_label(file).lower())
    switch["below"] = True
    where = {"lora_node": loader["id"], "lora_scope": scope, "advanced": True, "speed": True, "parent": switch["id"]}
    found = [{"id": f"{switch['id']}_name", "kind": "choice", "label": "LoRA", "choices": choices, "default": name,
              "labels": {file: speed_label(file) for file in choices}, "lora_widget": 0, **where}]
    if not linked & {"strength_model", "strength"}:
        found.append({"id": f"{switch['id']}_strength", "kind": "number", "label": "Strength", "default": f"{float(strength):g}", "min": -2, "max": 2,
                      "step": 0.05, "lora_widget": 1, **where})
    return found


def _set_mode(ui, node, mode):
    node["mode"] = mode
    # The editor sets a subgraph's insides with it, and the saved file has them that way.
    for subgraph in ui.get("definitions", {}).get("subgraphs", []):
        if subgraph["id"] == node["type"]:
            for inner in subgraph.get("nodes", []):
                inner["mode"] = mode


def _before(ui, options, chosen):
    """The saved workflow with the groups and face choices as chosen, and every prompt writer or enhancer off."""
    ui = copy.deepcopy(ui)
    for group in _switched_groups(ui):
        title = group.get("title") or ""
        # By its id, not its label: a group said as what it does ("Noise" as "Add noise (film grain)") was never found,
        # so choosing it did nothing. A prompt writer's group is found by its title, its label.
        option = next((option for option in options if option["kind"] == "switch" and (option["id"] == f"group_{_slug(title)}"
                                                                                       or option.get("role") and option["label"] == title)), None)
        if option and option.get("role"):
            wanted = chosen.get(option["id"], OFF)
        else:
            wanted = OFF if PROMPT_GROUPS.search(title) else chosen.get(option["id"], option["default"]) if option else None
        if wanted is None:
            continue
        for node in ui["nodes"]:
            if _inside(node, group) and node["type"] not in sw.NOTES + sw.EDITOR_ONLY:
                _set_mode(ui, node, 0 if wanted == ON else BYPASSED)
    nodes = {node["id"]: node for node in ui["nodes"]}
    subgraphs = _subgraphs(ui)
    for option in options:
        # A named Boolean on the canvas: set before the workflow is made, as the Image side settles switches then.
        # A prompt writer is off unless chosen, as a group of one is.
        picked = chosen.get(option["id"], OFF) if option.get("role") else chosen.get(option["id"])
        if option.get("primitive") and picked is not None and option["node"] in nodes:
            nodes[option["node"]]["widgets_values"][0] = picked == ON
            continue
        # A value on a subgraph's face: a choice, a switch or a number there.
        if "input" in option and picked is not None and option["node"] in nodes:
            node = nodes[option["node"]]
            names = (sw.face_names(node, subgraphs[node["type"]]) if node["type"] in subgraphs
                     else [entry["widget"]["name"] for entry in node.get("inputs", []) if "widget" in entry])
            values = node.get("widgets_values")
            value = picked
            value = value == ON if option["kind"] == "switch" else float(value) if option["kind"] == "number" else value
            if isinstance(values, list) and option["input"] in names and names.index(option["input"]) < len(values):
                values[names.index(option["input"])] = value
        # The turbo LoRA's file and strength: on the Load LoRA node, wherever it is.
        if "lora_widget" in option and picked is not None:
            holders = ui["nodes"] if option["lora_scope"] is None else next(
                (subgraph["nodes"] for subgraph in subgraphs.values() if subgraph["id"] == option["lora_scope"]), [])
            loader = next((node for node in holders if node["id"] == option["lora_node"]), None)
            if loader:
                loader["widgets_values"][option["lora_widget"]] = float(picked) if option["kind"] == "number" else picked
    return ui


def _flag(api, value):
    """A switch's on or off: as set, or from the Boolean it reads. None if that can't be told."""
    if isinstance(value, list):
        value = api.get(value[0], {}).get("inputs", {}).get("value")
    return value if isinstance(value, bool) else None


def _number_source(api, node_id, name, depth=0, kinds=(int,)):
    """Where the number an input takes is set: [node id, input], through a primitive or the side a switch takes. Or None."""
    value = api.get(node_id, {}).get("inputs", {}).get(name)
    if type(value) in kinds:
        return [node_id, name]
    if not isinstance(value, list) or depth > 4:
        return None
    source = api.get(value[0], {}).get("inputs", {})
    if type(source.get("value")) in kinds:
        return [value[0], "value"]
    if api.get(value[0], {}).get("class_type") in sw.SWITCHES:
        on = _flag(api, source.get("switch"))
        return None if on is None else _number_source(api, value[0], "on_true" if on else "on_false", depth + 1, kinds)
    return None


def _text_source(api, node_id, name):
    """[node id, input] if the input holds its text itself, rather than taking it from another node. Or None."""
    return [node_id, name] if isinstance(api.get(node_id, {}).get("inputs", {}).get(name), str) else None


def _distinct(found):
    return [target for number, target in enumerate(found) if target and target not in found[:number]]


def _combo(info, class_type, name):
    """The values ComfyUI offers this node's input, or []."""
    inputs = sw._input_spec(info.get(class_type, {}))
    return list(sw._options(inputs[name]) or []) if name in inputs else []


FLOATS = (int, float)
MOST_CFG = 30
MOST_TEXT = 4000
FOLLOWERS = ("steps", "cfg", "sampler", "scheduler")
NEGATIVE_TEXT = ("CLIPTextEncode",)
LTX_FPS = "LTXVConditioning"
DISTILLED = "The workflow sets its own steps with fixed sigmas, as a distilled one does."
H3_MEMORY, H3_SPARSE = "H3MemoryOptimization", "H3SparseAttention"
H3_IMAGE = "MiniMaxH3Image"
H3_SAMPLING = ("BasicGuider", "CFGGuider", "KSampler", "KSamplerAdvanced", "SamplerCustom", "MiniMaxH3MotionDirector")


# --- The LoRA setting every workflow has (under Advanced) ---
# One LoRA, its file and strength, wherever the workflow takes it: the first row of its Power Lora Loader, its face's
# enable_lora (Krea-2's template), or else a Load LoRA put in before what samples. So a LoRA dropped in ComfyUI's
# models/loras is offered at once, on any workflow. The one the workflow has is the one to start from: most LoRAs are
# made for one model. Speed LoRAs (turbo, lightning, n-step) have switches of their own, and aren't listed.
LORA, LORA_NAME, LORA_STRENGTH = "lora", "lora_name", "lora_strength"
LORA_LOADERS = ("LoraLoaderModelOnly", "LoraLoader")
SPEED_LORA = re.compile(r"turbo|lightning|lightx2v|\d+.?steps?|distill", re.I)
FACE_LORA = re.compile(r"(?:enable|use)?[\s_]*loras?", re.I)
# A copy saved twice ("_1", " (1)"): said as the one it is.
DOWNLOAD_COPY = re.compile(r"(?:_1|\s*\(1\))$")
# What earlier runs chose, before the LoRA setting: Add a LoRA (LTX's empty loader), and a face's own.
OLD_LORA_IDS = {"lora_slot": LORA_NAME, "lora_slot_strength": LORA_STRENGTH, "face_enable_lora": LORA, "face_lora_name": LORA_NAME,
                "face_lora_strength": LORA_STRENGTH}


def lora_label(name):
    """A LoRA file as it's said: its folder and name, without .safetensors or a download's "_1"."""
    stem = os.path.splitext(str(name).replace("\\", "/"))[0]
    return DOWNLOAD_COPY.sub("", stem)


def speed_label(name, limit=28):
    """A turbo LoRA as the picker says it: no folder, and cut in the middle to fit one line."""
    short = lora_label(os.path.basename(str(name).replace("\\", "/")))
    if len(short) <= limit:
        return short
    head = (limit - 1) // 2 + (limit - 1) % 2
    return f"{short[:head]}…{short[-(limit - 1 - head):]}"


def _lora_files(info):
    """The LoRAs ComfyUI has, as its Load LoRA lists them."""
    return list(dict.fromkeys(_combo(info, "LoraLoader", "lora_name") + _combo(info, "LoraLoaderModelOnly", "lora_name")))


def _installed_lora(info, name):
    """The installed file a workflow's LoRA is: saved under a folder of its author's, it may be installed without one."""
    files = _lora_files(info)
    if name in files:
        return name
    wanted = os.path.basename(str(name).replace("\\", "/"))
    return next((file for file in files if os.path.basename(file.replace("\\", "/")) == wanted), name)


def lora_options(on, name, strength, files):
    """The switch, and under it the LoRA (named as lora_label says) and its strength. Speed LoRAs aren't listed."""
    choices = sorted({file for file in files if not SPEED_LORA.search(file)} | ({name} if name else set()), key=lambda file: lora_label(file).lower())
    default = name if name in choices else (choices[0] if choices else "")
    return [{"id": LORA, "kind": "switch", "label": "Use LoRA", "default": on, "advanced": True, "below": True},
            {"id": LORA_NAME, "kind": "choice", "label": "LoRA", "parent": LORA, "choices": choices, "default": default,
             "labels": {file: lora_label(file) for file in choices}, "advanced": True},
            {"id": LORA_STRENGTH, "kind": "number", "label": "Strength", "parent": LORA, "default": f"{float(strength):g}", "min": -2, "max": 2,
             "step": 0.05, "advanced": True}]


def upgraded(chosen, options):
    """
    What an earlier run chose for its LoRA, as the LoRA setting has it now: Add a LoRA, a face's enable_lora, or the
    first Power Lora Loader row's own switch ("lora_<its name>": its strength, or 0 for off).
    """
    chosen = dict(chosen or {})
    known = {option["id"] for option in options}
    for old, new in OLD_LORA_IDS.items():
        if old in chosen and new not in chosen and old not in known:
            value = chosen.pop(old)
            if old == "lora_slot":
                if value != "None":
                    chosen.update({LORA: ON, LORA_NAME: value})
            else:
                chosen[new] = value
    name = next((option for option in options if option["id"] == LORA_NAME), None)
    if name:
        old = f"lora_{_slug(os.path.splitext(os.path.basename(str(name['default']).replace(chr(92), '/')))[0])}"
        if old in chosen and old not in {option["id"] for option in options}:
            value = chosen.pop(old)
            chosen[LORA] = OFF if value == OFF else ON
            if value != OFF:
                chosen[LORA_STRENGTH] = value
    return chosen


def _model_feeds(api):
    """Where what samples takes its model from: [(node id, input)], or [] when that isn't one place."""
    takers = [(node_id, "model") for node_id, node in api.items() if isinstance(node["inputs"].get("model"), list)
              and ("positive" in node["inputs"] or node["class_type"] in H3_SAMPLING or node["class_type"].endswith("Guider"))]
    sources = {tuple(api[node_id]["inputs"]["model"]) for node_id, _ in takers}
    return takers if len(sources) == 1 else []


def _style_lora(api, info, chosen, options):
    """
    The LoRA setting, applied: to its Power Lora Loader row, or (with none and no face of its own) to an empty Power
    Lora Loader, or a Load LoRA put in before what samples. Returns the options it adds.
    """
    files = _lora_files(info)
    found = [option for option in options if option["id"] in (LORA, LORA_NAME, LORA_STRENGTH)]
    if found:
        switch = found[0]
        if "entry" in switch and str(switch["node"]) in api:
            on = chosen.get(LORA, switch["default"]) == ON
            name = chosen.get(LORA_NAME, found[1]["default"])
            strength = float(chosen.get(LORA_STRENGTH, found[2]["default"]))
            api[str(switch["node"])]["inputs"][switch["entry"]] = {"on": on, "lora": _installed_lora(info, name), "strength": strength, "strengthTwo": None}
        return []
    # A face with a LoRA switch of its own that isn't the setting (no file list on it): that one stays the way to it.
    if not files or not any(name in info for name in LORA_LOADERS) or any(
            option.get("input") and option["kind"] == "switch" and "lora" in option["id"] for option in options):
        return []
    added = lora_options(OFF, None, 1, files)
    if chosen.get(LORA) != ON:
        return added
    name, strength = chosen.get(LORA_NAME, added[1]["default"]), float(chosen.get(LORA_STRENGTH, 1))
    loaders = [node_id for node_id, node in api.items() if node["class_type"] == LORA_LOADER]
    if len(loaders) == 1:
        api[loaders[0]]["inputs"]["lora_1"] = {"on": True, "lora": name, "strength": strength, "strengthTwo": None}
        return added
    feeds = _model_feeds(api)
    if not feeds or "LoraLoaderModelOnly" not in info:
        raise sw.Unusable("There's no one place in this workflow to put a LoRA: give it a Power Lora Loader in ComfyUI.")
    api["style_lora"] = {"class_type": "LoraLoaderModelOnly", "_meta": {"title": "LoRA"},
                         "inputs": {"lora_name": name, "strength_model": strength, "model": list(api[feeds[0][0]]["inputs"]["model"])}}
    for node_id, input_name in feeds:
        api[node_id]["inputs"][input_name] = ["style_lora", 0]
    return added


def _constant(api, value, depth=0):
    """A number as set, or read from the constant it comes from (Float Constant, a primitive). None if it isn't one."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, list) and depth < 4 and value[0] in api:
        inputs = api[value[0]]["inputs"]
        return _constant(api, inputs.get("value", inputs.get("number")), depth + 1) if len(inputs) == 1 else None
    return None


def _drop_idle_loras(api):
    """
    A Load LoRA at strength 0 (a turbo LoRA switched off by its strength, as MiniMax H3's template has it) changes
    nothing: it's taken out, its model passed straight on, so what runs and its pills hold only LoRAs in use.
    """
    for node_id, node in list(api.items()):
        if node["class_type"] not in LORA_LOADERS or not isinstance(node["inputs"].get("model"), list):
            continue
        strengths = [_constant(api, node["inputs"].get(name)) for name in ("strength_model", "strength_clip") if name in node["inputs"]]
        if strengths and all(strength == 0 for strength in strengths):
            sw._replace_uses(api, node_id, 0, node["inputs"]["model"])
            if node["class_type"] == "LoraLoader" and isinstance(node["inputs"].get("clip"), list):
                sw._replace_uses(api, node_id, 1, node["inputs"]["clip"])
            del api[node_id]


def _negatives(api):
    """Where a negative prompt is typed, if one node has it: [node id, input]. Or None."""
    positive = {value[0] for node in api.values() for name, value in node["inputs"].items() if name == "positive" and isinstance(value, list)}
    found = [[node_id, "text"] for node_id, node in api.items() if node["class_type"] in NEGATIVE_TEXT and node_id not in positive
             and isinstance(node["inputs"].get("text"), str)
             and any(isinstance(value, list) and value[0] == node_id for other in api.values() for name, value in other["inputs"].items() if name == "negative")]
    found += [[node_id, "negative_prompt"] for node_id, node in api.items() if isinstance(node["inputs"].get("negative_prompt"), str)]
    return found[0] if len(found) == 1 else None


def _tune(api, info, chosen):
    """
    What the sampling takes, wherever the graph has it: sampler, scheduler and CFG (under Steps), the negative prompt,
    and for LTX its frame rate, image strength, NAG scale and a LoRA to add. Applies what's chosen. Returns the options.
    """
    options = []
    locked = any(node["class_type"] == "ManualSigmas" for node in api.values())

    def offer(option, targets, value=str):
        option = {"advanced": True, **option, "default": str(api[targets[0][0]]["inputs"][targets[0][1]])}
        if locked and option.get("parent") == "steps":
            option["problem"] = DISTILLED
        options.append(option)
        # Only what differs from the workflow: its own value stays as it has it (1, not 1.0).
        if option["id"] in chosen and str(chosen[option["id"]]) != option["default"] and not option.get("problem"):
            for node_id, name in targets:
                api[node_id]["inputs"][name] = value(chosen[option["id"]])

    main = _main_targets(api)
    for name, label in (("sampler_name", "Sampler"), ("scheduler", "Scheduler")):
        targets = _distinct([_text_source(api, node_id, name) for node_id, node in api.items() if name in node["inputs"]])
        # More than one (a 2nd pass, a sampler fed its own): the main sampler's, the one that makes the picture.
        if not (len(targets) == 1 or locked):
            targets = [main[name]] if main.get(name) else []
        choices = _combo(info, api[targets[0][0]]["class_type"], name) if targets else []
        if choices:
            offer({"id": name.split("_")[0], "kind": "choice", "label": label, "parent": "steps", "choices": choices}, targets[:1])
    cfg = _distinct([_number_source(api, node_id, "cfg", kinds=FLOATS) for node_id, node in api.items() if "cfg" in node["inputs"]])
    if not (len(cfg) == 1 or locked):
        cfg = [main["cfg"]] if main.get("cfg") else []
    if cfg:
        offer({"id": "cfg", "kind": "number", "label": "CFG", "parent": "steps", "min": 0, "max": MOST_CFG, "step": 0.1}, cfg[:1], float)
    negative = _negatives(api)
    # With the CFG fixed at 1 by distilled sigmas, a negative prompt is never used, unless NAG reads it.
    if negative and (not locked or any(node["class_type"] == "LTX2_NAG" for node in api.values())):
        offer({"id": "negative", "kind": "text", "label": "Negative prompt"}, [negative])
    if any(node["class_type"] == LTX_FPS for node in api.values()):
        fps = _distinct([_number_source(api, node_id, "frame_rate", kinds=FLOATS) for node_id, node in api.items() if "frame_rate" in node["inputs"]])
        if len(fps) == 1:
            offer({"id": "fps", "kind": "number", "label": "Frames per second", "min": 1, "max": 120, "step": 1}, fps, float)
    strength = _distinct([_number_source(api, node_id, "strength", kinds=FLOATS) for node_id, node in api.items()
                          if node["class_type"] in ("LTXVImgToVideoInplace", "LTXVImgToVideo")])
    if strength:
        offer({"id": "image_strength", "kind": "number", "label": "Image strength", "min": 0, "max": 1, "step": 0.05}, strength, float)
    nag = _distinct([_number_source(api, node_id, "nag_scale", kinds=FLOATS) for node_id, node in api.items() if node["class_type"] == "LTX2_NAG"])
    if nag:
        offer({"id": "nag_scale", "kind": "number", "label": "NAG scale", "min": 0, "max": MOST_CFG, "step": 0.5}, nag, float)
    options += _h3(api, info, chosen)
    options += _h3_fastvideo(api, info, chosen)
    options += _h3_latent_upscale(api, info, chosen)
    return options


# MiniMax H3's latent upscaler (Comfyui_Minimax_h3_latent_Upscaler): the clip is made at the size chosen, its video latent
# made bigger, then a short second pass draws the detail in at the new size. How much it draws again is the preset: the
# first sigma of that pass, out of the H3 turbo schedule (0.9231, 0.8780, 0.8000, 0.6316, 0.3158, 0).
H3_UPSCALER = "MinimaxH3LatentUpscaler3D"
NO_UPSCALE = "Off"
LATENT_UPSCALES = {
    "Clean": "0.3158, 0.0000",  # Sharper at the new size, the clip as it was: one light step
    "Hires fix": "0.6316, 0.3158, 0.0000",  # Detail added (skin, hair, texture), about a 0.35 denoise
    "Heavy": "0.8000, 0.6316, 0.3158, 0.0000",  # Reworked more, about 0.45: more new detail, a little drift
}
UPSCALE_MEGAPIXELS = (0.5, 4.0, 1.0)  # least, most, usual
# Custom: how much is drawn again (the refine pass's first sigma), in how many steps, with which sampler.
CUSTOM_UPSCALE = "Custom"
SAME_SAMPLER = "Same as the clip"


def custom_sigmas(denoise, steps):
    """Evenly from denoise down to 0 in steps: "0.5000, 0.2500, 0.0000" for 0.5 in 2."""
    return ", ".join(f"{denoise * (steps - i) / steps:.4f}" for i in range(steps + 1))


def _upscaler_model(info):
    """The upscaler's weights: BF16 where there is one (as small as FP16, and what a 30-series card runs natively)."""
    # The folder is shared: LTX's spatial upscaler sits there too, and isn't one for H3.
    names = [name for name in _combo(info, H3_UPSCALER, "model_name") if "minimax_h3" in name.lower()]
    return next((name for name in names if "bf16" in name.lower()), names[0] if names else None)


def _h3_decoders(api):
    """The VAE decoders fed by one H3 SamplerCustomAdvanced, and that sampler's output: ([node ids], link), or ([], None)."""
    if not any(node["class_type"].startswith("MiniMaxH3") for node in api.values()):
        return [], None
    decoders = [node_id for node_id, node in api.items() if node["class_type"] in ("VAEDecode", "VAEDecodeAudio", "VAEDecodeTiled")
                and isinstance(node["inputs"].get("samples"), list)
                and api.get(node["inputs"]["samples"][0], {}).get("class_type") == "SamplerCustomAdvanced"]
    links = {tuple(api[node_id]["inputs"]["samples"]) for node_id in decoders}
    return (decoders, list(next(iter(links)))) if len(links) == 1 else ([], None)


def _h3_latent_upscale(api, info, chosen):
    """
    The latent upscaler, for an H3 workflow that samples with SamplerCustomAdvanced and decodes what it made (the
    reference-to-video ones; Motion Director samples inside its own node, so it has no latent to give).
    """
    model = _upscaler_model(info) if all(name in info for name in (H3_UPSCALER, "LTXVSeparateAVLatent", "LTXVConcatAVLatent", "ManualSigmas")) else None
    decoders, made = _h3_decoders(api)
    if not model or not made:
        return []
    least, most, usual = UPSCALE_MEGAPIXELS
    samplers = _combo(info, "KSamplerSelect", "sampler_name")
    options = [{"id": "latent_upscale", "kind": "choice", "label": "Latent upscale", "choices": [NO_UPSCALE, *LATENT_UPSCALES, CUSTOM_UPSCALE],
                "default": NO_UPSCALE},
               {"id": "latent_upscale_mp", "kind": "number", "label": "Upscale to (MP)", "parent": "latent_upscale",
                "default": f"{usual:g}", "min": least, "max": most, "step": 0.1},
               {"id": "latent_upscale_denoise", "kind": "number", "label": "Denoise", "parent": "latent_upscale", "default": "0.5",
                "min": 0.05, "max": 1, "step": 0.05},
               {"id": "latent_upscale_steps", "kind": "number", "label": "Refine steps", "parent": "latent_upscale", "default": "3",
                "min": 1, "max": 12, "step": 1},
               {"id": "latent_upscale_chunking", "kind": "switch", "label": "Temporal chunking (less VRAM)", "parent": "latent_upscale", "default": ON}]
    if samplers:
        options.append({"id": "latent_upscale_sampler", "kind": "choice", "label": "Refine sampler", "parent": "latent_upscale",
                        "choices": [SAME_SAMPLER, *samplers], "default": SAME_SAMPLER})
    preset = chosen.get("latent_upscale", NO_UPSCALE)
    if preset not in LATENT_UPSCALES and preset != CUSTOM_UPSCALE:
        return options
    custom = preset == CUSTOM_UPSCALE
    if custom:
        denoise = min(1.0, max(0.05, float(chosen.get("latent_upscale_denoise", 0.5))))
        sigmas = custom_sigmas(denoise, min(12, max(1, int(float(chosen.get("latent_upscale_steps", 3))))))
    else:
        sigmas = LATENT_UPSCALES[preset]
    sampler = api[made[0]]
    megapixels = min(most, max(least, float(chosen.get("latent_upscale_mp", usual))))
    api["lu_split"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": made}, "_meta": {"title": "Latent upscale: split"}}
    api["lu_upscale"] = {"class_type": H3_UPSCALER, "_meta": {"title": "Latent upscale"}, "inputs": {
        "latent": ["lu_split", 0], "model_name": model, "mode": "megapixels", "mode.megapixels": megapixels, "align": 32,
        "enable_temporal_chunking": not custom or chosen.get("latent_upscale_chunking", ON) == ON, "force_unload": True, "device": "cuda", "precision": "bf16" if "bf16" in model.lower() else "fp16"}}
    api["lu_join"] = {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["lu_upscale", 0], "audio_latent": ["lu_split", 1]},
                      "_meta": {"title": "Latent upscale: join"}}
    api["lu_sigmas"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": sigmas}, "_meta": {"title": f"Latent upscale: {preset}"}}
    api["lu_refine"] = {"class_type": "SamplerCustomAdvanced", "_meta": {"title": "Latent upscale: refine"}, "inputs": {
        **{name: sampler["inputs"][name] for name in ("noise", "guider", "sampler")}, "sigmas": ["lu_sigmas", 0], "latent_image": ["lu_join", 0]}}
    chosen_sampler = chosen.get("latent_upscale_sampler", SAME_SAMPLER)
    if custom and chosen_sampler in samplers:
        api["lu_sampler"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": chosen_sampler}, "_meta": {"title": "Latent upscale: sampler"}}
        api["lu_refine"]["inputs"]["sampler"] = ["lu_sampler", 0]
    for node_id in decoders:
        api[node_id]["inputs"]["samples"] = ["lu_refine", 0]
    return options


# The nodes the options here splice in, which the workflow itself doesn't have: kept with its listing (.info.json), as a
# run makes its workflow again from that, and an option whose nodes aren't there is left out.
SPLICED_NODES = ("MinimaxH3LatentUpscaler3D", "LTXVSeparateAVLatent", "LTXVConcatAVLatent", "ManualSigmas", "KSamplerSelect",
                 "UNETLoader", "UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScaleBy", "VAEEncode", "VAEDecode",
                 "LatentUpscaleBy", "SplitSigmasDenoise", "UltimateSDUpscale", "UltimateSDUpscaleCustomSample",
                 "UltimateSDUpscaleGuider", "ImageScale", "FreeMemoryImage", "SeedVR2LoadDiTModel", "SeedVR2LoadVAEModel",
                 "SeedVR2VideoUpscaler")


# In Generate, each image upscaled as it is made (pipelines/image/refine_upscale.py): Ultimate SD Upscale's tiles with
# the set's own model and prompt, 4x-UltraSharp alone, or SeedVR2. Each needs its nodes and model. The page sizes it:
# image_upscale_size is where it ends, image_upscale_scale about how many times bigger that is.
NO_IMAGE_UPSCALE = "Off"
IMAGE_UPSCALE_NEEDS = {"UltraSharp": ("UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScale"),
                       "Ultimate SD": ("UpscaleModelLoader", "ImageScale", "ManualSigmas", "KSamplerSelect"),
                       "SeedVR2": ("SeedVR2LoadDiTModel", "SeedVR2LoadVAEModel", "SeedVR2VideoUpscaler", "ImageScale")}


def _image_upscale(api, info, chosen):
    from pipelines.image import refine_upscale as ru
    from pipelines.image.upscale import DIT_MODEL
    sharp = ru.UPSCALE_MODEL in _combo(info, "UpscaleModelLoader", "model_name")
    free = "FreeMemoryImage" in info
    offered = []
    for label, method in ru.IN_GENERATION.items():
        if not all(name in info for name in IMAGE_UPSCALE_NEEDS[label]):
            continue
        if (label != "SeedVR2" and not sharp) or (label == "SeedVR2" and DIT_MODEL not in _combo(info, "SeedVR2LoadDiTModel", "model")):
            continue
        try:
            trial = ru.in_generation(copy.deepcopy(api), method, (2048, 2048), free_memory=free)
        except ru.Unsupported:
            continue
        # Ultimate SD's node for this sampler (plain, custom-sample or guider) has to be installed too.
        if method == "usdu" and trial["ru_usdu"]["class_type"] not in info:
            continue
        if "ru_sigmas" in trial and "ManualSigmas" not in info:
            continue
        offered.append(label)
    if not offered:
        return []
    options = [{"id": "image_upscale", "kind": "choice", "label": "Upscale", "choices": [NO_IMAGE_UPSCALE, *offered], "default": NO_IMAGE_UPSCALE,
                "limits": {label: ru.LIMITS[label] for label in offered}},
               # SeedVR2's latent noise (pipelines/image/upscale.py upscale_workflow): 0, as it was, unless set.
               {"id": "image_upscale_denoise", "kind": "number", "label": "Denoise", "parent": "image_upscale", "default": "0",
                "min": 0, "max": 0.05, "step": 0.01},
               {"id": "image_upscale_size", "kind": "text", "label": "Upscale to", "parent": "image_upscale", "default": ""},
               {"id": "image_upscale_scale", "kind": "number", "label": "Upscale by", "parent": "image_upscale", "default": "2",
                "min": 1, "max": ru.MOST_SCALE, "step": 0.01}]
    label = chosen.get("image_upscale", NO_IMAGE_UPSCALE)
    final = ru.parse_final(chosen.get("image_upscale_size"))
    if label in offered and final:
        ru.in_generation(api, ru.IN_GENERATION[label], final, float(chosen.get("image_upscale_scale", 2)),
                         float(chosen.get("image_upscale_denoise", 0) or 0), free_memory=free)
    return options


# FastVideo: a 4-step distillation of H3's first/last-frame model. It stands in for that model, at 4 steps, and a turbo
# LoRA made for the full model comes out: it is distilled already.
FASTVIDEO = "minimax_h3_fastvideo"
H3_MODELS = ("Standard", "FastVideo 4-step")


def _h3_fastvideo(api, info, chosen):
    loaders = [node_id for node_id, node in api.items() if node["class_type"] == "UNETLoader"
               and "minimax_h3_fl2va" in str(node["inputs"].get("unet_name", "")).lower()]
    fast = next((name for name in _combo(info, "UNETLoader", "unet_name") if FASTVIDEO in name.lower()), None)
    if not loaders or not fast:
        return []
    options = [{"id": "h3_model", "kind": "choice", "label": "H3 model", "choices": list(H3_MODELS), "default": H3_MODELS[0], "advanced": True}]
    if chosen.get("h3_model") != H3_MODELS[1]:
        return options
    for node_id in loaders:
        api[node_id]["inputs"]["unet_name"] = fast
    turbo = [node_id for node_id, node in api.items() if node["class_type"] in ("LoraLoaderModelOnly", "LoraLoader")
             and re.search(r"turbo|lightx2v|\dstep", str(node["inputs"].get("lora_name", "")), re.I) and isinstance(node["inputs"].get("model"), list)]
    for node_id in turbo:
        source = api[node_id]["inputs"]["model"]
        for node in api.values():
            for name, value in node["inputs"].items():
                if value == [node_id, 0]:
                    node["inputs"][name] = source
    steps = _steps(api)
    if steps and "steps" not in chosen:
        api[steps[0]]["inputs"][steps[1]] = 4
    return options


def _node_defaults(info, class_type):
    """The inputs a node needs besides its model, as ComfyUI offers them by default."""
    values = {}
    for name, config in sw._input_spec(info.get(class_type, {})).items():
        if name == "model":
            continue
        extra = config[1] if len(config) > 1 and isinstance(config[1], dict) else {}
        choices = sw._options(config)
        value = extra.get("default", choices[0] if choices else None)
        if value is not None:
            values[name] = value
    return values


def _h3(api, info, chosen):
    """
    MiniMax H3's two optimizers (the H3-Optimizations custom node), which a workflow doesn't have: each is put between the
    model and what samples with it, when chosen. Sparse attention also takes how much of the video it attends to.
    """
    # Made for H3's video model (they order its video grid): not H3 Image's, whose conditioning node is its own.
    if (not any(node["class_type"].startswith("MiniMaxH3") and not node["class_type"].startswith(H3_IMAGE) for node in api.values())
            or not all(name in info for name in (H3_MEMORY, H3_SPARSE))):
        return []
    sparse = _node_defaults(info, H3_SPARSE)
    budget = float(sparse.get("video_budget", 0.15))
    options = [
        {"id": "h3_memory", "kind": "switch", "label": "H3 Memory Optimization", "default": OFF, "advanced": True},
        {"id": "h3_sparse", "kind": "switch", "label": "H3 Sparse Attention", "default": OFF, "advanced": True},
        {"id": "h3_budget", "kind": "number", "label": "Video attention", "parent": "h3_sparse", "default": f"{budget:g}", "min": 0.01, "max": 1, "step": 0.01,
         "advanced": True},
    ]
    wanted = [(class_type, inputs) for flag, class_type, inputs in (
        ("h3_memory", H3_MEMORY, _node_defaults(info, H3_MEMORY)),
        ("h3_sparse", H3_SPARSE, {**sparse, "video_budget": float(chosen.get("h3_budget", budget))})) if chosen.get(flag) == ON]
    if wanted:
        sources = {tuple(node["inputs"]["model"]) for node in api.values() if node["class_type"] in H3_SAMPLING and isinstance(node["inputs"].get("model"), list)}
        for number, source in enumerate(sorted(sources)):
            link = list(source)
            for class_type, inputs in wanted:
                node_id = f"h3_{number}_{class_type}"
                api[node_id] = {"class_type": class_type, "inputs": {**inputs, "model": link}, "_meta": {"title": class_type}}
                link = [node_id, 0]
            for node in api.values():
                if node["class_type"] in H3_SAMPLING and node["inputs"].get("model") == list(source):
                    node["inputs"]["model"] = link
    return options


def _steps(api):
    """
    Where the steps are set, if just one sampler has them as a number: [node id, input], or None. A sampler fed sigmas
    (SamplerCustomAdvanced) has none of its own, so then its scheduler's (BasicScheduler) are the ones.
    """
    for takes in (lambda node: "positive" in node["inputs"], lambda node: node["class_type"].endswith("Scheduler")):
        found = [source for node_id, node in api.items() if "steps" in node["inputs"] and takes(node)
                 for source in [_number_source(api, node_id, "steps")] if source]
        if found:
            return found[0] if len(found) == 1 else None
    return None


def _after(api, options, chosen, info):
    """The LoRAs and the enhancer as chosen. (SeedVR2 falls back to SDPA itself where SageAttention isn't installed.)"""
    loras = (info.get("LoraLoader") or info.get("LoraLoaderModelOnly") or {}).get("input", {}).get("required", {}).get("lora_name", [[]])[0]
    for option in options:
        if option["kind"] != "strength":
            continue
        node = api.get(str(option["node"]))
        if not node:
            continue
        value = chosen.get(option["id"], option["default"])
        strength = float(value) if value != OFF else 0.0
        if option["id"] == "prompt_boost":
            node["inputs"].update(enabled=value != OFF, strength=strength if value != OFF else node["inputs"].get("strength", 1.0))
            continue
        entry = node["inputs"].get(option["entry"])
        if isinstance(entry, dict):
            entry = {**entry, "on": value != OFF, "strength": strength if value != OFF else entry.get("strength", 1)}
            # Saved under a folder of the author's, it may be installed without one.
            wanted = os.path.basename(str(entry["lora"]).replace("\\", "/"))
            if entry["lora"] not in loras:
                entry["lora"] = next((name for name in loras if os.path.basename(name.replace("\\", "/")) == wanted), entry["lora"])
            node["inputs"][option["entry"]] = entry


def lora_problem(option, info, model=None):
    """
    Why a LoRA can't be switched on, or does nothing: its file isn't installed, or it was made for an earlier version
    of the model (core/lora_check.py). None if it's fine.
    """
    if option["kind"] != "strength" or option["id"] == "prompt_boost":
        return None
    loras = (info.get("LoraLoader") or info.get("LoraLoaderModelOnly") or {}).get("input", {}).get("required", {}).get("lora_name", [[]])[0]
    name = option["label"].split(": ", 1)[1]
    found = next((lora for lora in loras if os.path.splitext(os.path.basename(lora.replace("\\", "/")))[0] == name), None)
    if not found:
        return f"Its file {name} isn't installed."
    return lora_check.problem(found, model)


def convert(ui, info, chosen=None, pipeline="image"):
    """The workflow made for this side (image, video or shorts) with these options. Returns (api, fields, model, options). Raises Unusable."""
    options = describe(ui, info, pipeline)
    chosen = upgraded(chosen, options)
    api = sw.to_api(_before(ui, options, chosen), info, images=pipeline == "image", enhance=chosen.get("prompt_enhancer") == ON)
    # References that grow, such as Fibo 2.0's 16 or MiniMax H3's: a saved workflow wires one or two. Shorts gives one.
    if pipeline != "shorts":
        sw._grow_references(api, info)
    _after(api, options, chosen, info)
    options += _style_lora(api, info, chosen, options)
    steps = _steps(api) or _main_targets(api).get("steps")
    if steps:
        node_id, name = steps
        options.append({"id": "steps", "kind": "number", "label": "Steps", "default": str(api[node_id]["inputs"][name]), "min": 1, "max": MOST_STEPS, "step": 1,
                        "advanced": True})
        if "steps" in chosen:
            api[node_id]["inputs"][name] = int(float(chosen["steps"]))
    options += _tune(api, info, chosen)
    if pipeline == "image":
        options += _image_upscale(api, info, chosen)
        # SeedVR2 is in Upscale now: the workflow's own SeedVR2 switch (Krea 2 SFW/NSFW's group) stays as saved, off
        # the form. Kept among the options, so a set made with it can still be made again.
        if any(option["id"] == "image_upscale" and "SeedVR2" in option["choices"] for option in options):
            for option in options:
                if "seedvr2" in option["id"].lower() and option["id"] != "image_upscale":
                    option["moved"] = "Upscale"
    _drop_idle_loras(api)
    if pipeline == "image":
        return api, sw.find_image_fields(api, info), sw.image_model(api), options
    return api, sw.find_fields(api, info, needs_audio=pipeline == "shorts"), None, options


def offered(ui, info, pipeline="image"):
    """
    The options as the form shows them: each with a problem, if choosing the other way can't run. A way for the
    workflow to write its own prompt also says how many images it takes then: image to prompt needs its picture.
    """
    _, _, model, options = convert(ui, info, pipeline=pipeline)
    # A switch such as turbo has its own steps, CFG and sampler: they show the ones that go with it as it's set.
    flips = {}
    for option in options:
        problem = lora_problem(option, info, model)
        if not problem and option["kind"] == "switch":
            try:
                _, fields, model, flipped = convert(ui, info, {option["id"]: ON if option["default"] == OFF else OFF}, pipeline)
                flips[option["id"]] = flipped
                if option.get("role"):
                    found = sw.image_takes(fields, model) if pipeline == "image" else sw.takes(fields)
                    option["takes"] = {key: found[key] for key in ("min_images", "max_images")}
            except sw.Unusable as e:
                problem = str(e)
        if problem:
            option["problem"] = problem
    switches = {option["id"]: option for option in options if option["kind"] == "switch"}
    # What goes with a switch that can't be switched can't be set either, for the same reason.
    for option in options:
        parent = switches.get(option.get("parent"))
        if parent and parent.get("problem") and not option.get("problem"):
            option["problem"] = parent["problem"]
    for target in options:
        if target["id"] not in FOLLOWERS or target.get("problem"):
            continue
        for switch_id, flipped in flips.items():
            other = next((found["default"] for found in flipped if found["id"] == target["id"]), None)
            if other and other != target["default"] and not switches[switch_id].get("problem"):
                flipped_to = ON if switches[switch_id]["default"] == OFF else OFF
                target["follows"] = {"switch": switch_id, switches[switch_id]["default"]: target["default"], flipped_to: other}
                break
    return options


def remake(workflow_path, chosen, pipeline=None):
    """
    The workflow a run makes with these options, from the copy kept when it was listed: (api, {field: (node, input)}).
    For ComfyClient and Shorts' AvatarGenerator. Raises RuntimeError, saying why.
    """
    stem = os.path.splitext(workflow_path)[0]
    try:
        with open(stem + ".map.json", "r", encoding="utf-8") as f:
            saved = json.load(f)
        offered_ = saved.get("_options") or []
        problem = check(offered_, chosen)
        if problem:
            raise RuntimeError(problem)
        with open(stem + ".ui.json", "r", encoding="utf-8") as f:
            ui = json.load(f)
        with open(stem + ".info.json", "r", encoding="utf-8") as f:
            info = json.load(f)
    except OSError:
        raise RuntimeError("This workflow's options need it listed again: open the panel with ComfyUI on.")
    try:
        api, fields, _, _ = convert(ui, info, chosen, pipeline or saved.get("_pipeline") or "video")
    except sw.Unusable as e:
        raise RuntimeError(f"With these options the workflow can't run: {e}")
    return api, {field: tuple(value) for field, value in fields.items() if isinstance(value, list)}


def chosen_in_env():
    """The options the panel chose for this run, kept with it: COMFYUI_OPTIONS, as JSON."""
    try:
        found = json.loads(os.getenv("COMFYUI_OPTIONS") or "{}")
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def check(options, chosen):
    """Why these choices can't be made, or None."""
    chosen = upgraded(chosen, options)
    known = {option["id"]: option for option in options}
    for key, value in chosen.items():
        option = known.get(key)
        if not option:
            return f"This workflow has no option {key}."
        if option.get("problem") and value != option["default"]:
            return f"{option['label']} can't be changed: {option['problem']}"
        if option["kind"] == "switch" and value not in (ON, OFF):
            return f"{option['label']} is on or off."
        if option["kind"] == "choice" and value not in option["choices"]:
            return f"{option['label']} is one of {', '.join(option['choices'])}."
        if option["kind"] == "text" and (not isinstance(value, str) or len(value) > MOST_TEXT):
            return f"{option['label']} is text of up to {MOST_TEXT} characters."
        if option["kind"] in ("strength", "number"):
            try:
                number = float(value)
            except ValueError:
                return f"{option['label']} needs a number."
            if (option["kind"] == "number" or value != OFF) and not option["min"] <= number <= option["max"]:
                return f"{option['label']} goes from {option['min']:g} to {option['max']:g}."
    return None


# --- Which LoRAs a run used, for the gallery ---

OUTPUTS = {sw.PREVIEW, *sw.IMAGE_SAVES, *sw.VIDEO_SAVES}
LORA_STRENGTHS = ("strength_model", "lora_strength", "strength")
_loras = {}


def _feeding_outputs(api):
    """The nodes an output reads from, however far back: a LoRA loader switched out of the way isn't one."""
    todo = [key for key, node in api.items() if isinstance(node, dict) and node.get("class_type") in OUTPUTS]
    seen = set()
    while todo:
        key = todo.pop()
        if key in seen or key not in api:
            continue
        seen.add(key)
        for value in (api[key].get("inputs") or {}).values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)):
                todo.append(str(value[0]))
    return seen


def _lora_label(name, strength):
    """A LoRA as its pill says it: its name (lora_label, without its folder) and strength, 1 too."""
    short = lora_label(os.path.basename(str(name).replace("\\", "/")))
    try:
        strength = float(strength)
    except (TypeError, ValueError):
        return short
    return f"{short} ({strength:g})"


def loras_in(api):
    """The LoRAs a workflow in API format runs with, as "name" or "name (strength)", in node order."""
    used = []
    for key in sorted(_feeding_outputs(api), key=lambda k: (len(k), k)):
        inputs = api[key].get("inputs") or {}
        name = inputs.get("lora_name")
        if isinstance(name, str) and name.lower() not in ("", "none"):
            strength = next((inputs[s] for s in LORA_STRENGTHS if s in inputs and not isinstance(inputs[s], list)), 1)
            if strength != 0:
                used.append(_lora_label(name, strength))
        # rgthree's Power Lora Loader: one {"on", "lora", "strength"} per row.
        for value in inputs.values():
            if isinstance(value, dict) and value.get("lora") and value.get("on") and value.get("strength", 1) != 0:
                used.append(_lora_label(value["lora"], value.get("strength", 1)))
    return list(dict.fromkeys(used))


def _made_with(workflow_path, chosen=None, pipeline=None):
    """The workflow a run was made with, its options and all, in API format: {} if that can't be told. Kept for reuse."""
    if not workflow_path:
        return {}
    stem = os.path.splitext(workflow_path)[0]
    try:
        stamp = max(os.path.getmtime(path) for path in (workflow_path, stem + ".ui.json") if os.path.exists(path))
    except ValueError:
        return {}
    key = (workflow_path, stamp, json.dumps(chosen or {}, sort_keys=True), pipeline)
    if key not in _loras:
        try:
            api = remake(workflow_path, chosen or {}, pipeline)[0]
        except RuntimeError:
            # Listed before options were kept: the workflow as saved.
            try:
                with open(workflow_path, "r", encoding="utf-8") as f:
                    api = json.load(f)
            except (OSError, ValueError):
                api = {}
        _loras[key] = api if isinstance(api, dict) else {}
    return _loras[key]


def loras_used(workflow_path, chosen=None, pipeline=None):
    """The LoRAs a run used: its workflow with the options it was made with. [] if that can't be told."""
    return loras_in(_made_with(workflow_path, chosen, pipeline))


def prompt_writer_used(workflow_path, chosen=None, form=None):
    """An image workflow's chosen prompt writer, as (id, label), including one stopped after reviewing its prompts."""
    chosen, form = chosen or {}, run_form.flat(form)
    if form.get("image_mode") in ("areas", "expand"):
        return None
    role = next((role for role in ROLES if chosen.get(role) == ON), None)
    selected = form.get("llm")
    if not role and form.get("prompt_mode") == "llm" and selected in ROLES:
        if selected not in chosen or (selected == "prompt_enhancer" and form.get("review")):
            role = selected
    if not role:
        return None
    label = "Image to prompt" if role == "image_to_prompt" else "Prompt enhancer"
    if role == "prompt_enhancer" and any(node.get("class_type", "").startswith(H3_IMAGE)
                                       for node in _made_with(workflow_path, chosen, "image").values()):
        label = H3_ENHANCER_LABEL
    return role, label


def _main_targets(api):
    """
    Where the main sampler (_main_sampler) takes its sampler, scheduler, steps and CFG: its own, or what it's fed (a
    KSamplerSelect, a scheduler's sigmas, a guider). {name: [node id, input]} for each that can be set.
    """
    main = _main_sampler(api)
    if not main:
        return {}
    inputs = api[main]["inputs"]
    fed = lambda name: inputs[name][0] if isinstance(inputs.get(name), list) else None
    sampler, sigmas, guider = fed("sampler") or main, fed("sigmas") or main, fed("guider")
    found = {"sampler_name": _text_source(api, sampler, "sampler_name"), "scheduler": _text_source(api, sigmas, "scheduler"),
             "steps": _number_source(api, sigmas, "steps"),
             "cfg": _number_source(api, guider, "cfg", kinds=FLOATS) if guider else _number_source(api, main, "cfg", kinds=FLOATS)}
    return {name: target for name, target in found.items() if target}


def _samplers(api):
    """The nodes in use that sample (they take a latent, sigmas or steps), with a sampler of their own or fed one."""
    used = _feeding_outputs(api)
    return [node_id for node_id, node in api.items() if node_id in used
            and (isinstance(node["inputs"].get("sampler_name"), str) or isinstance(node["inputs"].get("sampler"), list))
            and any(name in node["inputs"] for name in ("latent_image", "sigmas", "steps"))]


def _main_sampler(api):
    """
    The sampler that makes the picture: the one that denoises the most (a 2nd pass, as Krea-2's at 0.2, only
    refines). Its node id, or None.
    """
    samplers = _samplers(api)
    if not samplers:
        return None
    denoise = lambda node_id: _constant(api, api[node_id]["inputs"].get("denoise", 1.0))
    return max(samplers, key=lambda node_id: denoise(node_id) if denoise(node_id) is not None else 1.0)


def sampling_in(api):
    """
    The sampler and steps a workflow in API format samples with, as "euler, 6 steps". None if neither can be told.
    A sampler fed its sampler (KSamplerSelect) or its sigmas (a scheduler's steps) runs with those, not with the
    settings it has of its own, as MiniMax H3's Motion Director has.
    """
    main = _main_sampler(api) if api else None
    if not main:
        return None
    inputs = api[main]["inputs"]
    fed = inputs.get("sampler")
    sampler = api.get(fed[0], {}).get("inputs", {}).get("sampler_name") if isinstance(fed, list) else inputs.get("sampler_name")
    if isinstance(inputs.get("sigmas"), list):
        found = _steps(api)
        steps = _constant(api, api[found[0]]["inputs"][found[1]]) if found else None
    else:
        steps = _constant(api, inputs.get("steps"))
    parts = [sampler.split("/")[-1] if isinstance(sampler, str) else None, f"{int(steps)} steps" if steps else None]
    return ", ".join(part for part in parts if part) or None


def cfg_in(api):
    """The CFG the picture is made with, as "1" or "4.5": the main sampler's, or its guider's (a Basic Guider has none: 1). None if it can't be told."""
    main = _main_sampler(api) if api else None
    if not main:
        return None
    inputs = api[main]["inputs"]
    guider = api.get(inputs["guider"][0]) if isinstance(inputs.get("guider"), list) else None
    if guider:
        value = 1 if guider["class_type"] == "BasicGuider" else _constant(api, guider["inputs"].get("cfg"))
    else:
        value = _constant(api, inputs.get("cfg"))
    return f"{float(value):g}" if value is not None else None


def cfg_used(workflow_path, chosen=None, pipeline=None):
    """The CFG a run was made with (cfg_in), or None."""
    return cfg_in(_made_with(workflow_path, chosen, pipeline))


def sampling_used(workflow_path, chosen=None, pipeline=None):
    """The sampler and steps a run was made with (sampling_in), or None."""
    return sampling_in(_made_with(workflow_path, chosen, pipeline))
