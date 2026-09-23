"""
Enterprise-Grade Host PID Mapping for Hexr SDK
==============================================

SECURITY MODEL: Riptides-level security through userspace standards
- No kernel modifications
- Minimal privilege escalation
- Enterprise security compliance
- Zero-trust process identity
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import Optional, Dict, Tuple
from dataclasses import dataclass
from contextvars import ContextVar

import logging

# Simple logging setup - no complex imports
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProcessContextError(Exception):
    """Process context related errors."""

    pass


@dataclass
class SecurePIDMapping:
    """Secure mapping between container PID and host PID."""

    container_pid: int
    host_pid: int
    namespace_mapping: Dict[str, str]  # pid, net, ipc, etc.
    security_context: Dict[str, str]  # user, capabilities, etc.
    validation_timestamp: float

    def is_valid(self, max_age_seconds: int = 30) -> bool:
        """Validate PID mapping is still current and secure."""
        return (time.time() - self.validation_timestamp) < max_age_seconds


class EnterpriseHostPIDMapper:
    """
    Enterprise-grade secure host PID mapping for SPIRE integration.

    HEXR ARCHITECTURE: Simplified to hostPID=true only
    - SDK Agent Pods: hostPID=true (container PID 1 → host PID 15432)
    - SPIRE Agent DaemonSet: hostPID=true (cross-namespace visibility)
    - NO shareProcessNamespace or isolated containers supported

    SECURITY PRINCIPLES:
    1. Minimal privilege - only read necessary proc files
    2. Validation - verify mapping integrity continuously
    3. Audit trail - log all PID mapping operations
    4. Fail-safe - error if hostPID=true not configured
    """

    def __init__(self):
        self.cache: Dict[int, SecurePIDMapping] = {}
        self.security_mode = self._detect_security_mode()
        self.proc_mount = self._get_proc_mount_path()

        logger.info(f"Initialized PID mapper in {self.security_mode} mode")

    def _detect_security_mode(self) -> str:
        """
        Detect current security configuration for Hexr SDK PID mapping.

        HEXR ARCHITECTURE: All SDK agent pods run with hostPID=true

        Returns:
            - "host_pid": Running with hostPID=true (direct mapping) ✅ EXPECTED
            - "unsupported": Not running with hostPID=true ❌ CONFIGURATION ERROR
        """
        # Check if we're in host PID namespace (hostPID=true)
        try:
            if os.path.exists("/proc/1/comm"):
                with open("/proc/1/comm", "r") as f:
                    comm = f.read().strip()
                    if comm in ["systemd", "init", "kthreadd"]:
                        return "host_pid"
        except (OSError, PermissionError):
            pass

        # If we reach here, hostPID=true is not configured
        logger.error("CONFIGURATION ERROR: Hexr SDK requires hostPID=true in pod spec")
        return "unsupported"

    def _get_proc_mount_path(self) -> str:
        """Get the correct /proc mount path for reading host process information."""

        # In host PID mode, use direct /proc
        if self.security_mode == "host_pid":
            return "/proc"

        # Check for host proc mount (typically /host/proc)
        for mount_path in ["/host/proc", "/proc"]:
            if os.path.exists(mount_path):
                return mount_path

        # Fallback to container proc
        return "/proc"

    def get_secure_host_pid_mapping(
        self, container_pid: Optional[int] = None
    ) -> SecurePIDMapping:
        """
        Get secure host PID mapping with enterprise security validation.

        Args:
            container_pid: Container process ID (defaults to current process)

        Returns:
            SecurePIDMapping with validated host PID

        Raises:
            ProcessContextError: If secure mapping cannot be established
        """
        if container_pid is None:
            container_pid = os.getpid()

        # Check cache first
        if container_pid in self.cache:
            cached = self.cache[container_pid]
            if cached.is_valid():
                return cached
            else:
                # Remove stale cache entry
                del self.cache[container_pid]

        # Get fresh mapping based on security mode
        try:
            if self.security_mode == "host_pid":
                mapping = self._map_host_pid_mode(container_pid)
            else:
                # CONFIGURATION ERROR: Hexr SDK requires hostPID=true
                raise ProcessContextError(
                    f"Unsupported security mode '{self.security_mode}'. Hexr SDK requires hostPID=true in pod specification."
                )

            # Validate mapping security
            self._validate_mapping_security(mapping)

            # Cache validated mapping
            self.cache[container_pid] = mapping

            # Audit log the mapping
            logger.info(
                f"Secure PID mapping: container_pid={mapping.container_pid} -> host_pid={mapping.host_pid} (mode={self.security_mode})"
            )

            return mapping

        except Exception as e:
            logger.error(f"Failed to establish secure PID mapping: {e}")
            raise ProcessContextError(f"Secure PID mapping failed: {e}")

    def _map_host_pid_mode(self, container_pid: int) -> SecurePIDMapping:
        """Map PID in hostPID=true mode (direct mapping)."""

        # In host PID mode, container PID == host PID
        host_pid = container_pid

        # Read namespace information for validation
        namespace_mapping = self._read_namespace_info(container_pid)
        security_context = self._read_security_context(container_pid)

        return SecurePIDMapping(
            container_pid=container_pid,
            host_pid=host_pid,
            namespace_mapping=namespace_mapping,
            security_context=security_context,
            validation_timestamp=time.time(),
        )

    # NOTE: Removed _map_shared_pid_mode() and _map_isolated_mode()
    # REASON: Hexr SDK architecture requires hostPID=true only
    # See: /platform/contracts/runtime/ for standard configuration

    def _read_namespace_info(self, pid: int) -> Dict[str, str]:
        """Read namespace information for security validation."""

        namespace_mapping = {}
        ns_types = ["pid", "net", "ipc", "uts", "mnt", "user"]

        for ns_type in ns_types:
            try:
                ns_file = f"{self.proc_mount}/{pid}/ns/{ns_type}"
                if os.path.exists(ns_file):
                    ns_link = os.readlink(ns_file)
                    namespace_mapping[ns_type] = ns_link
            except (OSError, PermissionError):
                pass

        return namespace_mapping

    def _read_security_context(self, pid: int) -> Dict[str, str]:
        """Read security context for validation."""

        security_context = {}

        try:
            # Read UID/GID information
            status_file = f"{self.proc_mount}/{pid}/status"
            with open(status_file, "r") as f:
                for line in f:
                    if line.startswith("Uid:"):
                        uids = line.split()[1:]
                        security_context["real_uid"] = uids[0] if uids else "unknown"
                    elif line.startswith("Gid:"):
                        gids = line.split()[1:]
                        security_context["real_gid"] = gids[0] if gids else "unknown"
                    elif line.startswith("CapEff:"):
                        security_context["capabilities"] = (
                            line.split()[1] if len(line.split()) > 1 else "none"
                        )

        except (OSError, PermissionError):
            pass

        return security_context

    def _validate_mapping_security(self, mapping: SecurePIDMapping) -> None:
        """
        Validate that the PID mapping meets enterprise security requirements.

        Raises:
            ProcessContextError: If mapping fails security validation
        """

        # Validation 1: Ensure host PID is reasonable
        if mapping.host_pid <= 0 or mapping.host_pid > 4194304:  # Linux PID_MAX
            raise ProcessContextError(f"Invalid host PID: {mapping.host_pid}")

        # Validation 2: Ensure we're not mapping to critical system processes
        critical_pids = [1, 2]  # init, kthreadd
        if mapping.host_pid in critical_pids:
            raise ProcessContextError(
                f"Cannot map to critical system PID: {mapping.host_pid}"
            )

        # Validation 3: Verify security context is appropriate
        if (
            mapping.security_context.get("real_uid") == "0"
            and self.security_mode != "host_pid"
        ):
            logger.warning(
                f"Process {mapping.host_pid} running as root - security review required"
            )

        # Validation 4: Ensure namespace isolation is maintained
        if not mapping.namespace_mapping and self.security_mode == "shared_pid":
            logger.warning(
                "No namespace information available - reduced security validation"
            )

        logger.debug(f"PID mapping security validation passed for {mapping.host_pid}")


# Global instance for SDK use
_host_pid_mapper: Optional[EnterpriseHostPIDMapper] = None


def get_enterprise_host_pid() -> int:
    """
    Get enterprise-grade secure host PID for current process.

    Returns:
        Host PID that SPIRE Enhanced Attestor can use for process identity

    Raises:
        ProcessContextError: If secure mapping cannot be established
    """
    global _host_pid_mapper

    if _host_pid_mapper is None:
        _host_pid_mapper = EnterpriseHostPIDMapper()

    mapping = _host_pid_mapper.get_secure_host_pid_mapping()
    return mapping.host_pid


def get_secure_pid_mapping_info() -> Dict[str, str]:
    """
    Get detailed information about current PID mapping for debugging/audit.

    Returns:
        Dictionary with PID mapping details for audit logging
    """
    global _host_pid_mapper

    if _host_pid_mapper is None:
        _host_pid_mapper = EnterpriseHostPIDMapper()

    mapping = _host_pid_mapper.get_secure_host_pid_mapping()

    return {
        "container_pid": str(mapping.container_pid),
        "host_pid": str(mapping.host_pid),
        "security_mode": _host_pid_mapper.security_mode,
        "proc_mount": _host_pid_mapper.proc_mount,
        "namespace_count": str(len(mapping.namespace_mapping)),
        "validation_age": str(int(time.time() - mapping.validation_timestamp)),
    }


def discover_agent_pids_from_markers(
    marker_dir: str = "/tmp/hexr-context/agent-markers",
) -> Dict[str, int]:
    """
    Discover agent PIDs from marker files (Priority Method).

    Marker files are automatically created by @hexr_agent decorator when agents start.
    This provides explicit agent_name → PID mapping for multiprocess agents.

    Args:
        marker_dir: Directory containing marker files

    Returns:
        Dict mapping agent_name to PID: {"research_analyst": 30594, "data_engineer": 30595}

    Example marker file: /tmp/hexr-context/agent-markers/research_analyst-30594.marker
    Content: {"agent_name": "research_analyst", "pid": 30594, "ppid": 30593, "timestamp": 1704067200.0}
    """
    agent_pids = {}

    try:
        marker_path = Path(marker_dir)
        if not marker_path.exists():
            logger.info(
                f"📍 Marker directory not found: {marker_dir} (falling back to /proc scanning)"
            )
            return agent_pids

        marker_files = list(marker_path.glob("*.marker"))
        if not marker_files:
            logger.info(
                f"📍 No marker files found in {marker_dir} (falling back to /proc scanning)"
            )
            return agent_pids

        logger.info(
            f"🎯 Found {len(marker_files)} marker files - using explicit agent→PID mapping"
        )

        for marker_file in marker_files:
            try:
                with open(marker_file, "r") as f:
                    marker_data = json.load(f)

                agent_name = marker_data.get("agent_name")
                pid = marker_data.get("pid")
                ppid = marker_data.get("ppid")
                timestamp = marker_data.get("timestamp", 0)

                if agent_name and pid:
                    agent_pids[agent_name] = pid
                    logger.info(
                        f"  ✓ Marker: {agent_name} → PID {pid} (ppid={ppid}, age={int(time.time() - timestamp)}s)"
                    )
                else:
                    logger.warning(f"  ⚠️  Invalid marker file: {marker_file}")

            except Exception as e:
                logger.warning(f"  ✗ Failed to read marker file {marker_file}: {e}")
                continue

        logger.info(f"📊 Discovered {len(agent_pids)} agents from marker files")

    except Exception as e:
        logger.warning(
            f"Error reading marker files: {e} (falling back to /proc scanning)"
        )

    return agent_pids


def discover_python_processes(
    proc_mount: str = "/proc", agent_script: str = None
) -> Dict[int, Dict[str, str]]:
    """
    Discover actual running Python processes for agent PID mapping (Fallback Method).

    OPTION B Implementation: Scans /proc to find real PIDs instead of using placeholders.
    Framework-agnostic: Works with CrewAI, LangChain, AutoGen, etc.

    CRITICAL: Filters by POD_UID to only include processes from THIS pod.
    With hostPID=true, we can see ALL node processes - must filter by pod!

    Args:
        proc_mount: Path to /proc (usually /proc or /host/proc)
        agent_script: Name of the agent script to filter by (optional)

    Returns:
        Dict mapping PID to process info {cmdline, exe, cwd}
    """
    discovered_processes = {}
    scanned_pids = 0
    python_pids_found = 0
    pod_filtered_pids = 0
    
    # CRITICAL: Get current pod UID for filtering
    current_pod_uid = os.environ.get("POD_UID")
    if not current_pod_uid:
        logger.error("❌ CRITICAL: POD_UID environment variable not set!")
        logger.error("   Pid-mapper CANNOT filter processes without pod UID")
        logger.error("   This will cause cross-pod PID contamination!")
        return discovered_processes
    
    logger.info(f"🔒 Filtering processes for pod UID: {current_pod_uid}")

    try:
        logger.info(f"🔍 Scanning {proc_mount} for Python processes...")
        # Iterate through /proc to find python processes
        for entry in Path(proc_mount).iterdir():
            if not entry.name.isdigit():
                continue

            scanned_pids += 1
            pid = int(entry.name)

            # Log specific PIDs we're looking for
            if pid in [23424, 23136, 22040]:  # Known agent PIDs from testing
                logger.info(f"🎯 Checking target PID {pid}...")

            cmdline_file = entry / "cmdline"
            exe_file = entry / "exe"
            cgroup_file = entry / "cgroup"

            try:
                # STEP 1: Check if process belongs to THIS pod via cgroup
                if cgroup_file.exists():
                    try:
                        cgroup_content = cgroup_file.read_text()
                        # cgroup contains pod UID in paths like:
                        # 0::/kubepods/burstable/pod{POD_UID}/...
                        if current_pod_uid not in cgroup_content:
                            # Process belongs to different pod - skip it!
                            if pid in [23424, 23136, 22040]:  # Debug specific PIDs
                                logger.info(f"  ✗ PID {pid} belongs to different pod (cgroup check)")
                            continue
                        pod_filtered_pids += 1
                    except (OSError, PermissionError) as e:
                        if pid in [23424, 23136, 22040]:
                            logger.info(f"  ✗ Cannot read cgroup for PID {pid}: {e}")
                        continue
                else:
                    # No cgroup file - process might be from different namespace
                    continue

                # STEP 2: Read command line
                if cmdline_file.exists():
                    try:
                        cmdline = cmdline_file.read_text().replace("\x00", " ").strip()
                        if pid in [23424, 23136, 22040]:
                            logger.info(f"  📄 PID {pid} cmdline: '{cmdline}'")
                    except (OSError, PermissionError) as e:
                        if pid in [23424, 23136, 22040]:
                            logger.info(f"  ✗ Cannot read PID {pid}: {e}")
                        continue

                    # Log empty cmdlines for debugging
                    if not cmdline and pid in [23424, 23136, 22040]:
                        logger.info(f"  ⚠️  PID {pid} has EMPTY cmdline")

                    # Filter for Python processes
                    if "python" in cmdline.lower():
                        python_pids_found += 1
                        logger.info(f"  ✓ Python PID {pid}: {cmdline[:120]}")
                        # Get executable path
                        exe_path = ""
                        try:
                            if exe_file.exists():
                                exe_path = str(exe_file.resolve())
                        except (OSError, PermissionError):
                            pass

                        # Filter by agent script if specified
                        if agent_script and agent_script not in cmdline:
                            logger.info(
                                f"  ✗ Skipping PID {pid}: doesn't match agent_script '{agent_script}'"
                            )
                            continue

                        logger.info(f"  ✓ Adding PID {pid} to discovered processes")
                        discovered_processes[pid] = {
                            "cmdline": cmdline,
                            "exe": exe_path,
                            "cwd": str((entry / "cwd").resolve())
                            if (entry / "cwd").exists()
                            else "",
                        }

            except (OSError, PermissionError, FileNotFoundError):
                # Process might have exited or we lack permissions
                continue

    except Exception as e:
        logger.error(f"Error discovering processes: {e}")

    logger.info(
        f"📊 Scan results: {scanned_pids} PIDs scanned, {pod_filtered_pids} in this pod, {python_pids_found} Python processes found, {len(discovered_processes)} matched filters"
    )
    logger.info(f"🔒 Pod UID filter ensured only processes from pod {current_pod_uid} were included")
    return discovered_processes


# CLI interface for hexr deploy Job execution
if __name__ == "__main__":
    import argparse
    import subprocess

    parser = argparse.ArgumentParser(
        description="Hexr Enterprise PID Mapper - Generate process context JSON files for Enhanced Attestor"
    )
    parser.add_argument(
        "--build-dir",
        required=True,
        help="Directory containing hexr build JSON templates",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for process context JSON files (/tmp/hexr-context)",
    )
    parser.add_argument("--tenant", required=True, help="Tenant name")
    parser.add_argument("--framework", required=True, help="Agent framework type")
    parser.add_argument(
        "--pod-name", required=False, help="Agent pod name to wait for (optional)"
    )
    parser.add_argument(
        "--namespace", required=False, help="Agent pod namespace (optional)"
    )

    args = parser.parse_args()

    logger.info(f"🚀 Hexr Enterprise PID Mapper starting for tenant: {args.tenant}")
    logger.info(f"📁 Reading build artifacts from: {args.build_dir}")
    logger.info(f"📤 Writing process context files to: {args.output_dir}")

    # Count expected agents from JSON template files to determine wait threshold
    build_path = Path(args.build_dir)
    expected_agent_count = 0
    if build_path.exists():
        json_templates = list(build_path.glob("hexr-agent-*.json"))
        expected_agent_count = len(json_templates)
        logger.info(f"📋 Expected {expected_agent_count} agents from JSON templates")
    else:
        logger.warning(f"⚠️  Build directory {build_path} not found, using fallback")
        expected_agent_count = 1  # Minimum fallback

    # OPTION B: Wait for agent pod to be Running before discovering PIDs
    if args.pod_name and args.namespace:
        logger.info(
            f"⏳ Waiting for agent pod {args.pod_name} in namespace {args.namespace} to be Running..."
        )
        try:
            # Wait up to 2 minutes for ALL expected agent processes to start
            # The PID mapper job runs AFTER agent pod is deployed, so wait for all processes
            max_wait = 120
            wait_interval = 5
            waited = 0

            logger.info(f"⏳ Waiting up to {max_wait}s for all {expected_agent_count} agent processes to start...")
            while waited < max_wait:
                time.sleep(wait_interval)
                waited += wait_interval

                # Check marker files first (multiprocess pattern)
                marker_mappings = discover_agent_pids_from_markers()
                if len(marker_mappings) >= expected_agent_count:
                    logger.info(
                        f"✅ Found all {len(marker_mappings)} expected marker files after {waited}s"
                    )
                    # Grace period to ensure all processes fully initialized
                    logger.info(f"⏳ Grace period: waiting 10 seconds for full initialization...")
                    time.sleep(10)
                    break

                # Fallback: check Python processes (non-multiprocess pattern)
                test_procs = discover_python_processes(proc_mount="/proc")
                if len(test_procs) >= expected_agent_count:
                    logger.info(
                        f"✅ Found all {len(test_procs)} expected Python processes after {waited}s"
                    )
                    # Grace period to ensure all sub-agents spawned
                    logger.info(f"⏳ Grace period: waiting 10 seconds for sub-agents...")
                    time.sleep(10)
                    break

                logger.info(f"   Still waiting... (marker_files={len(marker_mappings)}, procs={len(test_procs)}, expected={expected_agent_count}, elapsed={waited}/{max_wait}s)")

            if waited >= max_wait:
                logger.warning(
                    f"⚠️  Timeout waiting for all {expected_agent_count} agents, proceeding anyway..."
                )

        except Exception as e:
            logger.error(f"❌ Error while waiting: {e}")
            logger.warning(f"⚠️  Proceeding with PID discovery anyway...")
    else:
        logger.info(
            f"ℹ️  No pod name specified, proceeding with immediate PID discovery"
        )

    try:
        # Initialize PID mapper
        mapper = EnterpriseHostPIDMapper()

        # Get base host PID for this container
        base_mapping = mapper.get_secure_host_pid_mapping()
        base_host_pid = base_mapping.host_pid

        logger.info(
            f"✅ Base host PID: {base_host_pid} (container PID: {base_mapping.container_pid})"
        )
        logger.info(f"🔒 Security mode: {mapper.security_mode}")

        # Read JSON templates from build directory
        # Templates follow pattern: hexr-agent-{placeholder_pid}-{agent_name}.json
        build_path = Path(args.build_dir)
        if not build_path.exists():
            logger.error(f"❌ Build directory not found: {build_path}")
            sys.exit(1)

        json_files = sorted(list(build_path.glob("hexr-agent-*.json")))
        if not json_files:
            logger.error(
                f"❌ No hexr-agent-*.json template files found in {build_path}"
            )
            sys.exit(1)

        logger.info(f"📋 Found {len(json_files)} agent JSON templates")

        # PRIORITY: Check for marker files first (multiprocess agents)
        logger.info(f"🎯 Checking for agent marker files...")
        agent_name_to_pid = discover_agent_pids_from_markers()

        # FALLBACK: Discover actual running Python processes via /proc
        if not agent_name_to_pid:
            logger.info(
                f"🔍 No marker files found - discovering Python processes via /proc scanning..."
            )
            discovered_pids = discover_python_processes(proc_mount=mapper.proc_mount)
            logger.info(
                f"✅ Discovered {len(discovered_pids)} Python processes: {list(discovered_pids.keys())}"
            )
        else:
            logger.info(
                f"✅ Using marker files for agent→PID mapping: {agent_name_to_pid}"
            )

        # Determine PID mapping strategy based on discovery method
        if agent_name_to_pid:
            # MARKER FILE METHOD: Use explicit agent→PID mappings
            logger.info(
                f"📍 Using marker-based agent→PID mappings (multiprocess pattern detected)"
            )
            pid_mapping_strategy = "marker_explicit"
            main_agent_pid = None  # No concept of "main" with marker files
        else:
            # /PROC SCANNING METHOD: Find main agent process (not the PID mapper itself)
            main_agent_pid = None
            agent_script_name = None

            # Filter out the PID mapper's own process
            for pid, info in discovered_pids.items():
                if "enterprise_pid_mapper.py" in info["cmdline"]:
                    logger.info(f"   Skipping PID {pid} (PID mapper itself)")
                    continue
                # This should be the main agent process
                main_agent_pid = pid
                agent_script_name = (
                    info["cmdline"].split()[-1] if info["cmdline"] else "unknown"
                )
                logger.info(f"🎯 Found main agent process: PID {main_agent_pid}")
                logger.info(f"   Script: {agent_script_name}")
                logger.info(f"   Cmdline: {info['cmdline'][:100]}...")
                break

            if not main_agent_pid:
                logger.warning(
                    f"⚠️  No main agent process found, using base PID {base_host_pid}"
                )
                main_agent_pid = base_host_pid

            # Check for child processes of main agent (only for /proc scanning)
            child_pids = []
            try:
                for entry in Path(mapper.proc_mount).iterdir():
                    if not entry.name.isdigit():
                        continue
                    pid = int(entry.name)
                    stat_file = entry / "stat"
                    if stat_file.exists():
                        stat_content = stat_file.read_text()
                        # Parse: pid (comm) state ppid ...
                        parts = stat_content.split(")")
                        if len(parts) > 1:
                            ppid = int(parts[1].split()[1])
                            if ppid == main_agent_pid:
                                child_pids.append(pid)
                                logger.info(
                                    f"   Found child process: PID {pid} (parent: {main_agent_pid})"
                                )
            except Exception as e:
                logger.warning(f"⚠️  Could not scan for child processes: {e}")

            # Determine PID mapping strategy
            total_agents = len(json_files)
            total_pids = 1 + len(child_pids)  # main + children

            if total_pids == 1:
                logger.info(
                    f"📊 Pattern: Single process, async execution (1 PID for {total_agents} agents)"
                )
                logger.info(
                    f"   All {total_agents} agents will map to main PID {main_agent_pid}"
                )
                pid_mapping_strategy = "async_single_process"
            elif total_pids >= total_agents:
                logger.info(
                    f"📊 Pattern: Multi-process execution ({total_pids} PIDs for {total_agents} agents)"
                )
                logger.info(f"   Mapping agents 1:1 to discovered PIDs")
                pid_mapping_strategy = "multiprocess"
            else:
                logger.info(
                    f"📊 Pattern: Hybrid execution ({total_pids} PIDs for {total_agents} agents)"
                )
                logger.info(f"   Main agent + some workers detected")
                pid_mapping_strategy = "hybrid"

        # Create PID list for mapping
        if pid_mapping_strategy == "marker_explicit":
            # Marker files: No automatic PID list, handled per-agent below
            agent_pids = None
        elif pid_mapping_strategy == "async_single_process":
            # All agents map to main PID
            agent_pids = [main_agent_pid] * total_agents
        elif pid_mapping_strategy == "multiprocess":
            # 1:1 mapping
            agent_pids = [main_agent_pid] + child_pids[: total_agents - 1]
        else:
            # Hybrid: first agent gets main, rest get children or repeat main
            agent_pids = [main_agent_pid]
            for i in range(1, total_agents):
                if i - 1 < len(child_pids):
                    agent_pids.append(child_pids[i - 1])
                else:
                    agent_pids.append(main_agent_pid)

        # Create flat output directory structure
        # Pod metadata stored INSIDE JSON files (not in directory structure)
        output_path = Path(args.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Using flat directory structure: {output_path}")
        
        # Get pod metadata for JSON files
        pod_uid = os.environ.get("POD_UID", "unknown")
        pod_name = args.pod_name
        namespace = args.namespace

        # Process each JSON template and write process context file with real PIDs
        for idx, json_file in enumerate(json_files):
            # Parse filename: hexr-agent-1001-research_analyst.json
            filename_parts = json_file.stem.split(
                "-", 3
            )  # ['hexr', 'agent', '1001', 'research_analyst']
            if len(filename_parts) >= 4:
                placeholder_pid_str = filename_parts[2]
                agent_name = filename_parts[3]
            else:
                logger.warning(
                    f"⚠️  Could not parse filename {json_file.name}, using defaults"
                )
                placeholder_pid_str = str(1000 + idx)
                agent_name = f"agent-{idx}"

            # Read full template JSON with all AST analysis results
            with open(json_file, "r") as f:
                template_data = json.load(f)

            # Map to real PID based on strategy
            if pid_mapping_strategy == "marker_explicit":
                # Use explicit agent→PID mapping from marker files
                if agent_name in agent_name_to_pid:
                    real_host_pid = agent_name_to_pid[agent_name]
                    logger.info(
                        f"🎯 Marker mapping {agent_name}: → host PID {real_host_pid}"
                    )
                else:
                    logger.warning(f"⚠️  No marker found for {agent_name}, skipping")
                    continue
            else:
                # Use sequential PID list from /proc scanning
                real_host_pid = agent_pids[idx]
                logger.info(
                    f"🔄 /proc mapping {agent_name}: placeholder PID {placeholder_pid_str} → host PID {real_host_pid} ({pid_mapping_strategy})"
                )

            placeholder_pid = int(placeholder_pid_str)

            # Clone template and update all PIDs in process_tree
            updated_template = json.loads(json.dumps(template_data))  # Deep copy

            # Update root_pid if present
            if "root_pid" in updated_template:
                updated_template["root_pid"] = real_host_pid - 1  # Parent PID

            # Replace placeholder PID with real host PID in process_tree
            if (
                "process_tree" in updated_template
                and str(placeholder_pid) in updated_template["process_tree"]
            ):
                # Get the original process entry
                process_entry = updated_template["process_tree"][str(placeholder_pid)]

                # Update all PID references directly in the entry (NO "context" wrapper)
                if "pid" in process_entry:
                    process_entry["pid"] = real_host_pid
                if "ppid" in process_entry:
                    process_entry["ppid"] = real_host_pid - 1

                # Update SPIFFE ID with real PID
                if "spiffe_id" in process_entry:
                    process_entry["spiffe_id"] = process_entry["spiffe_id"].replace(
                        f"proc-{placeholder_pid}", f"proc-{real_host_pid}"
                    )

                # Move entry from placeholder PID key to real PID key
                updated_template["process_tree"][str(real_host_pid)] = process_entry
                del updated_template["process_tree"][str(placeholder_pid)]

            # Add pod metadata and mapping metadata to process context
            if (
                "process_tree" in updated_template
                and str(real_host_pid) in updated_template["process_tree"]
            ):
                process_entry = updated_template["process_tree"][str(real_host_pid)]
                
                # Add top-level pod_uid (Runtime Engineer requirement)
                updated_template["pod_uid"] = pod_uid
                
                # Add metadata directly to _hexr_internal
                if "_hexr_internal" not in updated_template:
                    updated_template["_hexr_internal"] = {}
                if not isinstance(updated_template["_hexr_internal"], dict):
                    updated_template["_hexr_internal"] = {}
                
                # Enhanced _hexr_internal structure (Runtime Engineer requirement)
                # Extract framework from process_entry
                framework = process_entry.get("framework", "unknown")
                tenant = process_entry.get("tenant", "default")
                service_account = os.environ.get("SERVICE_ACCOUNT", "default")
                
                updated_template["_hexr_internal"]["framework"] = framework
                updated_template["_hexr_internal"]["pod_namespace"] = namespace
                updated_template["_hexr_internal"]["pod_uid"] = pod_uid
                updated_template["_hexr_internal"]["service_account"] = service_account
                updated_template["_hexr_internal"]["tenant"] = tenant
                
                # Keep pod_metadata for backward compatibility
                updated_template["_hexr_internal"]["pod_metadata"] = {
                    "pod_uid": pod_uid,
                    "pod_name": pod_name,
                    "namespace": namespace,
                }
                
                # PID mapping for debugging
                updated_template["_hexr_internal"]["pid_mapping"] = {
                    "placeholder_pid": placeholder_pid,
                    "real_host_pid": real_host_pid,
                    "mapped_at": time.time(),
                    "security_mode": mapper.security_mode,
                }

            # Write updated template with real PIDs to output directory
            # Use same naming pattern but with real host PID
            output_file = output_path / f"hexr-agent-{real_host_pid}-{agent_name}.json"
            with open(output_file, "w") as f:
                json.dump(updated_template, f, indent=2)

            logger.info(f"✅ Generated: {output_file.name}")

        logger.info(
            f"🎉 Successfully generated {len(json_files)} process context JSON files"
        )
        logger.info(f"📂 Enhanced Attestor can read from: {args.output_dir}")

        # ENTERPRISE: Continuous monitoring for agent container restarts
        logger.info(
            f"🔄 Entering continuous monitoring mode for PID changes (enterprise-grade resilience)..."
        )
        
        # Track currently monitored PIDs
        tracked_pids = set()
        if pid_mapping_strategy == "marker_explicit":
            tracked_pids = set(agent_name_to_pid.values())
        else:
            tracked_pids = set(agent_pids) if agent_pids else set()
        
        logger.info(f"📊 Initial PIDs tracked: {sorted(tracked_pids)}")
        
        monitoring_interval = 15  # seconds
        generation_count = 1
        
        while True:
            time.sleep(monitoring_interval)
            
            try:
                # Check if tracked PIDs are still alive
                dead_pids = set()
                for pid in tracked_pids:
                    proc_path = Path(f"/proc/{pid}")
                    if not proc_path.exists():
                        dead_pids.add(pid)
                
                if dead_pids:
                    logger.info(f"⚠️  Detected dead PIDs: {sorted(dead_pids)} - agent container likely restarted")
                    
                    # Rescan for new PIDs (agent restarted)
                    logger.info(f"🔍 Rescanning for new agent PIDs after container restart...")
                    
                    # Wait for agent to stabilize after restart
                    time.sleep(5)
                    
                    # Re-discover PIDs using same logic
                    marker_files_new = list(Path("/tmp/hexr-context/agent-markers").glob("*.marker"))
                    
                    if marker_files_new:
                        # Marker-based discovery (multiprocess pattern)
                        logger.info(f"🎯 Found {len(marker_files_new)} marker files after restart")
                        
                        # Track ALL PIDs from markers (agent may have multiple PIDs due to restarts)
                        agent_name_to_pids_new = {}  # agent_name → list of PIDs
                        all_new_pids = set()
                        
                        for marker_file in marker_files_new:
                            with open(marker_file, "r") as f:
                                marker_data = json.load(f)
                            
                            agent_name_marker = marker_data.get("agent_name")
                            pid_marker = marker_data.get("pid")
                            
                            if agent_name_marker and pid_marker:
                                if agent_name_marker not in agent_name_to_pids_new:
                                    agent_name_to_pids_new[agent_name_marker] = []
                                agent_name_to_pids_new[agent_name_marker].append(pid_marker)
                                all_new_pids.add(pid_marker)
                                logger.info(f"  ✓ New marker: {agent_name_marker} → PID {pid_marker}")
                        
                        # Find truly new PIDs (not already tracked)
                        new_pids_to_generate = all_new_pids - tracked_pids
                        
                        if new_pids_to_generate:
                            generation_count += 1
                            logger.info(f"🔄 Generation #{generation_count}: Generating JSON files for new PIDs: {sorted(new_pids_to_generate)}")
                            
                            # Clean up old PID files
                            for old_pid in dead_pids:
                                for old_file in output_path.glob(f"hexr-agent-{old_pid}-*.json"):
                                    old_file.unlink()
                                    logger.info(f"🗑️  Removed stale file: {old_file.name}")
                            
                            # Generate new files for EACH new PID
                            for json_file in json_files:
                                filename_parts = json_file.stem.split("-", 3)
                                if len(filename_parts) >= 4:
                                    agent_name = filename_parts[3]
                                else:
                                    continue
                                
                                # Generate file for EACH PID associated with this agent
                                if agent_name in agent_name_to_pids_new:
                                    for real_host_pid in agent_name_to_pids_new[agent_name]:
                                        # Skip if we already tracked this PID
                                        if real_host_pid in tracked_pids:
                                            continue
                                        
                                        # Read template
                                        with open(json_file, "r") as f:
                                            template_data = json.load(f)
                                        
                                        # Deep copy and update PIDs
                                        updated_template = json.loads(json.dumps(template_data))
                                        
                                        if "root_pid" in updated_template:
                                            updated_template["root_pid"] = real_host_pid - 1
                                        
                                        # Get original placeholder PID from filename
                                        placeholder_pid = int(filename_parts[2])
                                        
                                        if "process_tree" in updated_template and str(placeholder_pid) in updated_template["process_tree"]:
                                            process_entry = updated_template["process_tree"][str(placeholder_pid)]
                                            
                                            if "pid" in process_entry:
                                                process_entry["pid"] = real_host_pid
                                            if "ppid" in process_entry:
                                                process_entry["ppid"] = real_host_pid - 1
                                            if "spiffe_id" in process_entry:
                                                process_entry["spiffe_id"] = process_entry["spiffe_id"].replace(
                                                    f"proc-{placeholder_pid}", f"proc-{real_host_pid}"
                                                )
                                            
                                            updated_template["process_tree"][str(real_host_pid)] = process_entry
                                            del updated_template["process_tree"][str(placeholder_pid)]
                                        
                                        if "process_tree" in updated_template and str(real_host_pid) in updated_template["process_tree"]:
                                            process_entry = updated_template["process_tree"][str(real_host_pid)]
                                            
                                            # Add top-level pod_uid (Runtime Engineer requirement)
                                            updated_template["pod_uid"] = pod_uid
                                            
                                            if "_hexr_internal" not in updated_template:
                                                updated_template["_hexr_internal"] = {}
                                            if not isinstance(updated_template["_hexr_internal"], dict):
                                                updated_template["_hexr_internal"] = {}
                                            
                                            # Enhanced _hexr_internal structure (Runtime Engineer requirement)
                                            framework = process_entry.get("framework", "unknown")
                                            tenant = process_entry.get("tenant", "default")
                                            service_account = os.environ.get("SERVICE_ACCOUNT", "default")
                                            
                                            updated_template["_hexr_internal"]["framework"] = framework
                                            updated_template["_hexr_internal"]["pod_namespace"] = namespace
                                            updated_template["_hexr_internal"]["pod_uid"] = pod_uid
                                            updated_template["_hexr_internal"]["service_account"] = service_account
                                            updated_template["_hexr_internal"]["tenant"] = tenant
                                            
                                            # Keep pod_metadata for backward compatibility
                                            updated_template["_hexr_internal"]["pod_metadata"] = {
                                                "pod_uid": pod_uid,
                                                "pod_name": pod_name,
                                                "namespace": namespace,
                                            }
                                            
                                            updated_template["_hexr_internal"]["pid_mapping"] = {
                                                "placeholder_pid": placeholder_pid,
                                                "real_host_pid": real_host_pid,
                                                "mapped_at": time.time(),
                                                "security_mode": mapper.security_mode,
                                                "generation": generation_count,
                                                "restart_detected": True
                                            }
                                        
                                        output_file = output_path / f"hexr-agent-{real_host_pid}-{agent_name}.json"
                                        with open(output_file, "w") as f:
                                            json.dump(updated_template, f, indent=2)
                                        
                                        logger.info(f"✅ Regenerated: {output_file.name} (gen #{generation_count})")
                            
                            # Update tracked PIDs to include all new PIDs
                            tracked_pids.update(all_new_pids)
                            logger.info(f"✅ PID mapping updated. Now tracking {len(tracked_pids)} PIDs: {sorted(tracked_pids)}")
                    else:
                        # /proc-based discovery fallback (should rarely happen with marker files)
                        logger.info(f"🔍 Rescanning /proc for new Python processes...")
                        discovered_pids = discover_python_processes(proc_mount=mapper.proc_mount)
                        logger.info(f"✅ Discovered {len(discovered_pids)} Python processes after restart")
                        
                        # Find main agent process (not PID mapper itself)
                        new_main_pid = None
                        for pid, info in discovered_pids.items():
                            if "enterprise_pid_mapper.py" not in info["cmdline"]:
                                new_main_pid = pid
                                break
                        
                        if new_main_pid:
                            new_pids = set([new_main_pid])
                            if new_pids != tracked_pids:
                                generation_count += 1
                                logger.info(f"🔄 Generation #{generation_count}: Found new main PID {new_main_pid}")
                                
                                # Clean up old files
                                for old_pid in dead_pids:
                                    for old_file in output_path.glob(f"hexr-agent-{old_pid}-*.json"):
                                        old_file.unlink()
                                        logger.info(f"🗑️  Removed stale file: {old_file.name}")
                                
                                # Regenerate files with new PID
                                for json_file in json_files:
                                    filename_parts = json_file.stem.split("-", 3)
                                    if len(filename_parts) >= 4:
                                        placeholder_pid_str = filename_parts[2]
                                        agent_name = filename_parts[3]
                                    else:
                                        continue
                                    
                                    real_host_pid = new_main_pid
                                    placeholder_pid = int(placeholder_pid_str)
                                    
                                    with open(json_file, "r") as f:
                                        template_data = json.load(f)
                                    
                                    updated_template = json.loads(json.dumps(template_data))
                                    
                                    if "root_pid" in updated_template:
                                        updated_template["root_pid"] = real_host_pid - 1
                                    
                                    if "process_tree" in updated_template and str(placeholder_pid) in updated_template["process_tree"]:
                                        process_entry = updated_template["process_tree"][str(placeholder_pid)]
                                        
                                        if "pid" in process_entry:
                                            process_entry["pid"] = real_host_pid
                                        if "ppid" in process_entry:
                                            process_entry["ppid"] = real_host_pid - 1
                                        if "spiffe_id" in process_entry:
                                            process_entry["spiffe_id"] = process_entry["spiffe_id"].replace(
                                                f"proc-{placeholder_pid}", f"proc-{real_host_pid}"
                                            )
                                        
                                        updated_template["process_tree"][str(real_host_pid)] = process_entry
                                        del updated_template["process_tree"][str(placeholder_pid)]
                                    
                                    if "process_tree" in updated_template and str(real_host_pid) in updated_template["process_tree"]:
                                        if "_hexr_internal" not in updated_template:
                                            updated_template["_hexr_internal"] = {}
                                        if not isinstance(updated_template["_hexr_internal"], dict):
                                            updated_template["_hexr_internal"] = {}
                                        
                                        # Add pod metadata for auto-registrar
                                        updated_template["_hexr_internal"]["pod_metadata"] = {
                                            "pod_uid": pod_uid,
                                            "pod_name": pod_name,
                                            "namespace": namespace,
                                        }
                                        
                                        updated_template["_hexr_internal"]["pid_mapping"] = {
                                            "placeholder_pid": placeholder_pid,
                                            "real_host_pid": real_host_pid,
                                            "mapped_at": time.time(),
                                            "security_mode": mapper.security_mode,
                                            "generation": generation_count,
                                            "restart_detected": True
                                        }
                                    
                                    output_file = output_path / f"hexr-agent-{real_host_pid}-{agent_name}.json"
                                    with open(output_file, "w") as f:
                                        json.dump(updated_template, f, indent=2)
                                    
                                    logger.info(f"✅ Regenerated: {output_file.name} (gen #{generation_count})")
                                
                                tracked_pids = new_pids
                                logger.info(f"✅ PID mapping updated. Now tracking PIDs: {sorted(tracked_pids)}")
                
            except Exception as monitor_error:
                logger.error(f"⚠️  Monitoring iteration error: {monitor_error}")
                # Continue monitoring despite errors

    except Exception as e:
        logger.error(f"❌ PID mapping failed: {e}")
        sys.exit(1)
