import time
import unittest
import xml.etree.cElementTree as Et
import os

from Plugwise_Smile import Smile


class TestSmileMethods(unittest.TestCase):

    def setUp(self):
        self.smile = Smile(
            os.environ.get('SMILE_USERNAME', 'smile'), 
            os.environ.get('SMILE_PASSWORD', 'short_id'),
            os.environ.get('SMILE_IP', 'ip_address'),
            os.environ.get('SMILE_PORT', 80)
            )
