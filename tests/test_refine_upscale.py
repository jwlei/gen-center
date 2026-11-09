"""Hires fix and Ultimate SD Upscale, spliced into the set's own workflow after its last sampler."""
import copy
import unittest

from pipelines.image import refine_upscale as ru

KSAMPLER = {
    "1": {"class_type": "UNETLoader", "inputs": {}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat"}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
    "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024}},
    "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
                                               "seed": 5, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1}},
    "6": {"class_type": "VAELoader", "inputs": {}},
    "7": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["6", 0]}},
    "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0]}},
}


def two_passes():
    """As Krea 2 SFW/NSFW: a first pass, a second on its latent, then SeedVR2 on the decoded image."""
    api = copy.deepcopy(KSAMPLER)
    api["5"]["class_type"] = "ClownsharKSampler_Beta"
    api["5"]["inputs"]["sampler_name"] = "res_2s"
    api["9"] = {"class_type": "ClownsharKSampler_Beta", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                                                                   "latent_image": ["5", 0], "denoise": ["10", 0], "steps": 6, "cfg": 1.0,
                                                                   "sampler_name": "res_2s", "scheduler": "beta57", "seed": 9}}
    api["10"] = {"class_type": "PrimitiveFloat", "inputs": {"value": 0.5}}
    api["7"]["inputs"]["samples"] = ["9", 0]
    api["11"] = {"class_type": "SeedVR2VideoUpscaler", "inputs": {"image": ["7", 0]}}
    api["8"]["inputs"]["images"] = ["11", 0]
    return api


class NoHiresTest(unittest.TestCase):
    def test_hires_fix_is_gone(self):
        self.assertNotIn("hires", ru.SPLICES)
        self.assertNotIn("Hires fix", ru.IN_GENERATION)

    def test_no_decoded_sampler_is_unsupported(self):
        with self.assertRaises(ru.Unsupported):
            ru.usdu({"1": {"class_type": "SaveImage", "inputs": {}}}, "up.png")


class UltimateTest(unittest.TestCase):
    def test_ksampler_gives_model_prompts_and_its_settings(self):
        api = ru.usdu(copy.deepcopy(KSAMPLER), "up.png", denoise=0.3)
        node = api["ru_usdu"]
        self.assertEqual(node["class_type"], "UltimateSDUpscale")
        inputs = node["inputs"]
        self.assertEqual((inputs["model"], inputs["positive"], inputs["negative"], inputs["vae"]), (["1", 0], ["2", 0], ["3", 0], ["6", 0]))
        self.assertEqual((inputs["steps"], inputs["seed"], inputs["sampler_name"], inputs["scheduler"], inputs["denoise"]), (8, 5, "euler", "simple", 0.3))
        self.assertEqual((inputs["mode_type"], inputs["tile_width"], inputs["mask_blur"], inputs["upscale_by"]), ("Chess", 768, 16, 2.0))
        self.assertEqual(api["ru_model"]["inputs"]["model_name"], "4x-UltraSharp.pth")
        self.assertEqual(api["ru_show"]["inputs"]["images"], ["ru_usdu", 0])
        self.assertNotIn("5", api, "the sampler itself doesn't run")

    def test_a_sampler_ksampler_lacks_runs_as_euler(self):
        inputs = ru.usdu(two_passes(), "up.png")["ru_usdu"]["inputs"]
        self.assertEqual((inputs["sampler_name"], inputs["scheduler"]), ("euler", "simple"))

    def test_a_guider_goes_to_the_guider_node(self):
        api = copy.deepcopy(KSAMPLER)
        api["5"] = {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["12", 0], "guider": ["13", 0], "sampler": ["14", 0],
                                                                       "sigmas": ["15", 0], "latent_image": ["4", 0]}}
        for node_id in ("12", "13", "14", "15"):
            api[node_id] = {"class_type": "X", "inputs": {}}
        node = ru.usdu(api, "up.png")["ru_usdu"]
        self.assertEqual(node["class_type"], "UltimateSDUpscaleGuider")
        self.assertEqual((node["inputs"]["guider"], node["inputs"]["sigmas"]), (["13", 0], ["ru_split", 1]))

    def test_sampler_custom_keeps_its_own_sampler_and_schedule(self):
        api = copy.deepcopy(KSAMPLER)
        api["5"] = {"class_type": "SamplerCustom", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "cfg": 4.0,
                                                              "sampler": ["14", 0], "sigmas": ["15", 0], "latent_image": ["4", 0], "noise_seed": 3}}
        for node_id in ("14", "15"):
            api[node_id] = {"class_type": "X", "inputs": {}}
        node = ru.usdu(api, "up.png")["ru_usdu"]
        self.assertEqual(node["class_type"], "UltimateSDUpscaleCustomSample")
        self.assertEqual((node["inputs"]["custom_sampler"], node["inputs"]["custom_sigmas"], node["inputs"]["cfg"]), (["14", 0], ["ru_split", 1], 4.0))


class InGenerationTest(unittest.TestCase):
    def test_each_upscale_ends_exactly_at_the_size_chosen_after_freeing_vram(self):
        for method, inner in (("ultrasharp", "ru_sharp"), ("usdu", "ru_usdu"), ("seedvr2", "ru_seedvr2")):
            api = ru.in_generation(two_passes(), method, (2048, 3072), scale=2.5)
            self.assertEqual(api["11"]["inputs"]["image"], ["ru_size", 0], f"{method}: what came after reads the upscaled image")
            self.assertEqual((api["ru_size"]["inputs"]["width"], api["ru_size"]["inputs"]["height"]), (2048, 3072))
            self.assertEqual(api["ru_size"]["inputs"]["image"], [inner, 0])
            self.assertEqual(api["ru_free"]["inputs"]["image"], ["7", 0], "the set's model unloaded first")
            self.assertIn("5", api, "the workflow still makes its image")

    def test_ultimate_sd_upscales_by_the_scale_and_seedvr2_to_the_shorter_side(self):
        self.assertEqual(ru.in_generation(copy.deepcopy(KSAMPLER), "usdu", (2000, 2000), scale=2.5)["ru_usdu"]["inputs"]["upscale_by"], 2.5)
        self.assertEqual(ru.in_generation(copy.deepcopy(KSAMPLER), "usdu", (9000, 9000), scale=9)["ru_usdu"]["inputs"]["upscale_by"], ru.MOST_SCALE)
        self.assertEqual(ru.in_generation(copy.deepcopy(KSAMPLER), "seedvr2", (2160, 3840))["ru_seedvr2"]["inputs"]["resolution"], 2160)

    def test_without_free_memory_it_reads_the_decoder(self):
        api = ru.in_generation(copy.deepcopy(KSAMPLER), "ultrasharp", (2048, 2048), free_memory=False)
        self.assertNotIn("ru_free", api)
        self.assertEqual(api["ru_sharp"]["inputs"]["image"], ["7", 0])

    def test_final_sizes_are_parsed(self):
        self.assertEqual(ru.parse_final("2560x1440"), (2560, 1440))
        self.assertIsNone(ru.parse_final("big"))
        self.assertIsNone(ru.parse_final("20000x10"))


if __name__ == "__main__":
    unittest.main()
