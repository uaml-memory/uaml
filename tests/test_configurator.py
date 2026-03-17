"""Tests for UAML Security Configurator."""

import json
import pytest
from unittest.mock import patch, mock_open
from uaml.security.configurator import (
    SecurityConfigurator,
    Platform,
    CommandCategory,
    RiskLevel,
    GeneratedCommand,
    ConfigProfile,
    ExpertMode,
    ExpertAccessLevel,
    ExpertSession,
)


class TestPlatformDetection:
    """Test platform auto-detection."""

    def test_detect_wsl2(self):
        with patch("builtins.open", mock_open(read_data="Linux microsoft-standard-WSL2")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                assert cfg.platform == Platform.WSL2

    def test_detect_linux(self):
        with patch("builtins.open", mock_open(read_data="Linux 6.1.0-generic")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                assert cfg.platform == Platform.LINUX

    def test_detect_macos(self):
        with patch("platform.system", return_value="Darwin"):
            cfg = SecurityConfigurator()
            assert cfg.platform == Platform.MACOS

    def test_detect_windows(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            assert cfg.platform == Platform.WINDOWS

    def test_detect_unknown(self):
        with patch("platform.system", return_value="FreeBSD"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = SecurityConfigurator()
                assert cfg.platform == Platform.UNKNOWN


class TestFirewallRules:
    """Test firewall rule generation."""

    def test_linux_firewall_ufw(self):
        with patch("builtins.open", mock_open(read_data="Linux 6.1.0-generic")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                rules = cfg.firewall_rules(ports=[8780], allow_from="localhost")
                assert len(rules) > 0
                assert any("ufw" in r.command for r in rules)
                assert all(r.category == CommandCategory.FIREWALL for r in rules)

    def test_linux_firewall_from_lan(self):
        with patch("builtins.open", mock_open(read_data="Linux 6.1.0-generic")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                rules = cfg.firewall_rules(ports=[8780], allow_from="lan")
                ufw_rules = [r for r in rules if "ufw allow" in r.command and "8780" in r.command]
                assert len(ufw_rules) >= 1
                assert "192.168.0.0/16" in ufw_rules[0].command

    def test_windows_firewall(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            rules = cfg.firewall_rules(ports=[8780, 8785])
            assert len(rules) >= 2
            assert any("New-NetFirewallRule" in r.command for r in rules)

    def test_windows_firewall_localhost(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            rules = cfg.firewall_rules(ports=[8780], allow_from="localhost")
            fw_rules = [r for r in rules if "127.0.0.1" in r.command]
            assert len(fw_rules) >= 1

    def test_macos_firewall(self):
        with patch("platform.system", return_value="Darwin"):
            cfg = SecurityConfigurator()
            rules = cfg.firewall_rules(ports=[8780])
            assert any("socketfilterfw" in r.command for r in rules)
            assert any("pfctl" in r.command for r in rules)

    def test_wsl2_port_forwarding(self):
        with patch("builtins.open", mock_open(read_data="Linux microsoft-WSL2")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                rules = cfg.firewall_rules(ports=[8780])
                wsl_rules = [r for r in rules if r.platform == Platform.WSL2]
                assert len(wsl_rules) >= 1
                assert any("portproxy" in r.command for r in wsl_rules)

    def test_default_ports(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            rules = cfg.firewall_rules()  # No ports = defaults
            port_strs = " ".join(r.command for r in rules)
            assert "8780" in port_strs
            assert "8781" in port_strs
            assert "8785" in port_strs

    def test_all_commands_have_required_fields(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            rules = cfg.firewall_rules(ports=[8780])
            for r in rules:
                assert r.title
                assert r.description
                assert r.command
                assert isinstance(r.risk, RiskLevel)
                assert isinstance(r.category, CommandCategory)


class TestDirectoryExclusions:
    """Test antivirus/directory exclusion generation."""

    def test_windows_defender_exclusion(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            cmds = cfg.directory_exclusions(dirs=["/home/user/.uaml"])
            assert len(cmds) >= 1
            assert any("Add-MpPreference" in c.command for c in cmds)

    def test_macos_spotlight_exclusion(self):
        with patch("platform.system", return_value="Darwin"):
            cfg = SecurityConfigurator()
            cmds = cfg.directory_exclusions(dirs=["/Users/test/.uaml"])
            assert any("mdutil" in c.command for c in cmds)
            assert any("tmutil" in c.command for c in cmds)

    def test_linux_clamav_exclusion(self):
        with patch("builtins.open", mock_open(read_data="Linux 6.1.0-generic")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                cmds = cfg.directory_exclusions(dirs=["/home/user/.uaml"])
                assert any("ExcludePath" in c.command for c in cmds)

    def test_wsl2_gets_both_windows_and_linux(self):
        with patch("builtins.open", mock_open(read_data="Linux microsoft-WSL2")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                cmds = cfg.directory_exclusions(dirs=["/home/user/.uaml"])
                # Should have both Windows Defender + ClamAV
                has_windows = any("Add-MpPreference" in c.command for c in cmds)
                has_linux = any("ExcludePath" in c.command for c in cmds)
                assert has_windows and has_linux


class TestWSL2Config:
    """Test WSL2 configuration generation."""

    def test_wsl_conf_generation(self):
        with patch("builtins.open", mock_open(read_data="Linux microsoft-WSL2")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                cmds = cfg.wsl2_config(interop=True)
                assert len(cmds) >= 2
                wsl_conf = [c for c in cmds if "wsl.conf" in c.title]
                assert len(wsl_conf) == 1
                assert "metadata" in wsl_conf[0].command

    def test_wsl_interop_disabled(self):
        with patch("builtins.open", mock_open(read_data="Linux microsoft-WSL2")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                cmds = cfg.wsl2_config(interop=False)
                wsl_conf = [c for c in cmds if "wsl.conf" in c.title][0]
                assert "enabled = false" in wsl_conf.command


class TestBitLocker:
    """Test BitLocker command generation."""

    def test_bitlocker_commands(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            cmds = cfg.bitlocker_commands(vhd_size_gb=20)
            assert len(cmds) >= 3  # Create VHD, Enable BitLocker, Recovery key
            assert any("diskpart" in c.command.lower() or "vdisk" in c.command.lower() for c in cmds)
            assert any("Enable-BitLocker" in c.command for c in cmds)
            assert any(c.risk == RiskLevel.HIGH for c in cmds)

    def test_bitlocker_custom_path(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            cmds = cfg.bitlocker_commands(vhd_path=r"D:\Secure\uaml.vhdx")
            assert any("D:\\Secure\\uaml.vhdx" in c.command for c in cmds)


class TestNetworkProfile:
    """Test network profile configuration."""

    def test_windows_network_profile(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            cmds = cfg.network_profile(profile="private")
            assert len(cmds) >= 1
            assert any("NetworkCategory" in c.command for c in cmds)

    def test_linux_localhost_binding(self):
        with patch("builtins.open", mock_open(read_data="Linux 6.1.0-generic")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                cmds = cfg.network_profile()
                assert any("127.0.0.1" in c.command for c in cmds)


class TestFilesystemHardening:
    """Test filesystem permission commands."""

    def test_linux_permissions(self):
        with patch("builtins.open", mock_open(read_data="Linux 6.1.0-generic")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                cmds = cfg.filesystem_hardening(data_dir="/home/user/.uaml")
                assert any("chmod 700" in c.command for c in cmds)
                assert any("chmod 600" in c.command for c in cmds)


class TestFullConfiguration:
    """Test complete configuration generation."""

    def test_full_config_generates_all_categories(self):
        with patch("builtins.open", mock_open(read_data="Linux microsoft-WSL2")):
            with patch("platform.system", return_value="Linux"):
                cfg = SecurityConfigurator()
                cmds = cfg.full_configuration(
                    ports=[8780],
                    allow_from="localhost",
                    enable_bitlocker=True,
                )
                categories = {c.category for c in cmds}
                assert CommandCategory.FIREWALL in categories
                assert CommandCategory.DIRECTORY_EXCLUSION in categories
                assert CommandCategory.WSL2_CONFIG in categories
                assert CommandCategory.BITLOCKER in categories

    def test_commands_sorted_by_order(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            cmds = cfg.full_configuration(ports=[8780])
            orders = [c.order for c in cmds]
            assert orders == sorted(orders)


class TestExport:
    """Test export functionality."""

    def test_export_json(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            cmds = cfg.firewall_rules(ports=[8780])
            result = cfg.export_script(cmds, format="json")
            data = json.loads(result)
            assert isinstance(data, list)
            assert len(data) > 0
            assert "command" in data[0]

    def test_export_text(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            cmds = cfg.firewall_rules(ports=[8780])
            result = cfg.export_script(cmds, format="text")
            assert "UAML Security Configurator" in result
            assert "DO NOT BLINDLY COPY" in result


class TestGeneratedCommand:
    """Test GeneratedCommand dataclass."""

    def test_to_dict(self):
        cmd = GeneratedCommand(
            category=CommandCategory.FIREWALL,
            platform=Platform.LINUX,
            title="Test",
            description="Test desc",
            command="echo test",
            risk=RiskLevel.LOW,
        )
        d = cmd.to_dict()
        assert d["category"] == "firewall"
        assert d["platform"] == "linux"
        assert d["risk"] == "low"


class TestConfigProfile:
    """Test ConfigProfile serialization."""

    def test_roundtrip(self):
        profile = ConfigProfile(
            name="test",
            platform=Platform.WSL2,
            ports=[8780, 8785],
            allowed_ips=["127.0.0.1"],
            exclude_dirs=["~/.uaml"],
            enable_bitlocker=True,
        )
        d = profile.to_dict()
        restored = ConfigProfile.from_dict(d)
        assert restored.name == "test"
        assert restored.platform == Platform.WSL2
        assert restored.ports == [8780, 8785]
        assert restored.enable_bitlocker is True


class TestWebUI:
    """Test web UI generation."""

    def test_generates_html(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            html = cfg.generate_web_ui()
            assert "<!DOCTYPE html>" in html
            assert "Security Configurator" in html
            assert "windows" in html  # platform injected

    def test_contains_wizard_steps(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            html = cfg.generate_web_ui()
            assert "Firewall" in html
            assert "BitLocker" in html
            assert "WSL2" in html
            assert "Antivirus" in html

    def test_contains_run_buttons(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            html = cfg.generate_web_ui()
            assert "runCmd" in html
            assert "runAll" in html
            assert "Spustit" in html

    def test_contains_execution_api(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            html = cfg.generate_web_ui()
            assert "/api/execute" in html

    def test_localhost_only_warning(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            html = cfg.generate_web_ui()
            assert "localhost" in html
            assert "AI agent" in html


class TestServe:
    """Test serve method security."""

    def test_serve_forces_localhost(self):
        """Serve should force 127.0.0.1 even if different host passed."""
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = SecurityConfigurator()
                assert hasattr(cfg, "serve")
                import inspect
                sig = inspect.signature(cfg.serve)
                assert sig.parameters["host"].default == "127.0.0.1"
                assert sig.parameters["port"].default == 8785


class TestExpertMode:
    """Test Expert Mode — temporary AI agent access."""

    def test_start_session(self):
        expert = ExpertMode()
        session = expert.start_session(duration_minutes=15, reason="test")
        assert expert.is_active
        assert session.access_level == ExpertAccessLevel.DIAGNOSTIC
        assert session.reason == "test"

    def test_stop_session(self):
        expert = ExpertMode()
        expert.start_session(duration_minutes=5)
        assert expert.is_active
        stopped = expert.stop_session()
        assert not expert.is_active
        assert stopped is not None

    def test_cannot_start_two_sessions(self):
        expert = ExpertMode()
        expert.start_session(duration_minutes=5)
        with pytest.raises(RuntimeError):
            expert.start_session(duration_minutes=5)

    def test_diagnostic_blocks_write_commands(self):
        expert = ExpertMode()
        expert.start_session(
            duration_minutes=5,
            access_level=ExpertAccessLevel.DIAGNOSTIC,
        )
        expert.set_approval_callback(lambda cmd: True)
        result = expert.execute("ufw allow 8080")
        assert result.blocked
        assert "not whitelisted" in result.block_reason.lower()

    def test_diagnostic_allows_read_commands(self):
        expert = ExpertMode()
        expert.start_session(
            duration_minutes=5,
            access_level=ExpertAccessLevel.DIAGNOSTIC,
        )
        expert.set_approval_callback(lambda cmd: True)
        result = expert.execute("ls -la /tmp")
        assert not result.blocked
        assert result.executed

    def test_repair_allows_ufw(self):
        expert = ExpertMode()
        expert.start_session(
            duration_minutes=5,
            access_level=ExpertAccessLevel.REPAIR,
        )
        expert.set_approval_callback(lambda cmd: True)
        result = expert.execute("ufw allow 8080")
        assert not result.blocked
        # May fail on system without ufw, but shouldn't be blocked
        assert result.executed

    def test_blocks_dangerous_commands(self):
        expert = ExpertMode()
        expert.start_session(
            duration_minutes=5,
            access_level=ExpertAccessLevel.REPAIR,
        )
        expert.set_approval_callback(lambda cmd: True)
        result = expert.execute("rm -rf /")
        assert result.blocked
        assert "Blocked command" in result.block_reason

    def test_blocks_without_approval_callback(self):
        expert = ExpertMode()
        expert.start_session(
            duration_minutes=5,
            access_level=ExpertAccessLevel.REPAIR,
        )
        # No approval callback set — medium risk should be blocked
        result = expert.execute("ufw allow 8080")
        assert result.blocked

    def test_user_rejects_command(self):
        expert = ExpertMode()
        expert.start_session(
            duration_minutes=5,
            access_level=ExpertAccessLevel.REPAIR,
        )
        expert.set_approval_callback(lambda cmd: False)  # Always reject
        result = expert.execute("ufw allow 8080")
        assert result.blocked
        assert "rejected" in result.block_reason

    def test_audit_trail(self):
        expert = ExpertMode()
        expert.start_session(duration_minutes=5, reason="audit test")
        expert.set_approval_callback(lambda cmd: True)
        expert.execute("ls /tmp")
        expert.execute("rm -rf /")  # blocked
        expert.stop_session()

        trail = expert.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["commands_total"] == 2
        assert trail[0]["reason"] == "audit test"

    def test_session_to_dict(self):
        expert = ExpertMode()
        session = expert.start_session(duration_minutes=5)
        d = session.to_dict()
        assert "session_id" in d
        assert d["active"] is True
        assert d["remaining_seconds"] > 0
        expert.stop_session()

    def test_execute_without_session_raises(self):
        expert = ExpertMode()
        with pytest.raises(RuntimeError):
            expert.execute("ls")

    def test_configurator_has_expert(self):
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = SecurityConfigurator()
                assert hasattr(cfg, "expert")
                assert isinstance(cfg.expert, ExpertMode)

    def test_risk_assessment(self):
        expert = ExpertMode()
        assert expert._assess_risk("ls /tmp") == RiskLevel.LOW
        assert expert._assess_risk("ufw allow 80") == RiskLevel.MEDIUM
        assert expert._assess_risk("ufw enable") == RiskLevel.HIGH


class TestExecutionLog:
    """Test execution logging and report generation."""

    def test_log_execution(self):
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = SecurityConfigurator()
                cfg.log_execution(
                    command="ufw allow 8780",
                    title="Povolit port 8780",
                    success=True,
                    returncode=0,
                    output="Rule added",
                    risk="low",
                )
                assert len(cfg.execution_log) == 1
                assert cfg.execution_log[0]["success"] is True
                assert cfg.execution_log[0]["command"] == "ufw allow 8780"

    def test_multiple_log_entries(self):
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = SecurityConfigurator()
                cfg.log_execution("cmd1", "Test 1", True, 0, "ok")
                cfg.log_execution("cmd2", "Test 2", False, 1, "error")
                assert len(cfg.execution_log) == 2

    def test_generate_html_report(self):
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = SecurityConfigurator()
                cfg.log_execution("ls /tmp", "List tmp", True, 0, "file1\nfile2")
                cfg.log_execution("ufw enable", "Enable firewall", False, 1, "Permission denied")
                report = cfg.generate_report(format="html")
                assert "<!DOCTYPE html>" in report
                assert "UAML Security" in report
                assert "List tmp" in report
                assert "Enable firewall" in report
                assert "2" in report  # total count
                assert "1" in report  # success/fail counts

    def test_generate_json_report(self):
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = SecurityConfigurator()
                cfg.log_execution("ls", "List", True, 0, "ok")
                report = cfg.generate_report(format="json")
                data = json.loads(report)
                assert data["total_commands"] == 1
                assert data["successful"] == 1
                assert data["failed"] == 0
                assert len(data["executions"]) == 1

    def test_empty_report(self):
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = SecurityConfigurator()
                report = cfg.generate_report(format="html")
                assert "0" in report  # zero commands
                assert "<!DOCTYPE html>" in report

    def test_log_entry_has_timestamp(self):
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = SecurityConfigurator()
                cfg.log_execution("ls", "test", True, 0, "ok")
                assert "timestamp" in cfg.execution_log[0]
                assert "2026" in cfg.execution_log[0]["timestamp"]

    def test_log_entry_executor_is_user(self):
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = SecurityConfigurator()
                cfg.log_execution("ls", "test", True, 0, "ok")
                assert cfg.execution_log[0]["executor"] == "user"

    def test_web_ui_has_history_section(self):
        with patch("platform.system", return_value="Windows"):
            cfg = SecurityConfigurator()
            html = cfg.generate_web_ui()
            assert "historySection" in html
            assert "Execution History" in html
            assert "report" in html
