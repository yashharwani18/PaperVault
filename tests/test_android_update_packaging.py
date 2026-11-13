"""Small APK validation and safe previous-release archival, without Android tools."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('apk_audit', ROOT / 'scripts/audit_android_apk.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AndroidUpdatePackagingTest(unittest.TestCase):
    def apk(self, weights=True, content=b'valid model'):
        fixture = io.BytesIO()
        recipe = {'tiny.gguf': {'bytes': 11, 'sha256': hashlib.sha256(b'valid model').hexdigest()}}
        with zipfile.ZipFile(fixture, 'w') as z:
            z.writestr('assets/offline-models.json', json.dumps(recipe))
            if weights:
                z.writestr('assets/tiny.gguf', content)
        fixture.seek(0)
        return zipfile.ZipFile(fixture)

    def test_full_accepts_verified_weights_and_rejects_damage(self):
        with self.apk() as z:
            self.assertIn('tiny.gguf', audit.verify_model_assets(z, 'full'))
        with self.apk(content=b'broken file') as z:
            with self.assertRaises(AssertionError):
                audit.verify_model_assets(z, 'full')

    def test_update_requires_metadata_but_rejects_any_weights(self):
        with self.apk(weights=False) as z:
            self.assertIn('tiny.gguf', audit.verify_model_assets(z, 'update'))
        with self.apk() as z:
            with self.assertRaises(AssertionError):
                audit.verify_model_assets(z, 'update')

    def frontend(self, root):
        (root / 'src').mkdir(parents=True, exist_ok=True)
        (root / 'src/main.ts').write_bytes(b'export const answer = 42;')
        (root / 'index.html').write_text('<html></html>', encoding='utf-8')
        dist = root / 'dist'
        (dist / 'assets').mkdir(parents=True, exist_ok=True)
        (dist / 'index.html').write_text('<script src="/assets/index-a.js"></script>', encoding='utf-8')
        (dist / 'assets/index-a.js').write_bytes(b'console.log(1)')
        receipt = {'format': 'khoj-ui-v1', 'source_sha256': audit.ui_source_digest(root)}
        (dist / 'khoj-ui.json').write_text(json.dumps(receipt), encoding='utf-8')
        return dist

    def ui_apk(self, dist, receipt=True, bundle=None, omit=()):
        fixture = io.BytesIO()
        with zipfile.ZipFile(fixture, 'w') as z:
            for path in dist.rglob('*'):
                if not path.is_file():
                    continue
                relative = path.relative_to(dist).as_posix()
                if relative in omit or (relative == 'khoj-ui.json' and not receipt):
                    continue
                data = path.read_bytes()
                if relative == 'assets/index-a.js' and bundle is not None:
                    data = bundle
                z.writestr('assets/' + relative, data)
        fixture.seek(0)
        return zipfile.ZipFile(fixture)

    def test_interface_must_match_dist_and_its_recorded_sources(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as d:
            frontend = Path(d) / 'frontend'
            dist = self.frontend(frontend)
            with self.ui_apk(dist) as z:
                self.assertEqual(audit.ui_source_digest(frontend), audit.verify_frontend(z, frontend))

    def test_interface_stale_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as d:
            frontend = Path(d) / 'frontend'
            dist = self.frontend(frontend)
            with self.ui_apk(dist, bundle=b'console.log(2)') as z:
                with self.assertRaises(AssertionError):
                    audit.verify_frontend(z, frontend)

    def test_interface_missing_bundle_or_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as d:
            frontend = Path(d) / 'frontend'
            dist = self.frontend(frontend)
            with self.ui_apk(dist, omit=('assets/index-a.js',)) as z:
                with self.assertRaises(AssertionError):
                    audit.verify_frontend(z, frontend)
            with self.ui_apk(dist, receipt=False) as z:
                with self.assertRaises(AssertionError):
                    audit.verify_frontend(z, frontend)

    def test_interface_source_edited_after_build_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as d:
            frontend = Path(d) / 'frontend'
            dist = self.frontend(frontend)
            (frontend / 'src/main.ts').write_bytes(b'export const answer = 43;')
            with self.ui_apk(dist) as z:
                with self.assertRaises(AssertionError):
                    audit.verify_frontend(z, frontend)

    def test_archive_preserves_verified_build5_once_and_refuses_mismatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as d:
            root = Path(d)
            (root / 'output').mkdir()
            (root / 'results').mkdir()
            artifact = root / 'output/Khoj-0.5.0-android.apk'
            artifact.write_bytes(b'previous verified release')
            report = {'version_code': 5, 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}
            (root / 'results/android-apk.json').write_text(json.dumps(report))
            audit.archive_previous_release(root)
            saved = root / 'output/previous-android-v0.5-build5/Khoj-0.5.0-android.apk'
            self.assertEqual(saved.read_bytes(), artifact.read_bytes())
            audit.archive_previous_release(root)
            artifact.write_bytes(b'unreviewed change')
            with self.assertRaises(AssertionError):
                audit.archive_previous_release(root)
            self.assertEqual(saved.read_bytes(), b'previous verified release')


if __name__ == '__main__':
    unittest.main()
