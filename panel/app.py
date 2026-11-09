"""The panel with all its pipelines on it."""
from panel import image, image_tools, server, shorts, video  # noqa: F401, each adds its side to the server
from panel import collections  # noqa: F401, after the sides: it builds on them
from panel import comfy_cleanup  # noqa: F401, keeps ComfyUI's folders free of what this app makes

app = server.app
main = server.main
