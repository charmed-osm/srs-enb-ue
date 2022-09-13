# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import call, mock_open, patch

from ops import testing

from charm import SrsLteCharm

testing.SIMULATE_CAN_CONNECT = True


class MockOpen:
    def __init__(self, read_data: str = ""):
        """Init."""
        self.read_data = read_data
        self.writen_data = None

    def __enter__(self):
        """Enter."""
        return self

    def read(self):
        """Read."""
        return self.read_data

    def write(self, data: str):
        """Write."""
        self.writen_data = data

    def __exit__(self, *args):
        """Exit."""
        pass


class TestCharm(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = testing.Harness(SrsLteCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.mkdir")
    @patch("shutil.copy")
    @patch("shutil.rmtree")
    @patch("subprocess.run")
    def test_given_list_of_packages_to_install_when_install_then_apt_cache_is_updated(
        self, patch_subprocess_run, _, __, ___, ____
    ):

        self.harness.charm.on.install.emit()

        patch_subprocess_run.assert_any_call(
            ["apt", "-qq", "update"], shell=True, stdout=-1, encoding="utf-8"
        )

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.mkdir")
    @patch("shutil.copy")
    @patch("shutil.rmtree")
    @patch("subprocess.run")
    def test_given_list_of_packages_to_install_when_install_then_apt_packages_are_installed(
        self, patch_subprocess_run, _, __, ___, ____
    ):
        self.harness.charm.on.install.emit()

        patch_subprocess_run.assert_any_call(
            ["apt", "install", "git"], shell=True, stdout=-1, encoding="utf-8"
        )
        patch_subprocess_run.assert_any_call(
            ["apt", "install", "libzmq3-dev"], shell=True, stdout=-1, encoding="utf-8"
        )
        patch_subprocess_run.assert_any_call(
            ["apt", "install", "cmake"], shell=True, stdout=-1, encoding="utf-8"
        )
        patch_subprocess_run.assert_any_call(
            ["apt", "install", "build-essential"], shell=True, stdout=-1, encoding="utf-8"
        )
        patch_subprocess_run.assert_any_call(
            ["apt", "install", "libmbedtls-dev"], shell=True, stdout=-1, encoding="utf-8"
        )
        patch_subprocess_run.assert_any_call(
            ["apt", "install", "libboost-program-options-dev"],
            shell=True,
            stdout=-1,
            encoding="utf-8",
        )
        patch_subprocess_run.assert_any_call(
            ["apt", "install", "libsctp-dev"], shell=True, stdout=-1, encoding="utf-8"
        )
        patch_subprocess_run.assert_any_call(
            ["apt", "install", "libconfig++-dev"], shell=True, stdout=-1, encoding="utf-8"
        )
        patch_subprocess_run.assert_any_call(
            ["apt", "install", "libfftw3-dev"], shell=True, stdout=-1, encoding="utf-8"
        )
        patch_subprocess_run.assert_any_call(
            ["apt", "install", "net-tools"], shell=True, stdout=-1, encoding="utf-8"
        )

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.mkdir")
    @patch("shutil.copy")
    @patch("shutil.rmtree")
    @patch("subprocess.run")
    def test_given_install_event_when_install_then_srs_directories_are_removed_and_recreated(
        self, _, patch_rmtree, __, patch_mkdir, ___
    ):
        self.harness.charm.on.install.emit()

        rmtree_calls = [
            call("/srsLTE", ignore_errors=True),
            call("/build", ignore_errors=True),
            call("/config", ignore_errors=True),
            call("/service", ignore_errors=True),
        ]
        mkdir_calls = [call("/srsLTE"), call("/build"), call("/config"), call("/service")]
        patch_rmtree.assert_has_calls(calls=rmtree_calls)
        patch_mkdir.assert_has_calls(calls=mkdir_calls)

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.mkdir")
    @patch("shutil.copy")
    @patch("shutil.rmtree")
    @patch("subprocess.run")
    def test_given_install_event_when_install_then_srsran_repo_is_cloned(
        self, patch_subprocess_run, _, __, ___, ____
    ):
        self.harness.charm.on.install.emit()

        patch_subprocess_run.assert_any_call(
            [
                "git",
                "clone",
                "--branch=release_20_10",
                "--depth=1",
                "https://github.com/srsLTE/srsLTE.git",
                "/srsLTE",
            ],
            shell=True,
            stdout=-1,
            encoding="utf-8",
        )

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.mkdir")
    @patch("shutil.copy")
    @patch("shutil.rmtree")
    @patch("subprocess.run")
    def test_given_install_event_when_install_then_srsran_is_built(
        self, patch_subprocess_run, _, __, ___, ____
    ):
        self.harness.charm.on.install.emit()

        patch_subprocess_run.assert_any_call(
            "cd /build && cmake /srsLTE && make -j `nproc` srsenb srsue",
            shell=True,
            stdout=-1,
            encoding="utf-8",
        )

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.mkdir")
    @patch("shutil.copy")
    @patch("shutil.rmtree")
    @patch("subprocess.run")
    def test_given_install_event_when_install_then_files_are_copied(
        self, _, __, patch_copy, ___, ____
    ):
        self.harness.charm.on.install.emit()

        calls = [
            call("/srsLTE/srsenb/enb.conf.example", "/config/enb.conf"),
            call("/srsLTE/srsenb/drb.conf.example", "/config/drb.conf"),
            call("/srsLTE/srsenb/rr.conf.example", "/config/rr.conf"),
            call("/srsLTE/srsenb/sib.conf.example", "/config/sib.conf"),
            call("/srsLTE/srsenb/sib.conf.mbsfn.example", "/config/sib.mbsfn.conf"),
            call("/srsLTE/srsue/ue.conf.example", "/config/ue.conf"),
        ]
        patch_copy.assert_has_calls(calls=calls)

    @patch("os.mkdir")
    @patch("shutil.copy")
    @patch("shutil.rmtree")
    @patch("subprocess.run")
    def test_given_service_template_when_install_then_srsenb_service_file_is_rendered(
        self,
        _,
        __,
        ___,
        ____,
    ):

        with open("templates/srsenb.service", "r") as f:
            srsenb_service_content = f.read()
        with open("templates/srsue.service", "r") as f:
            srsue_service_content = f.read()

        with patch("builtins.open") as mock_open:
            mock_open_read_srsenb_template = MockOpen(read_data=srsenb_service_content)
            mock_open_write_srsenb_service = MockOpen()
            mock_open_read_srsue_template = MockOpen(read_data=srsue_service_content)
            mock_open_write_srsue_service = MockOpen()
            mock_open.side_effect = [
                mock_open_read_srsenb_template,
                mock_open_write_srsenb_service,
                mock_open_read_srsue_template,
                mock_open_write_srsue_service,
            ]
            self.harness.charm.on.install.emit()

        srsenb_expected_service = (
            "[Unit]\n"
            "Description=Srs EnodeB Service\n"
            "After=network.target\n"
            "StartLimitIntervalSec=0\n"
            "[Service]\n"
            "Type=simple\n"
            "Restart=always\n"
            "RestartSec=1\n"
            "User=root\n"
            "ExecStart=/build/srsenb/src/srsenb --enb.name=dummyENB01 --enb.mcc=901 --enb.mnc=70 --enb_files.rr_config=/config/rr.conf --enb_files.sib_config=/config/sib.conf --enb_files.drb_config=/config/drb.conf /config/enb.conf --rf.device_name=zmq --rf.device_args=fail_on_disconnect=true,tx_port=tcp://*:2000,rx_port=tcp://localhost:2001,id=enb,base_srate=23.04e6\n\n"  # noqa: E501, W505
            "[Install]\n"
            "WantedBy=multi-user.target"
        )
        srsue_expected_service = (
            "[Unit]\n"
            "Description=Srs User Emulator Service\n"
            "After=network.target\n"
            "StartLimitIntervalSec=0\n"
            "[Service]\n"
            "Type=simple\n"
            "Restart=always\n"
            "RestartSec=1\n"
            "ExecStart=/build/srsue/src/srsue --usim.algo=milenage --nas.apn=oai.ipv4 --rf.device_name=zmq --rf.device_args=tx_port=tcp://*:2001,rx_port=tcp://localhost:2000,id=ue,base_srate=23.04e6 /config/ue.conf\n"  # noqa: E501, W505
            "User=root\n"
            "KillSignal=SIGINT\n"
            "TimeoutStopSec=10\n"
            "ExecStopPost=service srsenb restart\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target"
        )

        assert mock_open_write_srsenb_service.writen_data == srsenb_expected_service
        assert mock_open_write_srsue_service.writen_data == srsue_expected_service
