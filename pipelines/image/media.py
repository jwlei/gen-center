import math
import os
import re
import threading

from PIL import Image, ImageOps

# Qwen-Image and Krea-2 both take sizes on this grid.
SIZE_STEP = 16
MIN_EDGE = 256
MAX_EDGE = 8192
# As in ComfyUI's own Resolution Selector, where 1 megapixel is 1024x1024.
PIXELS_PER_MEGAPIXEL = 1024 * 1024
DEFAULT_MEGAPIXELS = 1.0
MAX_MEGAPIXELS = 50.0
# Means: take this from the source image.
FROM_IMAGE = "image"
# What the panel offers, as (value, what it says). Any W:H works from the command line.
ASPECTS = (("1:1", "1:1 square"), ("2:3", "2:3 portrait photo"), ("3:2", "3:2 photo"), ("3:4", "3:4 portrait"), ("4:3", "4:3 standard"),
           ("9:16", "9:16 vertical"), ("16:9", "16:9 widescreen"))
MEGAPIXELS = (0.5, 1, 1.5, 2, 3, 4, 6, 8)
# Exact resolutions the panel offers, as (what it says, width, height): screens, to fill one pixel for pixel.
DESKTOP_SIZES = (("1080p Full HD", 1920, 1080), ("1440p QHD", 2560, 1440), ("1440p ultrawide", 3440, 1440), ("4K UHD", 3840, 2160))
PHONE_SIZES = (("OnePlus 15", 1272, 2772), ("Android Full HD+", 1080, 2400), ("Android QHD+", 1440, 3200),
               ("iPhone 16", 1179, 2556), ("iPhone 16 Pro Max", 1320, 2868))
THUMBNAIL_EDGE = 480
# The viewer's picture: a phone's screen, sharp, without the full file (see preview).
PREVIEW_EDGE = 2560


def on_grid(value):
    return min(MAX_EDGE, max(MIN_EDGE, round(value / SIZE_STEP) * SIZE_STEP))


def parse_size(text):
    """'1920x1080' as (width, height), or None if it isn't a size this can make."""
    match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", (text or "").strip().lower())
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    return (width, height) if MIN_EDGE <= width <= MAX_EDGE and MIN_EDGE <= height <= MAX_EDGE else None


def render_size(width, height, step=SIZE_STEP):
    """What to have the model make for this size: the nearest on its grid that's no smaller, so it can be cropped to fit."""
    return tuple(math.ceil(side / step) * step for side in (width, height))


def _reference_latent(width, height):
    """The size Qwen-Image's edit encoder scales its image to, whatever it's given: about a megapixel, in latent pixels."""
    scale = math.sqrt(PIXELS_PER_MEGAPIXEL / (width * height))
    return round(width * scale / 8), round(height * scale / 8)


def edit_render_size(width, height):
    """
    As render_size, for Qwen-Image's edit encoder. If its image comes out an odd number of latent pixels across, ComfyUI
    evens it up by wrapping the image around, and the result has a band of the far side along its edge. So this takes the
    nearest size on the grid, no smaller, where it comes out even. What's over gets cropped off like any other.
    """
    start_width, start_height = render_size(width, height)
    sizes = [(start_width + SIZE_STEP * more_wide, start_height + SIZE_STEP * more_high) for more_wide in range(8) for more_high in range(8)]
    for size in sorted(sizes, key=lambda size: size[0] * size[1]):
        if not any(side % 2 for side in _reference_latent(*size)):
            return size
    return start_width, start_height


def parse_aspect(text):
    """'16:9' as a width/height ratio, or None if it isn't one."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)", (text or "").strip())
    if not match or not float(match.group(1)) or not float(match.group(2)):
        return None
    return float(match.group(1)) / float(match.group(2))


def parse_megapixels(text):
    """A pixel count in megapixels, or None if it isn't a usable one."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if 0.05 <= value <= MAX_MEGAPIXELS else None


def pick_size(size=None, aspect=FROM_IMAGE, megapixels=DEFAULT_MEGAPIXELS, source=None, most_megapixels=None):
    """
    The size to make, from what was asked for. source is the first image's (width, height), if there is one:
    with none, "the same as the image" means square and one megapixel, which is what a blank canvas gets.
    most_megapixels: what the model makes well, which "the same as the image" stays within.
    """
    if size:
        return parse_size(size)
    width, height = source or (1, 1)
    ratio = width / height if aspect == FROM_IMAGE else parse_aspect(aspect) or 1
    most = (most_megapixels or MAX_MEGAPIXELS) * PIXELS_PER_MEGAPIXEL
    if megapixels == FROM_IMAGE:
        area = min(width * height, most) if source else DEFAULT_MEGAPIXELS * PIXELS_PER_MEGAPIXEL
    else:
        area = float(megapixels) * PIXELS_PER_MEGAPIXEL
    # Held to the limit, it rounds down: rounding up onto the grid would go over it.
    down = lambda side: max(MIN_EDGE, math.floor(side / SIZE_STEP) * SIZE_STEP)
    sides = tuple(on_grid(side) for side in (math.sqrt(area * ratio), math.sqrt(area / ratio)))
    if most_megapixels and sides[0] * sides[1] > most:
        sides = (down(math.sqrt(area * ratio)), down(math.sqrt(area / ratio)))
    return sides


def save_source(image, path):
    """Whole: its own size may be the one asked for."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path)


def fit(path, width, height, output):
    """The image at exactly this size, cropped at the edges if its shape differs, for a workflow that follows its source's size."""
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with Image.open(path) as image:
        ImageOps.fit(image.convert("RGB"), (width, height), Image.LANCZOS).save(output)
    return output


def with_mask(path, mask_path, fitted, output):
    """
    The image with what's painted on the mask made transparent, which Load Image gives as its mask (where alpha is 0):
    the part a workflow's inpaint mode redraws. The mask was painted over the image as it was given, so it's fitted to
    the same size as the image was (fitted, or None if it wasn't), then sized to it.
    """
    with Image.open(mask_path) as painted:
        alpha = painted.convert("RGBA").getchannel("A")
    alpha = alpha.point(lambda value: 255 if value >= 128 else 0)
    if fitted:
        alpha = ImageOps.fit(alpha, tuple(fitted), Image.LANCZOS)
    with Image.open(path) as image:
        image = image.convert("RGB")
        if alpha.size != image.size:
            alpha = alpha.resize(image.size, Image.LANCZOS)
        # Painted is kept (255 on the mask), so the image's alpha is its opposite.
        image.putalpha(alpha.point(lambda value: 0 if value >= 128 else 255))
        os.makedirs(os.path.dirname(output), exist_ok=True)
        image.save(output)
    return output


def trim(path, rendered, wanted):
    """
    Crops the finished image to the size asked for, when that isn't on the model's grid: 1080 isn't, so 1080p
    renders 1088 high and loses four rows off the top and bottom. Left alone if it came out any other size,
    as from a workflow that sets its own.
    """
    if rendered == tuple(wanted):
        return
    with Image.open(path) as image:
        if image.size != tuple(rendered):
            return
        kind = image.format
        # What ComfyUI wrote into it (the workflow it ran, which says its model, text encoder and VAE): kept.
        texts = {key: value for key, value in image.info.items() if isinstance(value, str)}
        left, top = (rendered[0] - wanted[0]) // 2, (rendered[1] - wanted[1]) // 2
        cropped = image.crop((left, top, left + wanted[0], top + wanted[1]))
        cropped.load()
    # Under another name until complete: a cut-off save must not pass as the image.
    part = path + ".part"
    if kind == "PNG" and texts:
        from PIL import PngImagePlugin
        info = PngImagePlugin.PngInfo()
        for key, value in texts.items():
            info.add_text(key, value)
        cropped.save(part, format=kind, pnginfo=info)
    else:
        cropped.save(part, format=kind)
    os.replace(part, path)


def image_problem(path):
    """What is wrong with this file as an image, or None."""
    try:
        with Image.open(path) as image:
            image.load()
    except (OSError, ValueError, SyntaxError) as e:
        return f"it can't be read ({e})"
    return None


def _made(path, output):
    return os.path.exists(output) and os.path.getmtime(output) >= os.path.getmtime(path)


def _part(output):
    """
    Where a copy is written until complete: two requests can ask for it at once, and the panel answers each on a
    thread of its own, so the process alone doesn't tell them apart.
    """
    return f"{output}.{os.getpid()}.{threading.get_ident()}.part"


def thumbnail(path, output):
    """A small JPEG of the image, made once, so a gallery of big PNGs doesn't crawl over a phone connection."""
    if _made(path, output):
        return output
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with Image.open(path) as image:
        small = image.convert("RGB")
        small.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE))
        part = _part(output)
        small.save(part, format="JPEG", quality=85)
    os.replace(part, output)
    return output


def preview(path, output):
    """
    The image at screen size for the viewer, made once: a phone opening a 3008x5584 PNG fetched tens of MB and then
    decoded 67 MB of pixels in one go, and lagged. WebP, which keeps transparency; at most PREVIEW_EDGE on its longer
    side, about 4 times less to decode, and the full file comes only when zoomed in past it.
    """
    if _made(path, output):
        return output
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with Image.open(path) as image:
        clear = image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info)
        shown = image.convert("RGBA" if clear else "RGB")
        shown.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE), Image.Resampling.LANCZOS)
        part = _part(output)
        shown.save(part, format="WEBP", quality=88, method=4)
    os.replace(part, output)
    return output


def opaque(path):
    """
    The image without its alpha channel. Qwen-Image 2.1 always decodes one, nearly all 255 on an opaque image (Kokon
    found about 1% of pixels at 247-254), which shows as faint holes: made opaque unless transparency was asked for.
    """
    with Image.open(path) as image:
        if image.mode not in ("RGBA", "LA", "PA") and "transparency" not in image.info:
            return
        kind = image.format
        flat = image.convert("RGB")
    part = path + ".part"
    flat.save(part, format=kind)
    os.replace(part, path)


def seeds_in(file):
    """The seeds a ComfyUI image was made with, from the workflow its PNG keeps. file: a path or an open stream."""
    from core import seeds
    try:
        with Image.open(file) as image:
            found = seeds.found_in(image.info.get("prompt") or "")
    except (OSError, ValueError, SyntaxError):
        found = set()
    if hasattr(file, "seek"):
        file.seek(0)
    return found


def resized(path, size, output):
    """The image at this size (its shape is the caller's to keep), saved as output. Returns output."""
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with Image.open(path) as image:
        if image.size == tuple(size) and path != output:
            image.save(output)
        else:
            image.resize(tuple(size), Image.LANCZOS).save(output)
    return output


def size_of(path):
    with Image.open(path) as image:
        return image.size


OUT_OF_MEMORY = ("out of memory", "outofmemory", "allocation on device", "cuda error: out of memory", "not enough memory")


def out_of_memory(error):
    """Whether ComfyUI stopped because the card ran out of memory, which a smaller try can get past."""
    text = str(error).lower()
    return any(marker in text for marker in OUT_OF_MEMORY)

