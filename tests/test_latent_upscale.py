"""MiniMax H3's latent upscaler and FastVideo, as workflow options spliced into an H3 graph."""
import copy
import unittest

from core import workflow_options as wo

INFO = {
    wo.H3_UPSCALER: {"input": {"required": {"model_name": [["ltx-2.3-spatial-upscaler-x2-1.0.safetensors", "minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors",
                                                             "minimax_h3_latent_upscaler_3d_conv_v1_bf16.safetensors"]]}}},
    "LTXVSeparateAVLatent": {}, "LTXVConcatAVLatent": {}, "ManualSigmas": {},
    "UNETLoader": {"input": {"required": {"unet_name": [["minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                                                          "minimax_h3_fastvideo_vsa_datafree_1300step_4step_int8_convrot.safetensors"]]}}},
}
# As the R2V workflows sample and decode: one SamplerCustomAdvanced, its latent to both decoders.
R2V = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors"}},
    "2": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"width": 640}},
    "3": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["2", 0]}},
    "4": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
    "5": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
    "6": {"class_type": "BasicScheduler", "inputs": {"steps": 20, "model": ["1", 0]}},
    "7": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["4", 0], "guider": ["3", 0], "sampler": ["5", 0],
                                                            "sigmas": ["6", 0], "latent_image": ["2", 1]}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0]}},
    "9": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["7", 0]}},
}


class LatentUpscaleTest(unittest.TestCase):
    def test_offered_off_and_changes_nothing_until_chosen(self):
        api = copy.deepcopy(R2V)
        options = wo._h3_latent_upscale(api, INFO, {})
        self.assertEqual([o["id"] for o in options][:2], ["latent_upscale", "latent_upscale_mp"])
        self.assertEqual(options[0]["default"], "Off")
        self.assertEqual(options[0]["choices"], ["Off", "Clean", "Hires fix", "Heavy", "Custom"])
        self.assertEqual(api, R2V)

    def test_a_preset_upscales_the_video_latent_and_refines_it(self):
        api = copy.deepcopy(R2V)
        wo._h3_latent_upscale(api, INFO, {"latent_upscale": "Hires fix", "latent_upscale_mp": "1.5"})
        self.assertEqual(api["lu_split"]["inputs"]["av_latent"], ["7", 0])
        upscale = api["lu_upscale"]["inputs"]
        self.assertEqual(upscale["model_name"], "minimax_h3_latent_upscaler_3d_conv_v1_bf16.safetensors", "BF16 for a 12 GB card")
        self.assertEqual((upscale["mode"], upscale["mode.megapixels"], upscale["precision"]), ("megapixels", 1.5, "bf16"))
        self.assertEqual(api["lu_join"]["inputs"], {"video_latent": ["lu_upscale", 0], "audio_latent": ["lu_split", 1]})
        self.assertEqual(api["lu_sigmas"]["inputs"]["sigmas"], wo.LATENT_UPSCALES["Hires fix"])
        refine = api["lu_refine"]["inputs"]
        self.assertEqual((refine["guider"], refine["noise"], refine["latent_image"]), (["3", 0], ["4", 0], ["lu_join", 0]))
        self.assertEqual(api["8"]["inputs"]["samples"], ["lu_refine", 0])
        self.assertEqual(api["9"]["inputs"]["samples"], ["lu_refine", 0], "the sound goes through the refine too")

    def test_custom_sets_its_own_denoise_steps_sampler_and_chunking(self):
        api = copy.deepcopy(R2V)
        info = {**INFO, "KSamplerSelect": {"input": {"required": {"sampler_name": [["euler", "res_multistep"]]}}}}
        wo._h3_latent_upscale(api, info, {"latent_upscale": "Custom", "latent_upscale_denoise": "0.5", "latent_upscale_steps": "2",
                                          "latent_upscale_sampler": "euler", "latent_upscale_chunking": "0"})
        self.assertEqual(api["lu_sigmas"]["inputs"]["sigmas"], "0.5000, 0.2500, 0.0000")
        self.assertEqual(api["lu_sampler"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(api["lu_refine"]["inputs"]["sampler"], ["lu_sampler", 0])
        self.assertFalse(api["lu_upscale"]["inputs"]["enable_temporal_chunking"])

    def test_megapixels_are_held_to_their_range(self):
        api = copy.deepcopy(R2V)
        wo._h3_latent_upscale(api, INFO, {"latent_upscale": "Clean", "latent_upscale_mp": "40"})
        self.assertEqual(api["lu_upscale"]["inputs"]["mode.megapixels"], wo.UPSCALE_MEGAPIXELS[1])

    def test_not_offered_without_the_node_or_a_decoded_h3_latent(self):
        self.assertEqual(wo._h3_latent_upscale(copy.deepcopy(R2V), {}, {}), [], "node not installed")
        director = {"1": {"class_type": "MiniMaxH3MotionDirector", "inputs": {}}, "2": {"class_type": "VAEDecode", "inputs": {"samples": ["1", 0]}}}
        self.assertEqual(wo._h3_latent_upscale(director, INFO, {}), [], "Motion Director samples inside its own node")
        other = {key: value for key, value in copy.deepcopy(R2V).items() if key != "2"}
        self.assertEqual(wo._h3_latent_upscale(other, INFO, {}), [], "not an H3 workflow")


class FastVideoTest(unittest.TestCase):
    def graph(self):
        api = copy.deepcopy(R2V)
        api["1"]["inputs"]["unet_name"] = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
        api["10"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
                                                                     "model": ["1", 0]}}
        api["3"]["inputs"]["model"] = ["10", 0]
        return api

    def test_fastvideo_stands_in_at_four_steps_without_a_turbo_lora(self):
        api = self.graph()
        options = wo._h3_fastvideo(api, INFO, {"h3_model": "FastVideo 4-step"})
        self.assertEqual(options[0]["id"], "h3_model")
        self.assertIn("fastvideo", api["1"]["inputs"]["unet_name"])
        self.assertEqual(api["3"]["inputs"]["model"], ["1", 0], "the turbo LoRA comes out")
        self.assertEqual(api["6"]["inputs"]["steps"], 4)

    def test_steps_chosen_are_kept(self):
        api = self.graph()
        wo._h3_fastvideo(api, INFO, {"h3_model": "FastVideo 4-step", "steps": "6"})
        self.assertEqual(api["6"]["inputs"]["steps"], 20, "convert() sets the chosen steps itself")

    def test_only_for_the_first_last_frame_model(self):
        self.assertEqual(wo._h3_fastvideo(copy.deepcopy(R2V), INFO, {}), [], "a reference-to-video workflow keeps its model")
        api = self.graph()
        self.assertEqual(wo._h3_fastvideo(api, INFO, {})[0]["default"], "Standard")
        self.assertNotIn("fastvideo", api["1"]["inputs"]["unet_name"])


if __name__ == "__main__":
    unittest.main()
