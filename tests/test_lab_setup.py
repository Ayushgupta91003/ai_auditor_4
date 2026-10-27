import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.setup_lab import create_env

class LabSetupTests(unittest.TestCase):
    def test_private_config_is_generated_once_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath('.env.example').write_text('POSTGRES_PASSWORD=replace-with-a-local-password\nDATABASE_URL=postgresql://auditor:replace-with-a-local-password@postgres/invoices\nSERVICE_TOKEN=replace-with-a-random-local-service-token\nAWS_REGION=us-east-1\n')
            with patch.dict(os.environ, {'AWS_REGION': 'ap-south-1'}):
                self.assertTrue(create_env(root))
            original = root.joinpath('.env').read_text()
            self.assertNotIn('replace-with-', original)
            self.assertIn('AWS_REGION=ap-south-1', original)
            password = original.splitlines()[0].split('=', 1)[1]
            self.assertIn(':' + password + '@postgres', original)
            self.assertFalse(create_env(root))
            self.assertEqual(root.joinpath('.env').read_text(), original)
