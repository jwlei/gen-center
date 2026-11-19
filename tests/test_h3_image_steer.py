"""MiniMax H3 Image's harshness fix: two passes over its official sigmas, with Kijai's empty image steering."""
import copy
import unittest

from core import workflow_options as wo

INFO = {name: {} for name in wo.H3_STEER_NODES}
INFO["KSamplerSelect"] = {"input": {"required": {"sampler_name": [["euler", "euler_ancestral", "lcm"]]}}}
# As image_Minimax_H3_T2I samples: one KSampler on the conditioning's own latent, a zeroed negative.
T2I = {
    "9": {"class_type": "PreviewImage", "inputs": {"images": ["42", 0]}},
    "29": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_image_pruned_int8_convrot.safetensors"}},
    "30": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl.safetensors", "type": "minimax"}},
    "31": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_image_vae_fp16.safetensors"}},
    "32": {"class_type": "MiniMaxH3ImageConditioning", "inputs": {"prompt": ["43", 0], "width": 4096, "height": 4096,
                                                                 "clip": ["30", 0], "vae": ["31", 0]}},
    "33": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["32", 0]}},
    "38": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 6, "cfg": 1, "sampler_name": "euler", "scheduler": "simple",
                                                "denoise": 1, "model": ["29", 0], "positive": ["32", 0], "negative": ["33", 0],
                                                "latent_image": ["32", 1]}},
    "42": {"class_type": "VAEDecode", "inputs": {"samples": ["38", 0], "vae": ["31", 0]}},
    "43": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "a parrot"}},
}


def steer(api, chosen):
    """As convert() runs it: the sampler set before Sampler is offered, then the passes spliced in."""
    wo._h3_steer_sampler(api, INFO, chosen)
    return wo._h3_image_steer(api, INFO, chosen)


class H3ImageSteerTest(unittest.TestCase):
    def test_offered_off_and_changes_nothing_until_chosen(self):
        api = copy.deepcopy(T2I)
        options = wo._h3_image_steer(api, INFO, {})
        self.assertEqual(options[0]["id"], wo.H3_STEER)
        self.assertEqual(options[0]["default"], wo.OFF)
        self.assertEqual(api, T2I)

    def test_on_it_runs_the_recipe(self):
        api = copy.deepcopy(T2I)
        steer(api, {wo.H3_STEER: wo.ON})
        self.assertNotIn("38", api, "the KSampler is replaced")
        self.assertEqual(api["42"]["inputs"]["samples"], [wo.STEER_PASS_2, 0])
        one, two = api[wo.STEER_PASS_1]["inputs"], api[wo.STEER_PASS_2]["inputs"]
        self.assertEqual(one["latent_image"], ["32", 1])
        self.assertEqual(api["steer_sampler_1"]["inputs"]["sampler_name"], "euler_ancestral")
        self.assertEqual(api["steer_sigmas_1"]["inputs"]["sigmas"], "1, 0.9675236940383911, 0.8875485062599182")
        self.assertEqual(api["steer_sigmas_2"]["inputs"]["sigmas"], "0.8875485062599182, 0.75, 0.5327739119529724, 0.23200887441635132, 0")
        self.assertEqual(api["steer_guider"]["inputs"], {"model": ["29", 0], "conditioning": ["steer_combine", 0]})
        self.assertEqual((two["add_noise"], two["cfg"], two["latent_image"]), (False, 1.0, [wo.STEER_PASS_1, 0]))
        self.assertEqual((two["positive"], two["negative"]), (["steer_combine", 0], ["33", 0]))
        self.assertEqual(api["steer_sampler_2"]["inputs"], {"s_noise": 0.95, "s_noise_end": 0.95, "noise_clip_std": 0.0})
        self.assertEqual(api["steer_noise"]["inputs"]["noise_seed"], 42)

    def test_the_empty_image_copy_has_no_vae_and_the_black_picture(self):
        api = copy.deepcopy(T2I)
        steer(api, {wo.H3_STEER: wo.ON})
        copy_ = api[wo.STEER_COPY]["inputs"]
        self.assertNotIn("vae", copy_)
        self.assertEqual((copy_["prompt"], copy_["clip"], copy_["images.image_1"]), (["43", 0], ["30", 0], ["steer_black", 0]))
        self.assertEqual(api["steer_black"]["inputs"]["color"], 0)
        self.assertEqual((api["steer_range_empty"]["inputs"]["start"], api["steer_range_empty"]["inputs"]["end"]), (0.0, 0.1))
        self.assertEqual((api["steer_range_plain"]["inputs"]["start"], api["steer_range_plain"]["inputs"]["end"]), (0.1, 1.0))

    def test_the_copy_follows_the_size_set_at_render(self):
        api = copy.deepcopy(T2I)
        steer(api, {wo.H3_STEER: wo.ON})
        api["32"]["inputs"].update(width=2048, height=1536)
        wo.mirror_steering(api)
        self.assertEqual((api[wo.STEER_COPY]["inputs"]["width"], api[wo.STEER_COPY]["inputs"]["height"]), (2048, 1536))
        self.assertNotIn("vae", api[wo.STEER_COPY]["inputs"])

    def test_settings_split_noise_and_no_steering(self):
        api = copy.deepcopy(T2I)
        steer(api, {wo.H3_STEER: wo.ON, "h3_steer.split": "3", "h3_steer.s_noise": "0.9", "h3_steer.empty": wo.OFF})
        self.assertEqual(api["steer_sigmas_1"]["inputs"]["sigmas"].count(","), 3)
        self.assertEqual(api["steer_sigmas_2"]["inputs"]["sigmas"].count(","), 3)
        self.assertEqual(api["steer_sampler_2"]["inputs"]["s_noise"], 0.9)
        self.assertNotIn(wo.STEER_COPY, api)
        self.assertEqual(api["steer_guider"]["inputs"]["conditioning"], ["32", 0])

    def test_out_of_range_values_are_held(self):
        api = copy.deepcopy(T2I)
        steer(api, {wo.H3_STEER: wo.ON, "h3_steer.split": "9", "h3_steer.s_noise": "5"})
        self.assertEqual(api["steer_sigmas_2"]["inputs"]["sigmas"], "0.23200887441635132, 0")
        self.assertEqual(api["steer_sampler_2"]["inputs"]["s_noise"], 1.2)

    def test_the_run_is_labelled_by_its_passes(self):
        api = copy.deepcopy(T2I)
        steer(api, {wo.H3_STEER: wo.ON})
        self.assertEqual(wo.sampling_in(api), "euler_ancestral + lcm, 6 steps")

    def test_on_the_sampler_is_the_recipes_until_another_is_chosen(self):
        api = copy.deepcopy(T2I)
        wo._h3_steer_sampler(api, INFO, {wo.H3_STEER: wo.ON})
        self.assertEqual(api["38"]["inputs"]["sampler_name"], "euler_ancestral", "Sampler shows the recipe's")
        api["38"]["inputs"]["sampler_name"] = "euler"  # As Sampler then sets it, chosen
        wo._h3_image_steer(api, INFO, {wo.H3_STEER: wo.ON})
        self.assertEqual(api["steer_sampler_1"]["inputs"]["sampler_name"], "euler", "the sampler chosen runs pass 1")
        off = copy.deepcopy(T2I)
        wo._h3_steer_sampler(off, INFO, {})
        self.assertEqual(off, T2I, "off, the workflow's own sampler stays")

    def test_other_steps_or_scheduler_split_the_models_schedule(self):
        api = copy.deepcopy(T2I)
        api["38"]["inputs"].update(steps=8, scheduler="beta")
        steer(api, {wo.H3_STEER: wo.ON, "h3_steer.split": "3"})
        self.assertNotIn("steer_sigmas_1", api)
        self.assertEqual(api["steer_schedule"]["inputs"], {"model": ["29", 0], "scheduler": "beta", "steps": 8, "denoise": 1.0})
        self.assertEqual(api["steer_split"]["inputs"], {"sigmas": ["steer_schedule", 0], "step": 3})
        self.assertEqual((api[wo.STEER_PASS_1]["inputs"]["sigmas"], api[wo.STEER_PASS_2]["inputs"]["sigmas"]), (["steer_split", 0], ["steer_split", 1]))
        self.assertEqual(wo.sampling_in(api), "euler_ancestral + lcm, 8 steps")

    def test_cfg_above_one_guides_with_the_negative(self):
        api = copy.deepcopy(T2I)
        api["38"]["inputs"]["cfg"] = 3.5
        info = {**INFO, "CFGGuider": {}}
        wo._h3_steer_sampler(api, info, {wo.H3_STEER: wo.ON})
        wo._h3_image_steer(api, info, {wo.H3_STEER: wo.ON})
        guider = api["steer_guider"]
        self.assertEqual((guider["class_type"], guider["inputs"]["cfg"], guider["inputs"]["negative"]), ("CFGGuider", 3.5, ["33", 0]))
        self.assertEqual(api[wo.STEER_PASS_2]["inputs"]["cfg"], 3.5)

    def test_the_label_follows_the_passes_in_any_node_order(self):
        api = copy.deepcopy(T2I)
        steer(api, {wo.H3_STEER: wo.ON, "h3_steer.split": "3"})
        reordered = {key: api[key] for key in reversed(list(api))}
        self.assertEqual(wo.sampling_in(reordered), "euler_ancestral + lcm, 6 steps")

    def test_a_size_set_reaches_every_input_that_shared_its_source(self):
        from pipelines.image.comfy import ImageClient
        api = copy.deepcopy(T2I)
        api["32"]["inputs"].update(width=["14", 0], height=["14", 1])
        steer(api, {wo.H3_STEER: wo.ON})
        client = ImageClient.__new__(ImageClient)
        client.fields = {"width": ("32", "width"), "height": ("32", "height")}
        client._set_shared(api, "width", 2048)
        client._set_shared(api, "height", 1152)
        for node_id in ("32", wo.STEER_COPY):
            self.assertEqual((api[node_id]["inputs"]["width"], api[node_id]["inputs"]["height"]), (2048, 1152))

    def test_an_edit_steers_with_its_image_then_the_black_picture(self):
        api = copy.deepcopy(T2I)
        api["32"]["inputs"]["images.image_1"] = ["48", 0]
        steer(api, {wo.H3_STEER: wo.ON})
        copy_ = api[wo.STEER_COPY]["inputs"]
        self.assertNotIn("vae", copy_)
        self.assertEqual((copy_["images.image_1"], copy_["images.image_2"]), (["48", 0], ["steer_black", 0]))
        self.assertEqual(api["32"]["inputs"]["vae"], ["31", 0], "the picture's own keeps its VAE")

    def test_an_image_taken_out_at_render_leaves_the_copy_too(self):
        api = copy.deepcopy(T2I)
        api["32"]["inputs"].update({"images.image_1": ["45", 0], "images.image_2": ["46", 0]})
        steer(api, {wo.H3_STEER: wo.ON})
        self.assertEqual(api[wo.STEER_COPY]["inputs"]["images.image_3"], ["steer_black", 0])
        del api["32"]["inputs"]["images.image_2"]
        wo.mirror_steering(api)
        copy_ = api[wo.STEER_COPY]["inputs"]
        self.assertEqual((copy_["images.image_1"], copy_["images.image_2"]), (["45", 0], ["steer_black", 0]))
        self.assertNotIn("images.image_3", copy_)

    def test_not_offered_without_the_nodes_or_h3_image(self):
        self.assertEqual(wo._h3_image_steer(copy.deepcopy(T2I), {}, {}), [], "nodes not installed")
        other = copy.deepcopy(T2I)
        other["32"]["class_type"] = "CLIPTextEncode"
        self.assertEqual(wo._h3_image_steer(other, INFO, {}), [], "not H3 Image")


if __name__ == "__main__":
    unittest.main()
