import io
import os
import unittest
from unittest.mock import patch, PropertyMock

import osc.babysitter
import osc.conf
import osc.core
import osc.oscerr
from osc.obs_scm import Project

from .common import OscTestCase

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'init_project_fixtures')

try:
    import ruamel.yaml
except ImportError:
    class MockGitStore:
        def __init__(self, *args, **kwargs):
            raise osc.oscerr.NoWorkingCopy("not a git working copy")
    osc.git_scm.GitStore = MockGitStore
    import sys
    sys.modules['osc.git_scm'].GitStore = MockGitStore


class TestCheckout(OscTestCase):
    def _get_fixtures_dir(self):
        return FIXTURES_DIR

    def setUp(self):
        super().setUp(copytree=False)

    def test_project_apiurl_mismatch_checkout_package(self):
        """checkout_package raises ProjectApiurlMismatch when existing project has a different apiurl"""
        prj_dir = os.path.join(self.tmpdir, 'testprj')
        Project.init_project('http://example.com', prj_dir, 'testprj', getPackageList=False)

        with self.assertRaises(osc.oscerr.ProjectApiurlMismatch) as ctx:
            osc.core.checkout_package('http://localhost', 'testprj', 'testpkg', prj_dir=prj_dir)

        e = ctx.exception
        self.assertIsInstance(e, osc.oscerr.ProjectError)
        self.assertIsInstance(e, osc.oscerr.OscBaseError)
        self.assertEqual(e.prj, 'testprj')
        self.assertEqual(e.prj_apiurl, 'http://example.com')
        self.assertEqual(e.apiurl, 'http://localhost')
        self.assertIn("project on disk has a different apiurl: http://example.com (expected http://localhost)", str(e))

        # Ensure package directory was not created on disk
        self.assertFalse(os.path.exists(os.path.join(prj_dir, 'testpkg')))

    def test_project_apiurl_matching_checkout_package(self):
        """checkout_package succeeds when existing project has matching apiurl"""
        prj_dir = os.path.join(self.tmpdir, 'testprj')
        Project.init_project('http://localhost', prj_dir, 'testprj', getPackageList=False)

        with patch('osc.core.show_package_meta', return_value=[b'<package name="testpkg" project="testprj" />']), \
             patch('osc.core.meta_get_packagelist', return_value=['testpkg']), \
             patch('osc.obs_scm.package.Package.update', return_value=None), \
             patch('osc.obs_scm.project.Project.read_packages') as mock_read_packages, \
             patch('osc.obs_scm.project.Project.write_packages'):
            import xml.etree.ElementTree as ET
            mock_read_packages.return_value = ET.ElementTree(ET.fromstring('<project name="testprj" />'))
            osc.core.checkout_package('http://localhost', 'testprj', 'testpkg', prj_dir=prj_dir)

        # Package directory should have been created
        self.assertTrue(os.path.exists(os.path.join(prj_dir, 'testpkg')))

    def test_project_apiurl_alias_matching_checkout_package(self):
        """checkout_package succeeds when existing project has an aliased apiurl"""
        prj_dir = os.path.join(self.tmpdir, 'testprj')
        Project.init_project('https://api.opensuse.org', prj_dir, 'testprj', getPackageList=False)

        aliases = {'obs': 'https://api.opensuse.org', 'https://api.opensuse.org': 'https://api.opensuse.org'}
        with patch.object(type(osc.conf.config), 'apiurl_aliases', new_callable=PropertyMock, return_value=aliases):
            with patch('osc.core.show_package_meta', return_value=[b'<package name="testpkg" project="testprj" />']), \
                 patch('osc.core.meta_get_packagelist', return_value=['testpkg']), \
                 patch('osc.obs_scm.package.Package.update', return_value=None), \
                 patch('osc.obs_scm.project.Project.read_packages') as mock_read_packages, \
                 patch('osc.obs_scm.project.Project.write_packages'):
                import xml.etree.ElementTree as ET
                mock_read_packages.return_value = ET.ElementTree(ET.fromstring('<project name="testprj" />'))
                osc.core.checkout_package('obs', 'testprj', 'testpkg', prj_dir=prj_dir)

        self.assertTrue(os.path.exists(os.path.join(prj_dir, 'testpkg')))

    def test_project_init_apiurl_matching(self):
        """Project.__init__ succeeds when apiurl parameter matches store.apiurl"""
        prj_dir = os.path.join(self.tmpdir, 'testprj')
        Project.init_project('http://example.com', prj_dir, 'testprj', getPackageList=False)

        prj = Project(prj_dir, getPackageList=False, apiurl='http://example.com')
        self.assertEqual(prj.apiurl, 'http://example.com')

    def test_project_init_apiurl_mismatch(self):
        """Project.__init__ raises ProjectApiurlMismatch when apiurl parameter does not match store.apiurl"""
        prj_dir = os.path.join(self.tmpdir, 'testprj')
        Project.init_project('http://example.com', prj_dir, 'testprj', getPackageList=False)

        with self.assertRaises(osc.oscerr.ProjectApiurlMismatch) as ctx:
            Project(prj_dir, getPackageList=False, apiurl='http://localhost')

        e = ctx.exception
        self.assertEqual(e.prj_apiurl, 'http://example.com')
        self.assertEqual(e.apiurl, 'http://localhost')

    def test_checkout_package_with_outdir_skips_project_apiurl_check(self):
        """checkout_package does not check prj_dir apiurl when outdir is specified"""
        prj_dir = os.path.join(self.tmpdir, 'testprj')
        Project.init_project('http://example.com', prj_dir, 'testprj', getPackageList=False)
        out_dir = os.path.join(self.tmpdir, 'custom_outdir')

        with patch('osc.core.show_package_meta', return_value=[b'<package name="testpkg" project="testprj" />']), \
             patch('osc.obs_scm.package.Package.update', return_value=None):
            osc.core.checkout_package('http://localhost', 'testprj', 'testpkg', prj_dir=prj_dir, outdir=out_dir)

        self.assertTrue(os.path.exists(out_dir))

    def test_resolve_apiurl_alias(self):
        """conf.resolve_apiurl_alias properly resolves aliases and sanitizes URLs"""
        aliases = {'obs': 'https://api.opensuse.org', 'https://api.opensuse.org': 'https://api.opensuse.org'}
        with patch.object(type(osc.conf.config), 'apiurl_aliases', new_callable=PropertyMock, return_value=aliases):
            self.assertEqual(osc.conf.resolve_apiurl_alias('obs'), 'https://api.opensuse.org')
            self.assertEqual(osc.conf.resolve_apiurl_alias('https://api.opensuse.org/'), 'https://api.opensuse.org')
            self.assertEqual(osc.conf.resolve_apiurl_alias('http://example.com/'), 'http://example.com')
            self.assertEqual(osc.conf.resolve_apiurl_alias(None), None)
            self.assertEqual(osc.conf.resolve_apiurl_alias(''), '')

    def test_make_dir_apiurl_mismatch(self):
        """make_dir raises ProjectApiurlMismatch when existing project directory has a different apiurl"""
        prj_dir = os.path.join(self.tmpdir, 'testprj')
        Project.init_project('http://example.com', prj_dir, 'testprj', getPackageList=False)

        with self.assertRaises(osc.oscerr.ProjectApiurlMismatch):
            osc.core.make_dir('http://localhost', 'testprj', 'testpkg', prj_dir=prj_dir)

        # Package directory should not be created
        self.assertFalse(os.path.exists(os.path.join(prj_dir, 'testpkg')))

    def test_babysitter_handles_project_apiurl_mismatch(self):
        """babysitter.run catches ProjectApiurlMismatch and prints to stderr"""
        err = osc.oscerr.ProjectApiurlMismatch('testprj', 'http://example.com', 'http://localhost')

        class MockPrg:
            def main(self, argv):
                raise err

        stderr_capture = io.StringIO()
        with patch('sys.stderr', stderr_capture):
            exit_code = osc.babysitter.run(MockPrg(), argv=['osc', 'co', 'testprj/testpkg'])

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "ProjectApiurlMismatch: testprj: project on disk has a different apiurl: http://example.com (expected http://localhost)",
            stderr_capture.getvalue(),
        )


if __name__ == '__main__':
    unittest.main()
