import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('blackhole_device',ROOT/'applications/blackhole/device.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class BlackHoleTests(unittest.TestCase):
    def test_requires_actual_unique_two_channel_device(self):
        device={'_name':'BlackHole 2ch','coreaudio_device_input':2,'coreaudio_device_output':'2'}
        self.assertEqual(module.validate_device_tree({'SPAudioDataType':[{'_items':[device]}]}),device)
        for tree in ({},[device,device],[{**device,'coreaudio_device_input':0}],[{**device,'coreaudio_device_output':None}]):
            with self.assertRaises(ValueError):module.validate_device_tree(tree)

if __name__=='__main__':unittest.main()
