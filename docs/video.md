# Video

The Video pipeline of [gen-center](../README.md). It has no YouTube upload: films are downloaded, or found in `output/video`.

Turns one image and a short prompt into a film, from a single 5-second clip up to 10 minutes. An LLM looks at the image and writes a detailed
prompt per shot, ComfyUI renders each shot as a clip, and ffmpeg joins them. It runs from a web panel or the
command line.

```
image + "a storm rolls in over the harbour"
  → Gemini or a local model writes the shot list (one request for the whole film)
  → ComfyUI renders each shot (LTX-2.3: 5-10 seconds a clip, MiniMax H3: 5-15, Wan: 3-5)
  → ffmpeg joins the clips into output/<title>_<workflow>.mp4 (the workflow without video_; LTX23_I2V_T2V for the built-in)
  → optionally, YouTube
```

## Setup

You need Python 3.10+, ffmpeg on the PATH, and ComfyUI with the models and custom nodes that
`workflows/video_workflow.json` uses (the same ones as yt-auto-shorts' avatar workflow).

```
pip install -r requirements.txt
copy .env.example .env
```

In `.env`, set at least one LLM key:

| Setting | What it's for |
|---|---|
| `GEMINI_API_KEY` | Writing the prompts with Gemini, on its free tier. |
| `ANTHROPIC_API_KEY` | Writing the prompts with Claude Opus 5.5, paid per use. Keys come from platform.claude.com. |
| `LLM_PROVIDER` | Which one to use when you don't choose: `local` (default), `gemini` or `claude`. |
| `COMFYUI_LAUNCHER` | Lets the panel start ComfyUI when a render needs it. |
| `APP_PASSWORD` | Needed to reach the panel from your phone. Without it, it only answers this PC. |
| `YOUTUBE_*` | Uploading. Run `scripts/authorize_youtube.py` once and paste what it prints. |

## The panel

Double-click **gen-center** on the desktop. To create that shortcut:

```
powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
```

Or run it yourself and open http://localhost:8801:

```
python webapp.py
```

**Making a film:** choose an image, say what should happen, and pick a length. By default the panel stops once
the prompts are written and opens them for you. Change any of them, then press **Render the film**. Untick
"Let me read the prompts" to go straight through.

**Write prompt:** enter an idea and press the button beside the prompt field to rewrite it locally using the model
selected in Settings. On success it replaces your text and keeps your selected prompt source. In LLM mode the rewritten
text is the brief for the clip planner; in Exact prompt mode it is repeated for every clip. It needs an idle, reachable ComfyUI
and temporarily unloads its models; queued panel generations wait until the writer finishes. The text is kept if it fails.
The progress bar and remaining time are estimates, learned separately for each model and for video and image prompts.
The writer receives only the text in the prompt box, not attached references or the selected duration. Its video
instructions describe shot composition, motion, sound and user-supplied dialogue and text; it cannot inspect references.

The prompt editor's writer menu offers Gemini and both local models (Gemma and Qwen), independently of the
local model selected in Settings. A workflow Prompt Enhancer appears when the setup supports it.
The selected writer stays highlighted; the reset button restores the text from before enhancement.
On mobile, the keyboard stays open while choosing a writer and closes after selection, keeping the buttons in place.
While enhancing, animated status text replaces the heading and the reset icon stays hidden until writing finishes.
Enhancing a video brief does not replace planning: in LLM mode the planner still turns that brief into per-clip prompts.

### One story or related scenes

**One story** asks the planner for a beginning, development and ending, with each clip advancing the action.
**Related scenes** asks for distinct, self-contained moments sharing the subject and visual identity, without a
required chronological story. With continuous connections, Related scenes still has to continue physically from
the previous clip: it cannot jump to a different location without getting there on screen.

Write the subject, desired actions, look, constraints and any essential ending or dialogue. You can omit
"plan N clips", clip lengths, general continuity instructions and "do not repeat the same scene": Generation and
these options supply that guidance. A story brief might be "A courier finds a sealed letter, follows its clue,
and reaches an abandoned lighthouse." A related-scenes brief might be "Quiet moments around the same harbour:
repairing fishing nets, unloading a boat and watching the evening tide. Warm documentary photography."
Use independent clips if those moments should have different starting frames.

These choices apply to the clip planner, not to Exact mode or the text-only prompt-editor writer.
Exact mode repeats the same prompt in every clip, even if a writer enhanced that text first.

For a 30-second film with fixed 10-second clips, an event at film second 12 belongs two seconds into clip 2.
For example: "Action A continues for the first 12 seconds, then transitions into action B.
Clip 1 (0-10s): A throughout. Clip 2 (10-20s): A for its first two seconds, then B.
Clip 3 (20-30s): continue and complete B." Choose LLM planning, One story and a continuous connection
when the movement must flow across clip boundaries. Review clip 2's prompt to confirm it expresses local timing.
This is guidance to the model, not an enforced event scheduler: generation, H3's frame grid and stitching can shift timing.

Select **LLM** under **Prompt source** and **Local model** under **Model** to plan a separate prompt per clip using
the existing workflow-specific planner. Gemma can analyze attached images; Qwen rejects them because it is text-only.
The local model unloads before rendering and needs an idle, reachable ComfyUI. Large plans can take substantial
time and may exceed the local model's context or output limits.
The panel defaults to Local model. A selected prompt model is remembered in this browser, and a default preset can
override it. A workflow's own prompt enhancer is offered but never picked by itself. Opening a previous film brings back every setting it was made with, its prompt model included: the
whole Generate form is kept with each run. The CLI follows `LLM_PROVIDER`, else the local model.

**OpenH3-IR (MiniMax H3).** The Prompt section offers this optional compiler on supported H3 workflows. It is off
by default; enable it to show its settings. Choose **before review** to compile each planned prompt before editing it (using the original reference
images), or **before each clip** to compile with the actual start frame, including a frame from the previous clip.
The latter happens after prompt review; its resulting brief is saved with the shot. Pick **Restrained**, **Balanced**
(default), **Bold**, or **Extreme** for how much the compiler may introduce. Your written constraints still apply.

The LLM plans the clips together, with a different action in each. If it returns identical prompts, the planner asks
again and reports an error if it cannot get a usable plan. Near-duplicate wording is checked before rendering:
pairs with at least 92% token-sequence similarity stop the run in the red **Warning** section above Queue/Pending.
For structured H3 reference prompts, the check compares `detailed_description`, rather than repeated subject definitions.
Each entry says **Check prompts (Items x and y)** and highlights its prompts button in red.
It has Pending's controls: inspect/edit the prompts, change setup, remove the queued entry, or start it.
Starting approves the exact prompts reviewed; editing them invalidates that approval if duplicates remain.
For a run already held by this warning, explicitly continuing with CLI `--resume RUN` also approves it.
Warning entries do not auto-start with the queue, and their saved plans and warnings survive a restart.
Exact mode is excluded because repetition is intentional. This wording check cannot detect every semantic repetition
and can flag deliberately similar actions, so it is a review warning rather than an automatic rewrite.

### Clip prompt history

The video's preview has a **Clips and prompt history** filmstrip button, including inside collections.
It opens the saved run's constituent clips. Each clip's prompt-history button shows the **Original brief**,
immutable **Planner output**, **Enhancer output**, and **Final ComfyUI text** recorded at submission.
The final text is the actual submitted input, including H3 Multishot's flattened sampler prompt, not a reconstruction
from the current editor. A later edit does not overwrite the last submitted text; rendering again updates it.
When an in-workflow text enhancer returns its output, a separate **Workflow enhancer** stage shows it:
that output is produced inside ComfyUI, after submission. Stages not used or not yet generated are identified explicitly.
Older runs cannot recover stages that were never recorded and say so rather than presenting current text as history.
H3 Multishot's one-file take provides cached per-shot video previews.

The compiler runs locally through the installed [ComfyUI-OpenH3-IR](https://github.com/ruashots/ComfyUI-OpenH3-IR)
pack and its `open-h3-ir` dependency in ComfyUI's Python. It starts llama.cpp for the compile and stops it before
rendering to release GPU memory; it refuses to unload ComfyUI's models if another ComfyUI job is running or queued.
Compiling can take several minutes per clip and uses substantial RAM. The original renderer, model, and settings stay
in place; H3 director workflows use H3's 24-fps frame grid for enhanced clips. Reference bindings are checked before
rendering, and duplicate reference files are refused rather than ambiguously assigned.
Motion Director is supported when the panel has adapted its inputs; manually wired Director timelines are not.

Choose the OpenH3-IR model in Settings: **Gemma 4 12B** is the default and supports images and reference videos;
**Qwen3 14B** is text-only and rejects visual references. This selection applies to subsequent compilations.
The GGUF models live in the project's ignored `models/gemma-4-12b-heretic` and `models/qwen3-14b-abliterated`
directories. Gemma also requires its `mmproj.gguf`.
For Gemma, the compiler uses guided JSON decoding by default to avoid malformed structured replies;
set `H3IR_GUIDED_DECODING=0` in `.env` to use the compiler's unguided mode instead.

For the portable Windows ComfyUI layout, the defaults locate `python_embeded/python.exe` and
`ComfyUI/custom_nodes/ComfyUI-OpenH3-IR` beside `COMFYUI_LAUNCHER`, and expect the Vulkan llama.cpp
at `1_Misc/llama.cpp/b12177-vulkan/llama-server.exe` beside the ComfyUI directory. Other layouts can set
`H3IR_COMFY_ROOT`, `H3IR_PYTHON`, `H3IR_LLAMA_SERVER`, `H3IR_MODEL_FILE`, and `H3IR_PROJECTOR_FILE`
in `.env`; `H3IR_GPU_LAYERS` defaults to 16. Model-file overrides apply to the currently selected model.
From the command line use `--h3-enhance review` or `--h3-enhance render`, and optionally
`--h3-creativity restrained|balanced|bold|extreme`.

**Every image has a box.** Image 1 is the first frame, or the main character in a reference workflow such as
MiniMax H3, which starts no clip on it. Each image after it is optional, and you say what it is:

| The image is | What the LLM does with it |
|---|---|
| **Same character, new view** (default) | More details of the subject to get right: another angle, the rest of an outfit. |
| **Another character** | It gives them a real part in the film, alongside the subject. |
| **Environment** | It's where the film happens: the subject goes there. Several places and the film moves between them. |

If your prompt says how to use an image, that wins. On H3 each character and place becomes a `<Subject>` of its own.

You can upload an image or use the gallery button in any box to choose one of your generated images from Output.
You start with one box, and **+** below it opens the next once it holds an image. ✕ removes an image and the ones after
it move up. It goes up to 20 boxes, or as many as the workflow has Load Image nodes if that's fewer. A reference node
whose inputs grow is different: wire one or two references in ComfyUI and the pipeline adds Load Image nodes up to 20,
or the node's own limit if that's lower, which is 9 on MiniMax H3. The boxes you leave empty come out of the workflow
again.

**Reference video and audio.** On MiniMax H3 the form also has boxes for reference videos and audio clips. Every clip
gets them, as it gets the images. H3 takes up to 3 videos and 3 audio clips, and 12 references in all, images
included: with 9 images there is room for 3 more of any kind. Each one is 2-15 seconds. A longer one is cut to its
first 15 seconds, and a video is turned to 24 fps, the rate H3 reads it at. Choose what each one is for:

| A video is | What the LLM does with it |
|---|---|
| **Movement and camera** (default) | The action and the camera follow it. |
| **A character** | Someone in the film, the next `<Subject>`. |
| **A place** | Where the film happens. |

| An audio clip is | What the LLM does with it |
|---|---|
| **Voice of the main character** | `<Subject 1>` speaks in that voice. |
| **Music** | The film's music, in `non_diegetic_music`. |
| **Sound and ambience** (default) | The soundscape follows it. |

The LLM can't watch or hear them, so it only knows what you chose and what your prompt says. It calls them
`<Video 1>` and `<Audio 1>`, as H3 does. A video with sound of its own brings that too, as an `<Audio>` of its own,
numbered before the audio clips. Every prompt has to name each one, or the missing ones are added.

**How long a clip is** depends on the video model, and the LLM is held to it:

| Video model | A clip | Usual (the fixed length's default) | Why |
|---|---|---|---|
| LTX-2.3 (LTX23_I2V_T2V, and any other) | 5-10 s | 8 s | About as long as it holds up. |
| MiniMax H3 | 5-15 s | 10 s | It was trained on 124-362 frames at 24 fps. |
| Wan 2.2 | 3-5 s | 5 s | It was trained on 81 frames at 16 fps. |

Film length under Generation shows how many clips that comes to on the workflow you chose. The buttons adjust it by
five seconds; type a whole number in the middle for finer control.
The lock beside Clip length switches between a range and one fixed length. A fixed length rounds the film to the
nearest whole number of clips (ties round up, within the film limit). If audio determines the length, it is trimmed
when the film is shorter or padded with silence when it is longer.
On the command line, use `--clip-seconds 8-8 --fixed-clips` for fixed eight-second clips.

A workflow with one image input, like LTX23_I2V_T2V, renders from image 1 alone. Only the LLM sees image 2 there, so
it reaches the clips as words in the prompts: expect a description of that place or person, not a copy of it.
A reference workflow gives image 2 to every clip.

**Seed**, under Generation, is empty by default: every clip gets a new random seed. The shuffle button picks one to keep, and ✕
goes back to random. With a seed, clip 1 uses it, clip 2 the next number and so on, so the same prompts make the
same film again. **Shots** shows the seed each clip was made with, and rendering it again keeps that seed unless you
change it or press shuffle, so a changed prompt changes only what the prompt does. An empty seed is new each time. A seed you set is used once per render: a clip that
fails its check is tried again on a new one.

**Resolution** offers 360p, 480p, 540p and 720p, in landscape 16:9 or portrait 9:16. The default and highest preset
is 720p (1280x736) in the shape of image 1, and **Custom size** takes anything else. The sizes are multiples of 32,
so they're as near 16:9 as the models allow. An image of another shape is fitted to the size, usually by cropping
its edges. The ETA scales with the pixel count.

**While it runs:** you see each step with its ETA, which clip is rendering, ComfyUI's own progress, GPU use and the
log. Generate adds more films to a queue, and each keeps the options it was queued with.
The setup button on a queued generation moves it to Pending while you edit its settings and inputs.
To reorder queued jobs, select an entry to outline it in green, then drag it or use the arrow keys.
The list scrolls when a dragged item is held near an edge. Dropping clears the selection; selecting the
same entry again clears it, and selecting another moves it there.
Tap the Queue heading to collapse or expand it. Queue, Pending and Failed scroll internally when their
lists exceed three cards or the available screen height; scrolling past an end continues on the page.
Queue and Pending entries show their resolution and a shortened prompt. Finished items open their output when available;
failed items open and highlight their entry under Failed. A failure before a run was saved (a planning error, or
ComfyUI stopping) keeps its settings: **Back to Pending** puts it in Pending to start again, and the sliders put it
there and open its setup to change it first.
Generate keeps the prompt after queuing so you can make variants. Use **Clear** beside Prompt to empty it, or leave
Generate or switch sides to clear it automatically; the other settings stay in place.
**Save to queue** replaces it at the front of the queue; **Cancel editing** leaves the original in Pending.
Removing the pending job ends its editing session; the form can then be used for a new generation.
Upscale jobs use their own settings dialog and follow the same Pending and queue replacement behavior.
A continued run (its prompts already written, such as after a preview run) opens its setup too: resolution, workflow
options (sampler, steps, latent upscale) and Preview run can change, while the prompt, images, length and workflow stay
as they were planned. **Generated prompts** under the prompt box opens every prompt of the run in the prompt editor,
one to a page: swipe, or use the arrows, to go through them. A run that stops on ComfyUI's *aimdo memory compile
error* is tried once more after ComfyUI is force-restarted; if it fails the same way again, it goes to Failed and
ComfyUI is restarted once more for the next job.

**Latent upscale** (under Resolution, for H3 reference-to-video workflows with the
[Minimax H3 latent upscaler](https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler) installed): the clip is
made at the resolution, its latent is enlarged to the size the megapixel stepper sets (with latent upscale on, the
stepper sets where it ends, held to what the workflow makes well), and a short second pass draws it in at that size.
Resolution, latent upscale and the stepper are one block; the stepper scales any resolution, screens too, and a size past
what the workflow makes well is held to the nearest below. Tap Latent upscale's heading for what the chosen preset does. *Clean* sharpens it as it was, *Hires fix* adds detail (about a 0.35 denoise), *Heavy* reworks more
(about 0.45). Set the resolution low (0.4 MP or so) and the stepper higher. A finished film can be latent-upscaled
from its viewer (Upscale → **Latent**): a copy of its run is made again on the seeds each clip was made with, then
upscaled, as a new film named `<film>_latent`. It takes about as long as the film took to make. Workflows using H3's first/last-frame model
also offer **H3 model: FastVideo 4-step** under Advanced, which runs at 4 steps without a turbo LoRA.
For a saved run in Pending, the settings icon opens its setup in Generate for a new or matching run;
the original stays in Pending. The prompts icon also opens the saved prompts for a continued job in
the queue or Pending.
While a continuation is in Pending, its prompts and seeds can be edited; save them before starting it.
It still reserves the saved run so it cannot be queued twice or discarded while pending.

**Stop** stops the run and cancels its clip in ComfyUI; queued jobs wait until the queue is resumed.
**Cancel** stops the run and starts the next queued job, leaving the run under Pending. Both require a second tap
to confirm. **Continue** brings the cancelled run back behind whatever is queued by then.

**Waiting to be rendered** lists plans not rendered yet and runs that were stopped, failed or cut off by a crash.
**Continue** picks up from the last finished clip, and only the clip that was cut off starts again. H3 Multishot is
an exception: it renders one whole take, so a stopped or failed take starts again from the beginning.

**Fixing a shot:** press **Shots** on a film to watch each clip. Change a prompt if you like and press **Render
again**. In a continuous take every shot after it renders again too, because each starts on the last frame of the
one before. H3 Multishot's **Render take again** instead replaces the entire take.

**Open folder** shows the tab's folder in File Explorer. It's only there on this PC, not on your phone.

**Delete** removes the film along with its clips and prompts. **Shut down** force-stops everything and closes
ComfyUI if the panel started it. Queued jobs come back on hold next time.

### How clips connect

The connection selector appears below Clip length when the estimated film has more than one clip. A single clip
uses separate-moment behavior. If an audio track determines the length, the selector stays available because its
length is not yet known in the form. Changing back to multiple clips restores your previous connection choice.

| | What each clip starts on | Between clips | Redoing a shot |
|---|---|---|---|
| **One continuous take** (default) | The last frame of the clip before | Nothing: it flows | Also redoes every shot after it |
| **Separate moments** | Your image | A short fade | Leaves the others alone |
| **H3 Motion Director** | The previous clip's last frame | Nothing: it flows | Also redoes every shot after it |
| **H3 Multishot** | The previous shot's last frame | The sampler joins the shots | Renders the entire take again |
| **H3 Infinite continuation** | The previous clip's video and sound, carried over in place | The suite crossfades the seam | Also redoes every shot after it |

If a continuous take drifts away from how your image looks, try separate moments.
Ordinary multi-image workflows use separate moments. The H3 choices appear only for compatible saved workflows:
select the adapted **`video_Minimax_H3_T2V_I2V_R2V`** workflow for Motion Director, or a supported H3
reference-to-video workflow for Multishot or H3 Infinite continuation.

**H3 Motion Director** continuous takes require exactly one image. It is the first frame of the first clip;
the last frame of each clip becomes the next clip's first frame. Clips remain individually saved and resumable.

**H3 Multishot** requires the installed `H3MultishotSampler` node from the
[H3 Multishot workflow](https://huggingface.co/joeygambino/MiniMax-H3-Multishot-Workflow), plus the
video-combine nodes. It plans and optionally reviews a separate prompt for each shot, then renders them in one
ComfyUI job with one take seed and one fixed shot length. The sampler generates and joins video and audio; continuity
is not guaranteed. H3 rounds each shot to its 17-frame grid at 24 fps and removes duplicate boundary frames, so the
actual duration can differ slightly from the estimated duration. The step count under the mode controls Multishot's
sampler; the original workflow's sampler settings do not apply, though its model, text encoder and VAEs are used.

Images are subject references by default. Optionally use image 1 as the first frame **and** a subject reference;
reference images are resized and centre-cropped to the output dimensions. Reference videos and audio, OpenH3-IR and
the first-clip preview are unavailable in this mode. Stopping, retrying or changing a shot requires rendering the
whole take again; individual shots cannot be resumed. Exact-prompt mode deliberately repeats the same prompt for
every shot; choose an LLM prompt source for distinct planned actions.

**H3 Infinite continuation** uses [Herrgotts H3 Infinite Continuation Suite](https://github.com/HerrgottMargott/Herrgotts-H3-Infinite-Continuation-Suite)
(v1.4; install it with ComfyUI Manager, or clone it into `ComfyUI/custom_nodes`, then restart ComfyUI). Clip 1 is
made by its Start node and every clip after by its Continue node, which copies the last 39 frames of the clip before,
with their sound, into the new clip and keeps them (Native Masked AV), so motion and dialogue carry on across the
seam. Each clip saves its full video and audio latent under `ComfyUI/output/autogen_h3_infinite/<run>/`, numbered,
so a stopped run continues where it was; the suite's Saved Chain stitcher then makes the film from them, trimming
each carried-over head and crossfading the seams. It needs a ComfyUI build with MiniMax H3's native AV masks
(ComfyUI PR #15375, in 0.43) and the H3 first/last-frame model `minimax_h3_fl2va_pruned_int8_convrot.safetensors`.
Your H3 reference workflow gives the text encoder and VAEs; the model, sampler (Sigma Shift 12/3, res_multistep,
15 steps) and clip length are the suite's (Net New Content: a clip's length is its new footage, after the carried
head). Image 1 is the first frame of clip 1; image 2 is where clip 1 ends, image 3 where clip 2 ends, and so on, as
in the suite's own workflows. It makes its own sound, so narration, an audio file, reference media and OpenH3-IR are
off in this mode.

**Workflow options**, under Generation, are the chosen workflow's own switches and settings, such as a sampler's steps
or a switched group, as the [Image side](image.md#workflow-options) has them. A run keeps them, so the rest of its clips and
any shot made again come out the same way. The MiniMax H3 workflows also offer **H3 Memory Optimization** and **H3 Sparse
Attention** (with its video attention budget) under Advanced, when the [H3-Optimizations](https://github.com/Zironic/H3-Optimizations)
custom node is installed.

**`video_Minimax_H3_T2V_I2V_R2V`** is the Motion Director workflow, which makes text, image and reference clips of H3 in one
workflow. The panel gives its Director one clip at a time: no image is text-to-video, one image is a start frame
(image-to-video) and more are references. Its prompt and nine image boxes are wired in when it's listed, and the Director's own
timeline and refine pass are left out. **Turbo (4-step LoRA)** switches the LoRA and the steps together. The saved workflow
has Sage attention off (it isn't installed) and the DiffAid sparse patch off (it fails under ComfyUI's dynamic VRAM; H3 Sparse
Attention above is the one to use). Reference clips (two or more images) currently fail inside the Director node itself, which
calls ComfyUI's reference node with its arguments in an older order, until that node is updated.
**Upscale a film.** Open a film in the Video tab and press **Upscale** to queue it through NVIDIA RTX Video Super Resolution
(the [RTX VSR Long Video](https://github.com/tritant/ComfyUI_NVIDIA_RTX_VSR_Long_Video) custom node; needs an RTX GPU). Pick a
scale (1.5 to 4×) and a mode. The result is saved beside it as `<name>_upscaled.mp4`, with the sound kept; ComfyUI's own copy of it
is removed. **Prompts** in the same viewer opens the shots of the run that made the film.
Output cards show the workflow, actual resolution, duration, file size, LoRAs and enabled OpenH3-IR settings where recorded.
Upscaled films keep their original metadata independently, with the upscale's own resolution and size. Existing upscales
are given a metadata copy when listed or before their original run is removed, if that run still exists. Each upscale's
`<filename>.metadata.json` accompanies it; keep that file with the video if moving it.
The preview shows its position among visible films, resolution, workflow and prompt model where known. Tap the workflow
and prompt-model line to expand any LoRAs and OpenH3-IR settings. Swipe up or down (or use the up and down arrow keys)
to move between visible films. Older Shorts do not have OpenH3-IR settings recorded.
Its tools use icons; Download, Close and Delete have text labels.

## Time and cost

Rendering takes about 30 minutes per minute of film on the GPU this was built on, so a 10-minute film takes around
5 hours. The ETA learns from each run, per model, workflow, workflow options and size. ComfyUI's queue is shared, so other work there takes its turn between
clips.

A film's prompts take one LLM request, however long the film is, and an upload's title and description take one
more. Claude's cost depends on the film's length and is shown on your account at platform.claude.com.

## The command line

```
python -m pipelines.video.main harbour.jpg "a storm rolls in over the harbour" --duration 3m --llm claude
```

| Option | What it does |
|---|---|
| `--duration` | Film length: `90`, `3m` or `2m30`. From 5 seconds to 10 minutes, default `2m`. It's split into clips as long as the video model makes them. |
| `--llm` | `local`, `gemini` or `claude`. Default: `LLM_PROVIDER`, else `local`. |
| `--start` | `chain` for a normal continuous take (default), `image` for separate moments, `director` for H3 Motion Director chaining, `multishot` for an H3 Multishot take, or `infinite` for H3 Infinite continuation. |
| `--h3-first-frame`, `--h3-multishot-steps N` | For Multishot: use image 1 as the first frame and a reference; set sampling steps (default 20). Multishot also requires `--fixed-clips --clip-seconds N-N`. |
| `--reference IMAGE` | Another image, repeatable. The first one is image 2. |
| `--ref-video FILE`, `--ref-audio FILE` | A reference video or audio clip every clip gets, repeatable, on a workflow that takes them such as MiniMax H3. |
| `--ref-video-role`, `--ref-audio-role` | What each one is for, in order: `motion`, `character` or `place` for a video, `voice`, `music` or `sound` for audio. |
| `--image-role` | What an image after the first is, once per image in order from image 2: `view` (more of the subject), `character`, `place`, or `context` to let the LLM tell by looking (the default). `--image-2-role` still works. |
| `--size 1280x736` | Render size, rounded to multiples of 32. By default it takes the image's shape at the workflow's pixel count. |
| `--seed N` | Clip 1's seed, and the next number for each clip after it. Default: a random seed for every clip. |
| `--plan-only` | Writes the prompts and stops, so you can read them before spending the GPU time. |
| `--upload`, `--privacy` | Uploads when the film is done. Private by default. |
| `--resume RUN` | Continues a saved run. |
| `--redo SHOT` | With `--resume`: renders that shot again. In a chain or H3 Infinite continuation, every shot after it too; Multishot only accepts `1` and rerenders the entire take. |
| `--list` | Lists saved runs. |
| `--check` | Checks ffmpeg, the LLM key and ComfyUI, and makes nothing. |

Ctrl+C cancels the clip in ComfyUI, and `--resume` continues. The plan is in `runs/<run>/state.json`: edit any
`prompt` there and `--resume` uses it.

`python publish.py <film>` or `python publish.py --all` uploads what's in `output/`.

## Using another workflow

**Workflow**, at the top of the form, lists what you saved in ComfyUI, except those ending in `_shorts`, which are tuned for yt-auto-shorts, and those starting `image_`, which are for [Image](image.md). The panel converts the one you pick into API
format when it lists them, and finds its prompt, image, length and size inputs from the graph. **LTX23_I2V_T2V**
stays the default and works as before.

The form asks for what the chosen workflow can take:

| Workflow | Images | Without one |
| --- | --- | --- |
| I2V | 1, required, plus image 2 for the LLM | Can't run |
| I2V/T2V with a switch titled "text to video" | 0-1, plus image 2 for the LLM | The switch goes to text |
| TI2V, where the image plugs into an optional input | 0-1, plus image 2 for the LLM | The image comes out of the workflow |
| T2V, with no Load Image | None | Always from text |
| R2V, with several Load Image nodes | Up to that many, one box each | The empty ones come out, if they're optional |
| MiniMax H3 | Up to 9 images, 3 videos and 3 audio clips, 12 in all | The empty ones come out |

Without an image, the LLM describes everything in full in every prompt and the film is 1280x736, unless you set
a size. With references, every clip gets all of them and the LLM calls them `<Picture 1>`, `<Picture 2>`. A T2V or
R2V workflow can't start a clip on the last frame of the one before, so its clips are separate moments.

A workflow using MiniMax H3's reference-to-video node gets prompts written for H3 instead: its six labelled
fields, the subjects' details named and repeated word for word in every clip, actions sized to how long they really
take. The pipeline adds a Load Video (split into frames and sound) and a Load Audio for each of the node's
`ref_videos` and `ref_audios` that nothing in the saved workflow is wired to. `modules/h3_prompt.py` holds those instructions, rewritten from
[minimax-h3-skill](https://github.com/teskor-hub/minimax-h3-skill) (MIT). A reply without those fields is asked
for again rather than rendered.

A Wan workflow gets prompts written for Wan: a plain paragraph of how things move, with no sound, since it makes
none. Its negative prompt stays what you saved in the workflow. `modules/wan_prompt.py` holds those instructions.

It works out which input is the prompt by following the sampler's positive input back to its text, or from a
node's own `prompt` input. For length it wants a number node with "seconds" or "duration" in its title, or a
`length` input next to `width` and `height`. For size, integer nodes titled "width" and "height", or those same
inputs. A workflow that can't run stays in the list, greyed out, and the hint says why: a model or node that isn't
installed. Subgraphs are opened up as if you had unpacked them. A saved `SaveVideo` becomes VideoHelperSuite's Video Combine, the only way to keep its
clips out of ComfyUI's output folder.

A run keeps its workflow when you continue it or redo a shot. The conversions sit in `logs/workflows/`, so with
ComfyUI off the panel still lists the ones it had last time, and a run starts it.

From the command line, set `COMFYUI_WORKFLOW` to a workflow saved with ComfyUI's **Export (API)**. Next to it, put
a file with the same name ending in `.map.json`, which says which node inputs to fill (see
`workflows/video_workflow.map.json`). `prompt` and `image` are required.

Clips are kept out of ComfyUI's output folder: they render to its temp folder and are downloaded from there.

## Files

```
webapp.py             the panel
main.py               the run: plan, render, stitch, resume
publish.py            uploads what's in output/
start_webapp.pyw      what the shortcut runs
modules/planner.py    writes the shot list and upload text, with Gemini or Claude
modules/h3_prompt.py  what the LLM is told when a film renders on MiniMax H3
modules/wan_prompt.py what the LLM is told when a film renders on Wan
modules/comfy.py      talks to ComfyUI
modules/media.py      images, frames and joining clips, with ffmpeg
modules/run_state.py  what each run has finished
modules/run_eta.py    estimates, learned from earlier runs
modules/publisher.py  uploads to YouTube
modules/saved_workflows.py  turns the workflows saved in ComfyUI into what the pipeline runs
comfyui/              the workflow and which of its inputs get filled
runs/<run>/           a run's state, input image and clips, kept until you delete the film
output/               finished films
uploaded/             films that went to YouTube
inputs/               images the panel received, until a run has its own copy
logs/                 ETA timings, saved queues, the panel's log, converted workflows
```

## Tests

```
python -m unittest discover tests
```

The panel runs the real `main.py` as a real process, with real ffmpeg on tiny synthetic clips, against a fake
ComfyUI and a fake Claude on localhost. They use no GPU, no quota and no money, and everything they make goes to a
temporary folder. The page's script is checked with Node if it's installed.
