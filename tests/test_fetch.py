import io
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import urllib3.exceptions

import osc.conf
from osc.fetch import Fetcher


class DummyPac:
    def __init__(self, project, repository, name, filename="test.rpm"):
        self.project = project
        self.repository = repository
        self.name = name
        self.binary = name
        self.filename = filename
        self.repofilename = filename
        self.canonname = filename
        self.repoarch = "x86_64"
        self.repopackage = name
        self.pacsuffix = "rpm"
        self.hdrmd5 = None
        self.fullfilename = f"/tmp/nonexistent_{name}"
        self.localdir = f"{project}/{repository}/x86_64"
        self.urllist = []
        self.mp = {
            "project": project,
            "repository": repository,
            "arch": "x86_64",
            "filename": filename,
        }

    def makeurls(self, cachedir, urllist):
        self.localdir = f"{cachedir}/{self.project}/{self.repository}/{self.repoarch}"
        self.fullfilename = os.path.join(self.localdir, self.canonname)
        self.urllist = [url % self.mp for url in urllist]


class DummyBuildinfo:
    def __init__(self, apiurl, deps, urls=None):
        self.apiurl = apiurl
        self.deps = deps
        self.urls = urls or {}
        self.projects = {}
        for dep in deps:
            self.projects[dep.project] = True


class TestFetch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="osc_test_fetch")
        osc.conf.config = osc.conf.Options()
        osc.conf.config["http_debug"] = False
        osc.conf.config["api_host_options"] = {}

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("osc.fetch.http_request")
    def test_check_mirror_reachable_success(self, mock_http):
        mock_resp = MagicMock()
        mock_http.return_value = mock_resp

        fetcher = Fetcher(cachedir=self.tmpdir)
        url = "http://download.opensuse.org/repositories/foo/standard/x86_64/test.rpm"
        self.assertTrue(fetcher.check_mirror_reachable(url))
        self.assertTrue(fetcher._mirror_reachability["download.opensuse.org"])
        mock_resp.close.assert_called_once()

    @patch("osc.fetch.http_request")
    def test_check_mirror_reachable_http_error(self, mock_http):
        # HTTP 404 or 405 from server means server is reachable
        mock_http.side_effect = HTTPError("http://example.com/test.rpm", 404, "Not Found", {}, io.BytesIO())

        fetcher = Fetcher(cachedir=self.tmpdir)
        url = "http://download.opensuse.org/repositories/foo/standard/x86_64/test.rpm"
        self.assertTrue(fetcher.check_mirror_reachable(url))
        self.assertTrue(fetcher._mirror_reachability["download.opensuse.org"])

    @patch("osc.fetch.http_request")
    def test_check_mirror_reachable_connection_error(self, mock_http):
        # URLError (connection refused, network unreachable, etc.) means server is unreachable
        mock_http.side_effect = URLError("Connection refused")

        fetcher = Fetcher(cachedir=self.tmpdir)
        url = "http://download.suse.de/ibs/SUSE:/SLE-15/standard/x86_64/test.rpm"
        self.assertFalse(fetcher.check_mirror_reachable(url))
        self.assertFalse(fetcher._mirror_reachability["download.suse.de"])

    @patch("osc.fetch.http_request")
    def test_check_mirror_reachable_timeout_error(self, mock_http):
        # ConnectTimeoutError means server is unreachable
        mock_http.side_effect = urllib3.exceptions.ConnectTimeoutError()

        fetcher = Fetcher(cachedir=self.tmpdir)
        url = "http://download.suse.de/ibs/SUSE:/SLE-15/standard/x86_64/test.rpm"
        self.assertFalse(fetcher.check_mirror_reachable(url))
        self.assertFalse(fetcher._mirror_reachability["download.suse.de"])

    @patch("osc.obs_api.Keyinfo")
    @patch("osc.fetch.http_request")
    def test_auto_detect_download_api_only_when_mirror_unreachable(self, mock_http, mock_keyinfo):
        # Simulate download.suse.de hanging / timing out
        mock_http.side_effect = urllib3.exceptions.ConnectTimeoutError()
        mock_keyinfo.from_api.return_value = MagicMock(pubkey_list=[])

        pac1 = DummyPac("SUSE:SLE-15", "standard", "pkg1")
        pac2 = DummyPac("SUSE:SLE-15", "standard", "pkg2")
        bi = DummyBuildinfo(
            "https://api.suse.de",
            [pac1, pac2],
            urls={"SUSE:SLE-15/standard": "http://download.suse.de/ibs/SUSE:/SLE-15/standard/%(arch)s/%(filename)s"},
        )

        fetcher = Fetcher(cachedir=self.tmpdir, download_api_only=False, enable_cpio=True)

        with patch.object(fetcher, "_Fetcher__fetch_cpio") as mock_fetch_cpio:
            fetcher.run(bi)
            mock_fetch_cpio.assert_called_once_with("https://api.suse.de")

        # download_api_only must be automatically enabled!
        self.assertTrue(fetcher.download_api_only)
        # Packages must have been queued in cpio for api download
        self.assertIn("SUSE:SLE-15/standard/x86_64/pkg1", fetcher.cpio)
        self.assertIn("SUSE:SLE-15/standard/x86_64/pkg2", fetcher.cpio)

    @patch("osc.obs_api.Keyinfo")
    @patch("osc.fetch.http_request")
    def test_mirror_reachable_keeps_download_api_only_false(self, mock_http, mock_keyinfo):
        mock_http.return_value = MagicMock()
        mock_keyinfo.from_api.return_value = MagicMock(pubkey_list=[])

        pac = DummyPac("openSUSE:Factory", "standard", "pkg1")
        bi = DummyBuildinfo(
            "https://api.opensuse.org",
            [pac],
            urls={"openSUSE:Factory/standard": "http://download.opensuse.org/repositories/openSUSE:/Factory/standard/%(arch)s/%(filename)s"},
        )

        fetcher = Fetcher(cachedir=self.tmpdir, download_api_only=False, enable_cpio=True)

        with patch.object(fetcher, "fetch") as mock_fetch, \
             patch.object(fetcher, "_Fetcher__fetch_cpio"):
            fetcher.run(bi)
            mock_fetch.assert_called_once()

        self.assertFalse(fetcher.download_api_only)

    def test_build_urllist_download_api_only_without_cpio(self):
        pac = DummyPac("SUSE:SLE-15", "standard", "pkg1")
        bi = DummyBuildinfo(
            "https://api.suse.de",
            [pac],
            urls={"SUSE:SLE-15/standard": "http://download.suse.de/ibs/SUSE:/SLE-15/standard/%(arch)s/%(filename)s"},
        )

        fetcher = Fetcher(cachedir=self.tmpdir, download_api_only=True, enable_cpio=False)
        urllist = fetcher._build_urllist(bi, pac)
        self.assertEqual(
            urllist,
            ["https://api.suse.de/build/SUSE:SLE-15/standard/x86_64/pkg1/test.rpm"],
        )

    def test_fetch_runtime_connection_failure_enables_download_api_only(self):
        pac = DummyPac("SUSE:SLE-15", "standard", "pkg1")
        pac.urllist = ["http://download.suse.de/ibs/SUSE:/SLE-15/standard/x86_64/test.rpm"]

        fetcher = Fetcher(cachedir=self.tmpdir, download_api_only=False, enable_cpio=True)

        with patch("osc.fetch.OscMirrorGroup") as mock_mg_class:
            mock_mg = MagicMock()
            mock_mg.urlgrab.return_value = False
            mock_mg.failed_mirrors = {
                "http://download.suse.de/ibs/SUSE:/SLE-15/standard/x86_64/test.rpm": URLError("Connection refused")
            }
            mock_mg_class.return_value = mock_mg

            fetcher.fetch(pac)

        self.assertTrue(fetcher.download_api_only)
        self.assertIn("SUSE:SLE-15/standard/x86_64/pkg1", fetcher.cpio)

    @patch("osc.obs_api.Keyinfo")
    @patch("osc.fetch.http_request")
    def test_run_when_already_cached_no_reachability_check(self, mock_http, mock_keyinfo):
        mock_keyinfo.from_api.return_value = MagicMock(pubkey_list=[])
        pac = DummyPac("openSUSE:Factory", "standard", "pkg1")
        # Create the file in cache so it is treated as cached
        pac.localdir = f"{self.tmpdir}/openSUSE:Factory/standard/x86_64"
        pac.fullfilename = os.path.join(pac.localdir, pac.canonname)
        os.makedirs(pac.localdir, exist_ok=True)
        with open(pac.fullfilename, "w") as f:
            f.write("cached content")

        bi = DummyBuildinfo(
            "https://api.opensuse.org",
            [pac],
            urls={"openSUSE:Factory/standard": "http://download.opensuse.org/repositories/openSUSE:/Factory/standard/%(arch)s/%(filename)s"},
        )

        fetcher = Fetcher(cachedir=self.tmpdir, download_api_only=False, enable_cpio=True)
        fetcher.run(bi)

        # Since needed is 0, check_mirror_reachable should not have been called
        mock_http.assert_not_called()
        self.assertFalse(fetcher.download_api_only)

    @patch("osc.obs_api.Keyinfo")
    @patch("osc.fetch.http_request")
    def test_run_when_download_api_only_set_no_reachability_check(self, mock_http, mock_keyinfo):
        mock_keyinfo.from_api.return_value = MagicMock(pubkey_list=[])
        pac = DummyPac("openSUSE:Factory", "standard", "pkg1")
        bi = DummyBuildinfo(
            "https://api.opensuse.org",
            [pac],
            urls={"openSUSE:Factory/standard": "http://download.opensuse.org/repositories/openSUSE:/Factory/standard/%(arch)s/%(filename)s"},
        )

        fetcher = Fetcher(cachedir=self.tmpdir, download_api_only=True, enable_cpio=True)
        with patch.object(fetcher, "_Fetcher__fetch_cpio"):
            fetcher.run(bi)

        mock_http.assert_not_called()
        self.assertTrue(fetcher.download_api_only)

    @patch("osc.obs_api.Keyinfo")
    @patch("osc.fetch.http_request")
    def test_multiple_mirrors_partial_unreachable(self, mock_http, mock_keyinfo):
        mock_keyinfo.from_api.return_value = MagicMock(pubkey_list=[])

        def mock_http_side_effect(method, url, **kwargs):
            if "download.suse.de" in url:
                raise urllib3.exceptions.ConnectTimeoutError()
            return MagicMock()

        mock_http.side_effect = mock_http_side_effect

        pac1 = DummyPac("SUSE:SLE-15", "standard", "pkg1")
        pac2 = DummyPac("openSUSE:Factory", "standard", "pkg2")
        bi = DummyBuildinfo(
            "https://api.suse.de",
            [pac1, pac2],
            urls={
                "SUSE:SLE-15/standard": "http://download.suse.de/ibs/SUSE:/SLE-15/standard/%(arch)s/%(filename)s",
                "openSUSE:Factory/standard": "http://download.opensuse.org/repositories/openSUSE:/Factory/standard/%(arch)s/%(filename)s",
            },
        )

        fetcher = Fetcher(cachedir=self.tmpdir, download_api_only=False, enable_cpio=True)

        with patch.object(fetcher, "fetch") as mock_fetch, \
             patch.object(fetcher, "_Fetcher__fetch_cpio"):
            fetcher.run(bi)
            # Both packages are fetched
            self.assertEqual(mock_fetch.call_count, 2)

        # Global download_api_only is False because openSUSE mirror was reachable
        self.assertFalse(fetcher.download_api_only)
        # But pac1's urllist was cleared because download.suse.de was unreachable
        self.assertEqual(pac1.urllist, [])
        # And pac2's urllist still has the reachable mirror
        self.assertEqual(
            pac2.urllist,
            ["http://download.opensuse.org/repositories/openSUSE:/Factory/standard/x86_64/test.rpm"],
        )


if __name__ == "__main__":
    unittest.main()
