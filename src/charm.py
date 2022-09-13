#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the SRS RAN simulator."""

import logging
import os
import shutil
from typing import Optional

from jinja2 import Template
from ops.charm import (
    ActionEvent,
    CharmBase,
    ConfigChangedEvent,
    InstallEvent,
    RelationChangedEvent,
    StartEvent,
    StopEvent,
    UpdateStatusEvent,
)
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus

from utils import (
    copy_files,
    git_clone,
    install_apt_package,
    ip_from_default_iface,
    ip_from_iface,
    is_ipv4,
    service_active,
    service_enable,
    service_restart,
    service_start,
    service_stop,
    shell,
    systemctl_daemon_reload,
    update_apt_cache,
)

logger = logging.getLogger(__name__)

APT_REQUIREMENTS = [
    "git",
    "libzmq3-dev",
    "cmake",
    "build-essential",
    "libmbedtls-dev",
    "libboost-program-options-dev",
    "libsctp-dev",
    "libconfig++-dev",
    "libfftw3-dev",
    "net-tools",
]

GIT_REPO = "https://github.com/srsLTE/srsLTE.git"
GIT_REPO_TAG = "release_20_10"

SRC_PATH = "/srsLTE"
BUILD_PATH = "/build"
CONFIG_PATH = "/config"
SERVICE_PATH = "/service"

CONFIG_PATHS = {
    "enb": f"{CONFIG_PATH}/enb.conf",
    "drb": f"{CONFIG_PATH}/drb.conf",
    "rr": f"{CONFIG_PATH}/rr.conf",
    "sib": f"{CONFIG_PATH}/sib.conf",
    "sib.mbsfn": f"{CONFIG_PATH}/sib.mbsfn.conf",
    "ue": f"{CONFIG_PATH}/ue.conf",
}

CONFIG_ORIGIN_PATHS = {
    "enb": f"{SRC_PATH}/srsenb/enb.conf.example",
    "drb": f"{SRC_PATH}/srsenb/drb.conf.example",
    "rr": f"{SRC_PATH}/srsenb/rr.conf.example",
    "sib": f"{SRC_PATH}/srsenb/sib.conf.example",
    "sib.mbsfn": f"{SRC_PATH}/srsenb/sib.conf.mbsfn.example",
    "ue": f"{SRC_PATH}/srsue/ue.conf.example",
}

SRS_ENB_SERVICE = "srsenb"
SRS_ENB_BINARY = f"{BUILD_PATH}/srsenb/src/srsenb"
SRS_ENB_SERVICE_TEMPLATE = "./templates/srsenb.service"
SRS_ENB_SERVICE_PATH = "/etc/systemd/system/srsenb.service"

SRS_UE_SERVICE = "srsue"
SRS_UE_BINARY = f"{BUILD_PATH}/srsue/src/srsue"
SRS_UE_SERVICE_TEMPLATE = "./templates/srsue.service"
SRS_UE_SERVICE_PATH = "/etc/systemd/system/srsue.service"

SRS_ENB_UE_BUILD_COMMAND = f"cd {BUILD_PATH} && cmake {SRC_PATH} && make -j `nproc` srsenb srsue"


class SrsLteCharm(CharmBase):
    """Srs LTE charm."""

    _stored = StoredState()

    def __init__(self, *args):
        """Observes various events."""
        super().__init__(*args)

        self._stored.set_default(
            mme_addr=None,
            bind_addr=None,
            ue_usim_imsi=None,
            ue_usim_k=None,
            ue_usim_opc=None,
            installed=False,
            started=False,
            ue_attached=False,
        )

        # Basic hooks
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)

        # Actions hooks
        self.framework.observe(self.on.attach_ue_action, self._on_attach_ue_action)
        self.framework.observe(self.on.detach_ue_action, self._on_detach_ue_action)
        self.framework.observe(self.on.remove_default_gw_action, self._on_remove_default_gw_action)

        # Relations hooks
        self.framework.observe(self.on.mme_relation_changed, self._mme_relation_changed)

    def _on_install(self, _: InstallEvent) -> None:
        """Triggered on install event."""
        self.unit.status = MaintenanceStatus("Installing apt packages")

        update_apt_cache()
        for package in APT_REQUIREMENTS:
            install_apt_package(package)

        self.unit.status = MaintenanceStatus("Preparing the environment")
        self._reset_environment()

        self.unit.status = MaintenanceStatus("Downloading srsLTE from Github")
        git_clone(GIT_REPO, output_folder=SRC_PATH, branch=GIT_REPO_TAG, depth=1)

        self.unit.status = MaintenanceStatus("Building srsLTE")
        shell(SRS_ENB_UE_BUILD_COMMAND)

        self.unit.status = MaintenanceStatus("Generating configuration files")
        copy_files(origin=CONFIG_ORIGIN_PATHS, destination=CONFIG_PATHS)

        self.unit.status = MaintenanceStatus("Generating systemd files")
        self._configure_srsenb_service()
        self._configure_srsue_service()

        service_enable(SRS_ENB_SERVICE)
        self._stored.installed = True

    def _on_start(self, _: StartEvent) -> None:
        """Triggered on start event."""
        self.unit.status = MaintenanceStatus("Starting srsenb")
        service_start(SRS_ENB_SERVICE)
        self._stored.started = True
        self.unit.status = self._get_current_status()

    def _on_stop(self, _: StopEvent):
        """Triggered on stop event."""
        self._reset_environment()
        service_stop(SRS_ENB_SERVICE)
        self._stored.started = False
        self.unit.status = self._get_current_status()

    def _on_config_changed(self, _: ConfigChangedEvent):
        """Triggered on config changed event."""
        self._stored.bind_addr = self._get_bind_address()
        self._configure_srsenb_service()
        if self._stored.started:
            self.unit.status = MaintenanceStatus("Reloading srsenb")
            service_restart(SRS_ENB_SERVICE)
        self.unit.status = self._get_current_status()

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Triggered on update status event."""
        self.unit.status = self._get_current_status()

    def _on_attach_ue_action(self, event: ActionEvent) -> None:
        """Triggered on attach_ue action."""
        self._stored.ue_usim_imsi = event.params["usim-imsi"]
        self._stored.ue_usim_k = event.params["usim-k"]
        self._stored.ue_usim_opc = event.params["usim-opc"]
        self._configure_srsue_service()
        service_restart(SRS_UE_SERVICE)
        self._stored.ue_attached = True
        self.unit.status = self._get_current_status()
        event.set_results({"status": "ok", "message": "Attached successfully"})

    def _on_detach_ue_action(self, event: ActionEvent) -> None:
        """Triggered on detach_ue action."""
        self._stored.ue_usim_imsi = None
        self._stored.ue_usim_k = None
        self._stored.ue_usim_opc = None
        service_stop(SRS_UE_SERVICE)
        self._configure_srsue_service()
        self._stored.ue_attached = False
        self.unit.status = self._get_current_status()
        event.set_results({"status": "ok", "message": "Detached successfully"})

    def _on_remove_default_gw_action(self, event: ActionEvent):
        """Triggered on remove_default_gw action."""
        shell("route del default")
        event.set_results({"status": "ok", "message": "Default route removed!"})

    def _mme_relation_changed(self, event: RelationChangedEvent) -> None:
        """Triggered on MME relation changed event.

        Retrieves MME address from relation, configures the srs enb service and restarts it.
        """
        if event.unit in event.relation.data:
            mme_addr = event.relation.data[event.unit].get("mme-addr")
            if not is_ipv4(mme_addr):
                return
            self._stored.mme_addr = mme_addr
            self._configure_srsenb_service()
            if self._stored.started:
                self.unit.status = MaintenanceStatus("Reloading srsenb")
                service_restart(SRS_ENB_SERVICE)
        self.unit.status = self._get_current_status()

    def _configure_srsenb_service(self) -> None:
        """Configures srs enb service."""
        self._configure_service(
            command=self._get_srsenb_command(),
            service_template=SRS_ENB_SERVICE_TEMPLATE,
            service_path=SRS_ENB_SERVICE_PATH,
        )

    def _configure_srsue_service(self) -> None:
        """Configures srs ue service."""
        self._configure_service(
            command=self._get_srsue_command(),
            service_template=SRS_UE_SERVICE_TEMPLATE,
            service_path=SRS_UE_SERVICE_PATH,
        )

    @staticmethod
    def _configure_service(
        command: str,
        service_template: str,
        service_path: str,
    ) -> None:
        """Renders service template and reload daemon service."""
        with open(service_template, "r") as template:
            service_content = Template(template.read()).render(command=command)
            with open(service_path, "w") as service:
                service.write(service_content)
            systemctl_daemon_reload()

    def _get_srsenb_command(self) -> str:
        """Returns srs enb command."""
        srsenb_command = [SRS_ENB_BINARY]
        if self._stored.mme_addr:
            srsenb_command.append(f"--enb.mme_addr={self._stored.mme_addr}")
        if self._stored.bind_addr:
            srsenb_command.append(f"--enb.gtp_bind_addr={self._stored.bind_addr}")
            srsenb_command.append(f"--enb.s1c_bind_addr={self._stored.bind_addr}")
        srsenb_command.append(f'--enb.name={self.config.get("enb-name")}')
        srsenb_command.append(f'--enb.mcc={self.config.get("enb-mcc")}')
        srsenb_command.append(f'--enb.mnc={self.config.get("enb-mnc")}')
        srsenb_command.append(f'--enb_files.rr_config={CONFIG_PATHS["rr"]}')
        srsenb_command.append(f'--enb_files.sib_config={CONFIG_PATHS["sib"]}')
        srsenb_command.append(f'--enb_files.drb_config={CONFIG_PATHS["drb"]}')
        srsenb_command.append(CONFIG_PATHS["enb"])
        srsenb_command.append(f'--rf.device_name={self.config.get("enb-rf-device-name")}')
        srsenb_command.append(f'--rf.device_args={self.config.get("enb-rf-device-args")}')
        return " ".join(srsenb_command)

    def _get_srsue_command(self) -> str:
        """Returns srs ue command."""
        srsue_command = [SRS_UE_BINARY]
        if self._stored.ue_usim_imsi:
            srsue_command.append(f"--usim.imsi={self._stored.ue_usim_imsi}")
            srsue_command.append(f"--usim.k={self._stored.ue_usim_k}")
            srsue_command.append(f"--usim.opc={self._stored.ue_usim_opc}")
        srsue_command.append(f'--usim.algo={self.config.get("ue-usim-algo")}')
        srsue_command.append(f'--nas.apn={self.config.get("ue-nas-apn")}')
        srsue_command.append(f'--rf.device_name={self.config.get("ue-device-name")}')
        srsue_command.append(f'--rf.device_args={self.config.get("ue-device-args")}')
        srsue_command.append(CONFIG_PATHS["ue"])
        return " ".join(srsue_command)

    @staticmethod
    def _reset_environment() -> None:
        """Resets environment.

        Remove old folders (if they exist) and create needed ones.
        """
        shutil.rmtree(SRC_PATH, ignore_errors=True)
        shutil.rmtree(BUILD_PATH, ignore_errors=True)
        shutil.rmtree(CONFIG_PATH, ignore_errors=True)
        shutil.rmtree(SERVICE_PATH, ignore_errors=True)
        os.mkdir(SRC_PATH)
        os.mkdir(BUILD_PATH)
        os.mkdir(CONFIG_PATH)
        os.mkdir(SERVICE_PATH)

    def _get_bind_address(self) -> Optional[str]:
        """Returns bind address."""
        bind_address_subnet = self.model.config.get("bind-address-subnet")
        if bind_address_subnet:
            bind_addr = ip_from_iface(bind_address_subnet)
        else:
            bind_addr = ip_from_default_iface()
        return bind_addr

    def _get_current_status(self) -> ActiveStatus:
        """Returns current status."""
        status_type = ActiveStatus
        status_msg = ""
        if self._stored.installed:
            status_msg = "SW installed."
        if self._stored.started and service_active(SRS_ENB_SERVICE):
            status_msg = "srsenb started. "
            if mme_addr := self._stored.mme_addr:
                status_msg += f"mme: {mme_addr}. "
            if self._stored.ue_attached and service_active(SRS_UE_SERVICE):
                status_msg += "ue attached. "
        return status_type(status_msg)


if __name__ == "__main__":
    main(SrsLteCharm)
