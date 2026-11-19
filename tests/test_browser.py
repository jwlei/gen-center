"""Opt-in headless browser checks; enabled by CI, never using live application data."""
import os
import tempfile
import threading
import unittest
from unittest import mock

from fakes import close, fake_comfy
from panel import app as _routes  # noqa: F401
from panel import server
from werkzeug.serving import make_server


@unittest.skipUnless(os.getenv("GEN_CENTER_BROWSER_TESTS") == "1", "headless browser checks are opt-in")
class BrowserTest(unittest.TestCase):
    def test_connection_recovery_presets_and_private_drafts(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as folder:
            comfy = fake_comfy(folder)
            self.addCleanup(close, comfy)
            with mock.patch.dict(os.environ, {"COMFYUI_URL": comfy.url}):
                server._comfyui_cache["at"] = server._saved_workflows_cache["at"] = 0
                http = make_server("127.0.0.1", 0, server.app, threaded=True)
                thread = threading.Thread(target=http.serve_forever)
                thread.start()
                try:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        try:
                            page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
                            errors = []
                            page.on("pageerror", lambda error: errors.append(str(error)))
                            page.goto(f"http://127.0.0.1:{http.server_port}/image")
                            page.wait_for_function("!document.body.classList.contains('page-loading')")
                            page.evaluate("setPrivate(false)")
                            if not page.locator("#imagePromptSection").evaluate("el => el.open"):
                                page.locator("#imagePromptSection > summary").click()
                            page.locator("#imagePrompt").click()
                            page.locator("#promptEditorText").fill("normal browser draft")
                            page.locator("#promptEditorSave").click()
                            page.locator("#privateToggle").click()
                            page.wait_for_function("document.querySelector('#privateToggle').getAttribute('aria-pressed') === 'true'")
                            self.assertEqual(page.locator("#imagePrompt").input_value(), "")
                            if not page.locator("#imagePromptSection").evaluate("el => el.open"):
                                page.locator("#imagePromptSection > summary").click()
                            page.locator("#imagePrompt").click()
                            page.locator("#promptEditorText").fill("private browser draft")
                            page.locator("#promptEditorSave").click()
                            page.locator("#privateToggle").click()
                            page.wait_for_function("document.querySelector('#privateToggle').getAttribute('aria-pressed') === 'false'")
                            self.assertEqual(page.locator("#imagePrompt").input_value(), "normal browser draft")
                            storage = page.evaluate("JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])")
                            self.assertNotIn("private browser draft", storage)
                            form_top = page.locator("#optionsCard").bounding_box()["y"]
                            page.route("**/api/status*", lambda route: route.abort())
                            page.locator("#connectionNotice").wait_for(state="visible", timeout=45000)  # Shown after 30 s down
                            self.assertEqual(page.locator("#optionsCard").bounding_box()["y"], form_top)
                            self.assertEqual(page.locator("#connectionNotice").evaluate(
                                "el => getComputedStyle(el).position"), "fixed")
                            self.assertIn("Retrying automatically", page.locator("#connectionMessage").inner_text())
                            page.unroute("**/api/status*")
                            page.locator("#connectionRetry").click()
                            page.locator("#connectionNotice").wait_for(state="hidden")
                            page.route("**/api/presets", lambda route: route.fulfill(
                                status=500, content_type="application/json", body='{"ok":false,"error":"test disk unavailable"}',
                            ))
                            page.locator("#imagePresetOpen").click()
                            page.locator('[data-preset-save="image"]').click()
                            page.locator("#imagePresetName").fill("Browser test preset")
                            page.locator("#imagePresetConfirm").click()
                            page.wait_for_function("document.querySelector('#imagePresetFeedback').textContent.includes('test disk unavailable')")
                            page.locator('[data-preset-close="image"]').click()
                            page.unroute("**/api/presets")
                            page.evaluate("""() => {
                                const section = document.createElement('div');
                                section.id = 'browserOptions';
                                section.innerHTML = '<div id="browserOptionsBox"></div><div id="browserNegativeSlot"></div>';
                                document.querySelector('#imagePromptSection .section-body').append(section);
                                syncOptions('browserOptions', 'browserOptionsBox',
                                    [{id: 'lora', kind: 'switch', label: 'Use LoRA', default: '0', below: true}], 'browser');
                            }""")
                            lora_hint = page.locator("#browserOptions [data-style-lora-guide]")
                            self.assertTrue(lora_hint.evaluate("el => !!el.closest('.options-subtitle')"))
                            lora_hint.click()
                            page.wait_for_function("document.querySelector('#modelGuideTitle').textContent === 'Style LoRA'")
                            self.assertEqual(page.locator("#modelGuideTitle").inner_text(), "Style LoRA")
                            self.assertIn("not proof of compatibility", page.locator("#modelGuideBody").inner_text())
                            page.locator("#modelGuideClose").click()
                            self.check_workflow_presets(page)
                            self.check_heading_guides(page)
                            self.check_prompt_writer_scroll(page)
                            self.check_private_loras(page)
                            self.check_compact_sections(page)
                            self.check_queue_page_scroll(page)
                            self.check_collection_reorder_scroll(page)
                            self.assertEqual(errors, [])
                        finally:
                            browser.close()
                finally:
                    http.shutdown()
                    http.server_close()
                    thread.join(timeout=10)
                    self.assertFalse(thread.is_alive(), "browser-test HTTP server must stop")

    def check_prompt_writer_scroll(self, page):
        models = [{"id": f"browser-model-{i}", "label": f"Browser model {i}"} for i in range(20)]
        page.route("**/api/local-models", lambda route: route.fulfill(json={"ok": True, "models": models}))
        disabled = page.locator('#imageLlm option[value="local"]').evaluate("el => el.disabled")
        try:
            page.locator('#imageLlm option[value="local"]').evaluate("el => el.disabled = false")
            for width, height in [(1440, 1000), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("openPromptEditor($('imagePrompt'))")
                page.locator("#promptEditorText").focus()
                page.locator("#promptEditorEnhance").click()
                menu = page.locator("#promptEditorWriterMenu")
                menu.wait_for(state="visible")
                self.assertGreater(menu.evaluate("el => el.scrollHeight"), menu.evaluate("el => el.clientHeight"))
                box = menu.bounding_box()
                self.assertGreaterEqual(box["y"], 0)
                self.assertLessEqual(box["y"] + box["height"], height)
                menu.hover()
                page.mouse.wheel(0, 300)
                page.wait_for_function("document.querySelector('#promptEditorWriterMenu').scrollTop > 0")
                menu.evaluate("el => el.scrollTop = 0")
                gutter = menu.evaluate("el => el.offsetWidth - el.clientWidth - 2")
                if gutter > 0:
                    x = box["x"] + box["width"] - 1 - gutter / 2
                    page.mouse.move(x, box["y"] + 25)
                    page.mouse.down()
                    page.mouse.move(x, box["y"] + box["height"] - 20, steps=8)
                    page.mouse.up()
                    self.assertGreater(menu.evaluate("el => el.scrollTop"), 0, "the native menu scrollbar must be draggable")
                page.locator("#promptEditorCancel").click()
        finally:
            page.evaluate("closePromptEditor(false)")
            page.locator('#imageLlm option[value="local"]').evaluate("(el, disabled) => el.disabled = disabled", disabled)
            page.unroute("**/api/local-models")
            page.evaluate("refreshLocalModels()")
            page.set_viewport_size({"width": 1440, "height": 1000})

    def check_private_loras(self, page):
        page.evaluate("""() => {
            window.browserLorasBefore = {workflow: $('imageWorkflow').value};
            imageWorkflows['browser-private-loras'] = {...baseImageTakes(), name: 'browser-private-loras', options: [
                {id: 'lora', kind: 'switch', label: 'Use LoRA', default: '1', below: true},
                {id: 'lora_name', kind: 'choice', label: 'LoRA', parent: 'lora', default: 'NSFW/krea_style.safetensors',
                    choices: ['krea_safe.safetensors', 'NSFW/krea_style.safetensors', 'krea_UNCENSORED.safetensors']},
                {id: 'lora_strength', kind: 'number', label: 'Strength', parent: 'lora', default: '1', min: -2, max: 2, step: 0.05},
                {id: 'lora_extra', kind: 'strength', label: 'LoRA: extra', private_only: true,
                    default: '1', usual: '1', min: -2, max: 2, step: 0.05},
                {id: 'additional_loras', kind: 'lora_stack', default: '[]',
                    choices: ['krea_safe.safetensors', 'NSFW/krea_style.safetensors', 'krea_UNCENSORED.safetensors'],
                    min: -2, max: 2, step: 0.05}
            ]};
            $('imageWorkflow').add(new Option('Browser private LoRAs', 'browser-private-loras'));
            $('imageWorkflow').value = 'browser-private-loras';
            syncImageForm();
        }""")
        choices = "#imageOptionsBox select[name=opt_lora_name]"
        try:
            self.assertEqual(page.locator(choices).evaluate("el => [...el.options].map(o => o.value)"), ["krea_safe.safetensors"])
            self.assertEqual(page.locator('#imageOptionsBox input[type=checkbox][name=opt_lora_extra_on]').count(), 0)
            page.locator("#imageOptionsBox [data-add-lora]").evaluate("el => el.click()")
            self.assertEqual(page.locator("#imageOptionsBox [data-lora-index]").count(), 1)
            page.locator("#imageOptionsBox [data-lora-strength]").evaluate("el => {el.value = '0.5'; el.dispatchEvent(new Event('change', {bubbles: true}));}")
            page.locator("#imageLoraStrengthTest").evaluate("el => {el.checked = true; el.dispatchEvent(new Event('change', {bubbles: true}));}")
            page.locator("#imageLoraStyleTest").evaluate("el => {el.checked = true; el.dispatchEvent(new Event('change', {bubbles: true}));}")
            page.locator("#imageLoraTestStep").evaluate("el => {el.value = '0.5'; el.dispatchEvent(new Event('change', {bubbles: true}));}")
            self.assertIn("4 images", page.locator("#imageLoraTests [data-lora-test-hint]").inner_text())
            self.assertTrue(page.locator("#imageCount").is_disabled())
            page.evaluate("setPrivate(true)")
            page.wait_for_function("privateMode && !privateChanging")
            page.evaluate("$('imageWorkflow').value = 'browser-private-loras'; syncImageForm()")
            self.assertEqual(page.locator(choices).evaluate("el => el.options.length"), 3)
            page.locator("#imageOptionsBox [data-add-lora]").evaluate("el => el.click()")
            page.locator("#imageOptionsBox [data-lora-name]").evaluate("el => {el.value = 'NSFW/krea_style.safetensors'; el.dispatchEvent(new Event('change', {bubbles: true}));}")
            page.locator(choices).evaluate("el => {el.value = 'krea_UNCENSORED.safetensors'; el.dispatchEvent(new Event('change', {bubbles: true}));}")
            page.evaluate("setPrivate(false)")
            page.wait_for_function("!privateMode && !privateChanging")
            self.assertEqual(page.locator(choices).evaluate("el => [...el.options].map(o => o.value)"), ["krea_safe.safetensors"])
            self.assertEqual(page.locator("#imageOptionsBox [data-lora-strength]").input_value(), "0.5")
            page.evaluate("useDefaultOptions($('imageOptionsBox'))")
            self.assertEqual(page.locator(choices).input_value(), "krea_safe.safetensors")
            page.evaluate("setPrivate(true)")
            page.wait_for_function("privateMode && !privateChanging")
            self.assertEqual(page.locator(choices).input_value(), "krea_UNCENSORED.safetensors")
            self.assertEqual(page.locator("#imageOptionsBox [data-lora-name]").input_value(), "NSFW/krea_style.safetensors")
            storage = page.evaluate("JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])")
            self.assertNotIn("krea_UNCENSORED.safetensors", storage)
        finally:
            page.evaluate("setPrivate(false)")
            page.wait_for_function("!privateMode && !privateChanging")
            page.evaluate("""() => {
                $('imageWorkflow').value = window.browserLorasBefore.workflow;
                delete imageWorkflows['browser-private-loras'];
                document.querySelector('#imageWorkflow option[value="browser-private-loras"]').remove();
                delete window.browserLorasBefore;
                syncImageForm();
            }""")

    def check_queue_page_scroll(self, page):
        page.set_viewport_size({"width": 390, "height": 844})
        page.emulate_media(reduced_motion="reduce")
        page.evaluate("""() => {
            showPage('status');
            const box = document.getElementById('queueBox');
            for (const [where, height] of [['before', 300], ['after', 900]]) {
                const space = document.createElement('div');
                space.id = 'browser-scroll-' + where;
                space.style.height = height + 'px';
                box[where](space);
            }
        }""")
        try:
            for active in ("runQueue", "stoppedRuns", "failedRuns"):
                page.evaluate("""id => {
                    for (const section of document.querySelectorAll('#queueBox > .queue')) {
                        setQueueSectionOpen(section, false);
                    }
                    window.scrollTo(0, 0);
                    document.querySelector('#' + id + ' ' + (id === 'runQueue' ? '[data-fold-queue]' : 'summary')).click();
                }""", active)
                heading = page.locator(f"#{active} " + (".queue-head" if active == "runQueue" else "summary"))
                page.wait_for_function("""id => {
                    const header = document.querySelector('#' + id + ' ' + (id === 'runQueue' ? '.queue-head' : 'summary'));
                    return Math.abs(header.getBoundingClientRect().top) < 2 && window.scrollY > 50;
                }""", arg=active)
                self.assertLess(abs(heading.bounding_box()["y"]), 2)
                body = page.locator(f"#{active} " + (".queue-list" if active == "runQueue" else ".stopped-body"))
                body.evaluate("el => el.scrollTop = el.scrollHeight")
                body.hover()
                before = page.evaluate("window.scrollY")
                page.mouse.wheel(0, 200)
                page.wait_for_function("before => window.scrollY > before + 20", arg=before)
                self.assertTrue(body.evaluate("el => el.scrollHeight - el.clientHeight - el.scrollTop < 2"))
                body.evaluate("el => el.scrollTop = 0")
                body.hover()
                before = page.evaluate("window.scrollY")
                page.mouse.wheel(0, -200)
                page.wait_for_function("before => window.scrollY < before - 20", arg=before)
                self.assertEqual(body.evaluate("el => el.scrollTop"), 0)
            page.emulate_media(reduced_motion="no-preference")
            page.evaluate("""() => {
                window.scrollTo(0, 0);
                document.querySelector('#stoppedRuns summary').click();
            }""")
            page.wait_for_function("""() => Math.abs(document.querySelector('#stoppedRuns summary').getBoundingClientRect().top) < 2
                && !document.querySelector('#stoppedRuns')._sectionAnimation""")
        finally:
            page.evaluate("""() => {
                document.getElementById('browser-scroll-before').remove();
                document.getElementById('browser-scroll-after').remove();
            }""")
            page.emulate_media(reduced_motion="reduce")

    def check_collection_reorder_scroll(self, page):
        page.route("**/image-runs/browser-scroll/**", lambda route: route.fulfill(
            content_type="image/svg+xml", body='<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"/>'))
        page.route("**/api/collections/**", lambda route: route.fulfill(json={"ok": True}))
        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("""() => {
            window.browserCollectionsBefore = {collections, allImageSets, nsfwView};
            nsfwView = false;
            allImageSets = [{id: 'browser-scroll', label: 'Browser scroll',
                images: Array.from({length: 120}, (_, i) => ({position: i + 1, file: i + '.png', title: 'Image ' + i, version: 1}))}];
            collections = Array.from({length: 48}, (_, i) => ({id: 'edge-' + i, name: 'Collection ' + i,
                items: [{kind: 'image', set: 'browser-scroll', file: '0.png'}]}));
            collections[0].items = allImageSets[0].images.map(image => ({kind: 'image', set: 'browser-scroll', file: image.file}));
            setPipeline('image');
            showPage('output');
            pollGeneration++;
            if (pollAbort) pollAbort.abort();
            polling = true;
            document.body.classList.remove('output-pending');
            renderCollections();
            showCollections(true, false);
            collectionsArranging = true;
            collectionSelected = 'edge-0';
            showCollectionArranging();
        }""")
        try:
            tile = page.locator('#collections [data-collection="edge-0"]')
            tile.scroll_into_view_if_needed()
            box = tile.bounding_box()
            x = box["x"] + box["width"] / 2
            page.mouse.move(x, box["y"] + box["height"] / 2)
            page.mouse.down()
            before = page.evaluate("document.scrollingElement.scrollTop")
            bottom = page.locator("#stick").bounding_box()["y"] - 5
            page.mouse.move(x, bottom, steps=4)
            page.wait_for_function("before => document.scrollingElement.scrollTop > before + 100", arg=before)
            before = page.evaluate("document.scrollingElement.scrollTop")
            page.mouse.move(x, 5, steps=4)
            page.wait_for_function("before => document.scrollingElement.scrollTop < before - 50", arg=before)
            page.mouse.up()
            page.wait_for_function("gridDrag === null && !document.querySelector('.grid-ghost')")

            for width, height in ((1440, 1000), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("openThumbGrid({collection: 'edge-0'})")
                page.locator("#thumbGridArrange").click()
                page.locator('#thumbGridBody [data-grid-index="0"]').click()
                tile = page.locator('#thumbGridBody [data-grid-index="0"]')
                box = tile.bounding_box()
                x = box["x"] + box["width"] / 2
                page.mouse.move(x, box["y"] + box["height"] / 2)
                page.mouse.down()
                body = page.locator("#thumbGridBody")
                bounds = body.bounding_box()
                page.mouse.move(x, bounds["y"] + bounds["height"] - 5, steps=4)
                page.wait_for_function("document.getElementById('thumbGridBody').scrollTop > 100")
                before = body.evaluate("el => el.scrollTop")
                page.mouse.move(x, bounds["y"] + 5, steps=4)
                page.wait_for_function("before => document.getElementById('thumbGridBody').scrollTop < before - 50", arg=before)
                page.mouse.up()
                page.wait_for_function("gridDrag === null && !document.querySelector('.grid-ghost')")
                page.locator("#thumbGridClose").click()
        finally:
            page.mouse.up()
            page.evaluate("""() => {
                if (gridDrag) dropGrid({pointerId: gridDrag.pointer});
                document.getElementById('thumbGrid').close();
                ({collections, allImageSets, nsfwView} = window.browserCollectionsBefore);
                delete window.browserCollectionsBefore;
                collectionsArranging = false;
                renderCollections();
            }""")
            page.unroute("**/image-runs/browser-scroll/**")
            page.unroute("**/api/collections/**")

    def check_workflow_presets(self, page):
        values = page.evaluate("presetValues('image')")
        saved = [
            {"name": "Browser preset", "values": values, "default": False},
            {"name": "Alternate", "values": {**values, "count": "2"}, "default": False},
        ]
        page.evaluate("""items => {
            presets.image = items;
            syncPresets('image');
        }""", saved)
        trigger = page.locator("#imagePresetOpen")
        self.assertEqual(trigger.inner_text(), "Browser preset")
        self.assertEqual(trigger.evaluate("el => el.closest('.workflow-head') !== null"), True)
        trigger.click()
        self.assertTrue(page.locator("#imagePresetDialog").is_visible())
        self.assertEqual(page.locator("#imagePreset").input_value(), "Browser preset")
        before = page.locator("#imagePrompt").input_value()
        page.locator("#imagePreset").select_option("Alternate")
        self.assertEqual(page.locator("#imagePrompt").input_value(), before)
        page.locator('[data-preset-cancel="image"]').click()
        self.assertEqual(page.locator("#imagePrompt").input_value(), before)
        page.locator("#imagePreset").select_option("Alternate")
        page.locator('[data-preset-confirm="image"]').click()
        self.assertEqual(page.locator("#imagePrompt").input_value(), "")
        self.assertEqual(page.locator('#formImage [name="count"]').input_value(), "2")
        page.locator("#imagePreset").select_option("Browser preset")

        def save_presets(route):
            body = route.request.post_data_json
            if "values" in body:
                saved.append({"name": body["name"], "values": body["values"], "default": False})
            else:
                for preset in saved:
                    preset["default"] = preset["name"] == body["name"] and body["default"]
            route.fulfill(status=200, json={"ok": True, "presets": {"image": saved}})

        page.route("**/api/presets", save_presets)
        star = page.locator('[data-preset-default="image"]')
        star.click()
        page.wait_for_function("""document.querySelector('[data-preset-default="image"]').getAttribute('aria-pressed') === 'true'""")
        page.locator('[data-preset-save="image"]').click()
        self.assertTrue(page.locator("#imagePresetName").is_visible())
        page.locator("#imagePresetName").fill("Saved in modal")
        page.locator('[data-preset-confirm="image"]').click()
        page.wait_for_function("document.getElementById('imagePreset').value === 'Saved in modal'")
        page.locator("#imagePresetDialog").press("Escape")
        self.assertFalse(page.locator("#imagePresetDialog").is_visible())
        self.assertEqual(trigger.inner_text(), "Saved in modal")
        trigger.click()
        self.assertEqual(page.locator("#imagePreset").input_value(), "Saved in modal")
        page.locator('[data-preset-close="image"]').click()
        page.unroute("**/api/presets")
        page.evaluate("presets.image = []; syncPresets('image')")
        self.assertEqual(trigger.inner_text(), "Preset")

    def check_heading_guides(self, page):
        page.evaluate("setPipeline('video'); showPage('generate'); syncGuideLink('video')")
        icon = page.locator("#videoGuideLink")
        self.assertTrue(icon.evaluate("el => !!el.closest('.workflow-head .field-heading')"))
        icon.click()
        page.wait_for_function("document.getElementById('modelGuideTitle').textContent === 'LTX-2.3'")
        self.assertIn("image boxes below", page.locator("#modelGuideBody").inner_text())
        page.locator("#modelGuideClose").click()
        self.assertTrue(page.locator("#videoWorkflowHelp").is_hidden())
        page.evaluate("""() => {
            setPipeline('image');
            workflowGuides.image = {};
            builtInGuides.image = null;
            syncGuideLink('image');
        }""")
        page.locator("#imageGuideLink").click()
        self.assertTrue(page.locator("#imageWorkflowHelp").is_visible())
        page.locator("#imageGuideLink").click()
        self.assertTrue(page.locator("#imageWorkflowHelp").is_hidden())

    def check_compact_sections(self, page):
        page.evaluate("""() => {
            pollGeneration++;
            if (pollAbort) pollAbort.abort();
            polling = true;
            panelConnection.success();
        }""")
        page.emulate_media(reduced_motion="no-preference")
        opacities = page.evaluate("""() => {
            const notice = document.getElementById('connectionNotice');
            const sample = show => {
                getComputedStyle(notice).opacity;
                if (show) panelConnection.failure(new Error('Browser animation check'));
                else panelConnection.success();
                const animations = notice.getAnimations();
                const opacity = animations.find(animation => animation.transitionProperty === 'opacity');
                if (!opacity) throw new Error('Connection notice must animate opacity');
                opacity.pause();
                opacity.currentTime = opacity.effect.getComputedTiming().duration / 2;
                const value = Number(getComputedStyle(notice).opacity);
                for (const animation of animations) animation.finish();
                return value;
            };
            return [sample(true), sample(false)];
        }""")
        for opacity in opacities:
            self.assertGreater(opacity, 0)
            self.assertLess(opacity, 1)
        page.emulate_media(reduced_motion="reduce")
        page.locator("#keepSectionsOpen").click()
        page.locator("#keepSectionsOpen").click()
        for width, height in ((1440, 1000), (1920, 1080), (1024, 900), (390, 844)):
            with self.subTest(viewport=width):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("showPage('generate')")
                self.assertEqual(page.locator("#keepSectionsOpen").evaluate(
                    "el => el.previousElementSibling.dataset.defaults"), "imageOptionsBox")
                self.assertTrue(page.locator("#keepSectionsOpen").evaluate("el => !!el.closest('#formImage .workflow-head')"))
                self.assertEqual(page.locator(".wrap").evaluate(
                    "el => getComputedStyle(el).paddingLeft"), "8px")
                self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                estimate = page.evaluate("""() => {
                    const eta = document.getElementById('goBarEta');
                    eta.innerHTML = 'Estimate: <b>1 min</b>';
                    const label = document.createRange();
                    label.selectNode(eta.firstChild);
                    return {label: label.getBoundingClientRect().bottom,
                        time: eta.querySelector('b').getBoundingClientRect().top};
                }""")
                self.assertGreaterEqual(estimate["time"], estimate["label"] - 1)
                page.locator("#imageGeneration > summary").click()
                page.wait_for_function("document.querySelector('#imageGeneration').open")
                self.assertFalse(page.locator("#imagePromptSection").evaluate("el => el.open"))
                self.assertEqual(page.locator("#imageWorkflow").evaluate("el => el.closest('details')"), None)
                self.assertEqual(page.locator("#imageWorkflow").bounding_box()["height"], 28)
                page.evaluate("""() => {
                    document.querySelector('#imageGeneration .section-body').insertAdjacentHTML(
                        'beforeend', '<div class="layout-fixture">' + '<p>Extra generation content</p>'.repeat(80) + '</div>');
                }""")
                headers = page.locator("#formImage > details:not([hidden]) > summary")
                footer = page.locator("#stick").bounding_box()
                card = page.locator("#optionsCard").bounding_box()
                self.assertAlmostEqual(card["y"] + card["height"], footer["y"], delta=2)
                last = headers.last.bounding_box()
                self.assertAlmostEqual(last["y"] + last["height"], footer["y"], delta=2)
                page.wait_for_function("document.querySelector('#imageGeneration').classList.contains('scroll-below')")
                before = headers.evaluate_all("els => els.map(el => el.getBoundingClientRect().top)")
                page.locator("#imageGeneration .section-body").evaluate("el => el.scrollTop = el.scrollHeight")
                page.wait_for_function("!document.querySelector('#imageGeneration').classList.contains('scroll-below')")
                self.assertEqual(before, headers.evaluate_all("els => els.map(el => el.getBoundingClientRect().top)"))
                self.assertTrue(page.locator("#imageGeneration .section-body").evaluate("el => el.scrollTop > 0"))
                form = page.locator("#formImage").bounding_box()
                for box in headers.all():
                    bounds = box.bounding_box()
                    self.assertGreaterEqual(bounds["y"], form["y"])
                    self.assertLessEqual(bounds["y"] + bounds["height"], form["y"] + form["height"] + 1)
                page.locator("#imagePromptSection > summary").click()
                self.assertFalse(page.locator("#imageGeneration").evaluate("el => el.open"))
                page.locator("#keepSectionsOpen").click()
                page.locator("#imageGeneration > summary").click()
                self.assertTrue(page.locator("#imagePromptSection").evaluate("el => el.open"))
                page.locator("#keepSectionsOpen").click()
                page.locator(".layout-fixture").evaluate("el => el.remove()")
                if page.locator("#imageGeneration").evaluate("el => el.open"):
                    page.locator("#imageGeneration > summary").click()
                page.evaluate("""() => {
                    for (const section of document.querySelectorAll('#formImage details.section[open]')) {
                        section.querySelector('summary').click();
                    }
                }""")
                page.wait_for_function("!document.querySelector('#formImage details.section[open]')")
                positions = headers.evaluate_all("""els => els.map(el => {
                    const box = el.getBoundingClientRect(); return {top: box.top, bottom: box.bottom};
                })""")
                for previous, following in zip(positions, positions[1:]):
                    self.assertLessEqual(following["top"] - previous["bottom"], 2)
                self.assertGreater(footer["y"] - positions[-1]["bottom"], 50)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.evaluate("setGenerationSection(document.getElementById('imageGeneration'), true)")
        page.emulate_media(reduced_motion="no-preference")
        motion = page.evaluate("""async () => {
            const generation = document.getElementById('imageGeneration');
            const prompt = document.getElementById('imagePromptSection');
            const heading = prompt.querySelector('summary');
            const firstTop = heading.getBoundingClientRect().top;
            heading.click();
            const sample = section => {
                const animation = section._sectionAnimation;
                if (!animation) throw new Error('Sections must animate opening and closing');
                animation.pause();
                animation.currentTime = 125;
                const frames = animation.effect.getKeyframes();
                return [parseFloat(frames[0].height), section.getBoundingClientRect().height,
                    parseFloat(frames[1].height)];
            };
            const samples = [sample(generation), sample(prompt)];
            const closingBodyVisible = generation.querySelector('.section-body').getBoundingClientRect().height > 0;
            const upwardMiddle = heading.getBoundingClientRect().top;
            const finish = async () => {
                for (const section of document.querySelectorAll('#formImage details.section')) {
                    if (section._sectionAnimation) section._sectionAnimation.finish();
                }
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            };
            await finish();
            const upwardEnd = heading.getBoundingClientRect().top;
            generation.querySelector('summary').click();
            sample(generation);
            sample(prompt);
            const downwardMiddle = heading.getBoundingClientRect().top;
            await finish();
            const downwardEnd = heading.getBoundingClientRect().top;
            // Reverse an in-flight transition as well as a settled one.
            heading.click();
            sample(generation);
            sample(prompt);
            generation.querySelector('summary').click();
            for (const section of document.querySelectorAll('#formImage details.section')) {
                if (section._sectionAnimation) section._sectionAnimation.finish();
            }
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            setGenerationSection(generation, false);
            sample(generation);
            const last = document.querySelector('#formImage details.section:last-of-type > summary');
            const bottomGap = document.getElementById('stick').getBoundingClientRect().top - last.getBoundingClientRect().bottom;
            for (const section of document.querySelectorAll('#formImage details.section')) {
                if (section._sectionAnimation) section._sectionAnimation.finish();
            }
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            const closedGap = document.getElementById('stick').getBoundingClientRect().top - last.getBoundingClientRect().bottom;
            setGenerationSection(generation, true);
            for (const section of document.querySelectorAll('#formImage details.section')) {
                if (section._sectionAnimation) section._sectionAnimation.finish();
            }
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            return {samples, open: generation.open, closed: !prompt.open,
                cleaned: !generation.style.height && !prompt.style.height, closingBodyVisible, bottomGap, closedGap,
                upward: [firstTop, upwardMiddle, upwardEnd],
                downward: [upwardEnd, downwardMiddle, downwardEnd]};
        }""")
        for start, middle, end in motion["samples"]:
            self.assertGreater(middle, min(start, end))
            self.assertLess(middle, max(start, end))
        self.assertTrue(motion["open"] and motion["closed"] and motion["cleaned"])
        self.assertTrue(motion["closingBodyVisible"])
        self.assertGreater(motion["bottomGap"], 1)
        self.assertGreater(motion["closedGap"], motion["bottomGap"])
        self.assertGreater(motion["upward"][0], motion["upward"][1])
        self.assertGreater(motion["upward"][1], motion["upward"][2])
        self.assertLess(motion["downward"][0], motion["downward"][1])
        self.assertLess(motion["downward"][1], motion["downward"][2])
        page.emulate_media(reduced_motion="reduce")
        page.evaluate("""() => {
            const options = [
                {id: 'lora', kind: 'switch', label: 'Use LoRA', default: '1', below: true},
                {id: 'lora_name', parent: 'lora', kind: 'choice', label: 'LoRA', default: 'style', choices: ['style']},
                {id: 'lora_strength', parent: 'lora', kind: 'number', label: 'Strength', default: '1', min: -2, max: 2, step: .05},
            ];
            imageWorkflows['browser-inline-lora'] = {...baseImageTakes(), name: 'browser-inline-lora', options};
            document.querySelector('#imageWorkflow').add(new Option('Browser LoRA', 'browser-inline-lora'));
            document.querySelector('#imageWorkflow').value = 'browser-inline-lora';
            syncImageForm();
        }""")
        page.locator("#imageOptions > summary").click()
        line = page.locator("#imageOptions .lora-line")
        checkbox = line.locator("[type=checkbox]")
        for checked in (False, True):
            checkbox.set_checked(checked)
            selector = line.locator("select")
            strength = line.locator("[type=number]")
            self.assertTrue(selector.is_visible())
            positions = [el.bounding_box() for el in (checkbox, selector, strength)]
            self.assertLess(max(box["y"] for box in positions) - min(box["y"] for box in positions), 8)
            self.assertLess(strength.bounding_box()["width"], 65)
        page.evaluate("setPipeline('video'); showPage('generate'); document.querySelector('#videoPromptSection').open = true")
        page.locator("#llm").select_option("local")
        self.assertTrue(page.locator("#videoLocalModel").is_visible())
        page.route("**/api/write-prompt?*", lambda route: route.fulfill(
            status=200, json={"ok": True, "seconds": 1, "model": "qwen3-14b"}))
        page.route("**/api/write-prompt", lambda route: route.fulfill(
            status=200, json={"ok": True, "prompt": "A locally written scene"}))
        page.evaluate("""async () => {
            openPromptEditor(document.querySelector('#prompt'));
            document.querySelector('#promptEditorText').value = 'A scene';
            await enhanceInEditor({id: 'local', model: 'qwen3-14b'});
            closePromptEditor(true);
        }""")
        self.assertEqual(page.locator("#videoPromptWriterModel").input_value(), "qwen3-14b")
        self.assertEqual(page.locator("#videoLocalModel").input_value(), "qwen3-14b")
        page.evaluate("""() => {
            for (const [id, title] of [['runQueue', 'Queue'], ['stoppedRuns', 'Pending'], ['failedRuns', 'Failed']]) {
                const el = document.getElementById(id);
                el.hidden = false;
                el._open = false;
                const rows = '<div class="stopped-run">Queued work</div>'.repeat(40);
                el.innerHTML = id === 'runQueue'
                    ? '<div class="queue-head"><button type="button" data-fold-queue aria-expanded="false">Queue</button></div><div class="queue-list" hidden>' + rows + '</div>'
                    : '<details class="stopped-fold"><summary>' + title + '</summary><div class="stopped-body">' + rows + '</div></details>';
                el.dataset.html = el.innerHTML;
            }
            showPage('status');
            setRunTab('queue');
        }""")
        page.emulate_media(reduced_motion="no-preference")
        movement = page.evaluate("""async () => {
            const queue = document.getElementById('runQueue');
            const pending = document.getElementById('stoppedRuns');
            const failed = document.getElementById('failedRuns');
            const finish = async () => {
                for (const section of document.querySelectorAll('#queueBox > .queue')) {
                    if (section._sectionAnimation) section._sectionAnimation.finish();
                }
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            };
            const probe = async (control, heading) => {
                const before = heading.getBoundingClientRect().top;
                control.click();
                const animations = [...document.querySelectorAll('#queueBox > .queue')]
                    .map(el => el._sectionAnimation).filter(Boolean);
                if (animations.length < 2) throw new Error('Both queue sections must animate');
                for (const animation of animations) { animation.pause(); animation.currentTime = 125; }
                const middle = heading.getBoundingClientRect().top;
                const closing = document.querySelector('#queueBox .queue-closing .queue-list, #queueBox .queue-closing .stopped-body');
                const closingVisible = closing && closing.getBoundingClientRect().height > 0;
                await finish();
                return {positions: [before, middle, heading.getBoundingClientRect().top], closingVisible};
            };
            queue.querySelector('[data-fold-queue]').click();
            await finish();
            const pendingUp = await probe(pending.querySelector('summary'), pending.querySelector('summary'));
            const pendingDown = await probe(queue.querySelector('[data-fold-queue]'), pending.querySelector('summary'));
            const failedUp = await probe(failed.querySelector('summary'), failed.querySelector('summary'));
            setQueueAccordionSection(failed, false);
            await finish();
            return {pendingUp, pendingDown, failedUp};
        }""")
        for key in ("pendingUp", "failedUp"):
            start, middle, end = movement[key]["positions"]
            self.assertGreater(start, middle)
            self.assertGreater(middle, end)
            self.assertTrue(movement[key]["closingVisible"])
        start, middle, end = movement["pendingDown"]["positions"]
        self.assertLess(start, middle)
        self.assertLess(middle, end)
        self.assertTrue(movement["pendingDown"]["closingVisible"])
        page.emulate_media(reduced_motion="reduce")
        for width, height in ((1440, 1000), (390, 844)):
            with self.subTest(status_viewport=width):
                page.set_viewport_size({"width": width, "height": height})
                for active in ("runQueue", "stoppedRuns"):
                    page.locator(f"#{active} " + ("[data-fold-queue]" if active == "runQueue" else "summary")).click()
                    page.wait_for_function("""(id) => document.getElementById(id).classList.contains('queue-open')
                        && document.querySelectorAll('#queueBox > .queue.queue-open').length === 1""", arg=active)
                    headers = page.locator("#runQueue .queue-head, #stoppedRuns summary, #failedRuns summary")
                    before = headers.evaluate_all("els => els.map(el => el.getBoundingClientRect().top)")
                    body = page.locator(f"#{active} " + (".queue-list" if active == "runQueue" else ".stopped-body"))
                    body.evaluate("el => el.scrollTop = el.scrollHeight")
                    self.assertTrue(body.evaluate("el => el.scrollTop > 0"))
                    self.assertEqual(before, headers.evaluate_all("els => els.map(el => el.getBoundingClientRect().top)"))
                    queue = page.locator("#queueBox").bounding_box()
                    for header in headers.all():
                        box = header.bounding_box()
                        self.assertGreaterEqual(box["y"], queue["y"])
                        self.assertLessEqual(box["y"] + box["height"], queue["y"] + queue["height"] + 1)
        self.assertTrue(page.locator("#runQueue .queue-list").is_hidden())
        page.evaluate("document.getElementById('keepSectionsOpen').click()")
        page.locator("#failedRuns summary").click()
        page.wait_for_function("!document.querySelector('#stoppedRuns details').open")
        self.assertFalse(page.locator("#stoppedRuns details").evaluate("el => el.open"))
