"""CLI invocation wrappers for shani-health and shani-deploy."""

import logging
import json
import subprocess
from typing import Optional, Dict, Any
import shlex

logger = logging.getLogger(__name__)


class CLIWrapper:
    """Wrapper for invoking shani-health and shani-deploy CLI tools."""
    
    def __init__(self) -> None:
        """Initialize the CLI wrapper."""
        logger.info("CLIWrapper initialized")
    
    def run_shani_health(self, args: list[str]) -> Optional[Dict[Any, Any]]:
        """Run shani-health with given arguments and return parsed JSON output.
        
        Args:
            args: List of arguments to pass to shani-health (e.g., ['--verify', '--json'])
            
        Returns:
            Parsed JSON output as dictionary, or None if failed
        """
        try:
            cmd = ['shani-health'] + args
            logger.debug(f"Running command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"shani-health failed with return code {result.returncode}: {result.stderr}")
                return None
            
            # Try to parse as JSON
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning(f"shani-health output is not valid JSON: {result.stdout[:200]}...")
                # Return raw output wrapped in a dict for consistency
                return {"raw_output": result.stdout}
                
        except subprocess.TimeoutExpired:
            logger.error("shani-health command timed out")
            return None
        except Exception as e:
            logger.error(f"Failed to run shani-health: {e}")
            return None
    
    def run_shani_deploy(self, args: list[str]) -> Optional[Dict[Any, Any]]:
        """Run shani-deploy with given arguments and return parsed output.
        
        Args:
            args: List of arguments to pass to shani-deploy (e.g., ['--check', '--json'])
            
        Returns:
            Parsed output as dictionary, or None if failed
        """
        try:
            cmd = ['shani-deploy'] + args
            logger.debug(f"Running command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"shani-deploy failed with return code {result.returncode}: {result.stderr}")
                return None
            
            # Try to parse as JSON
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning(f"shani-deploy output is not valid JSON: {result.stdout[:200]}...")
                # Return raw output wrapped in a dict for consistency
                return {"raw_output": result.stdout}
                
        except subprocess.TimeoutExpired:
            logger.error("shani-deploy command timed out")
            return None
        except Exception as e:
            logger.error(f"Failed to run shani-deploy: {e}")
            return None
    
    def get_health_verify(self) -> Optional[Dict[Any, Any]]:
        """Get system verification health check.
        
        Returns:
            Health check results or None if failed
        """
        return self.run_shani_health(['--verify', '--json'])
    
    def get_health_security(self) -> Optional[Dict[Any, Any]]:
        """Get security audit health check.
        
        Returns:
            Security audit results or None if failed
        """
        return self.run_shani_health(['--security', '--json'])
    
    def get_health_hardware(self) -> Optional[Dict[Any, Any]]:
        """Get hardware check health check.
        
        Returns:
            Hardware check results or None if failed
        """
        return self.run_shani_health(['--hardware', '--json'])

    def get_health_boot(self) -> Optional[Dict[Any, Any]]:
        """Get boot validation health check.
        
        Returns:
            Boot validation results or None if failed
        """
        return self.run_shani_health(['--boot', '--json'])

    def get_health_all(self) -> Optional[Dict[Any, Any]]:
        """Get all health checks.
        
        Returns:
            All health check results or None if failed
        """
        return self.run_shani_health(['--all', '--json'])

    # Pulsar OS Sayri integration methods

    def pulsar_skill_install(self, skill_name: str, force: bool = False) -> Optional[Dict[Any, Any]]:
        """Install a Pulsar skill.
        
        Args:
            skill_name: Name of the skill to install
            force: Whether to force installation even if skill already exists
            
        Returns:
            Installation result or None if failed
        """
        args = ['skill', 'install', skill_name]
        if force:
            args.append('--force')
        return self.run_pulsar_skill(args)

    def pulsar_skill_remove(self, skill_name: str, purge: bool = False) -> Optional[Dict[Any, Any]]:
        """Remove a Pulsar skill.
        
        Args:
            skill_name: Name of the skill to remove
            purge: Whether to purge skill configuration
            
        Returns:
            Removal result or None if failed
        """
        args = ['skill', 'uninstall', skill_name]
        if purge:
            args.append('--purge')
        return self.run_pulsar_skill(args)

    def pulsar_scan_virustotal(self, target: str, recursive: bool = False, timeout: int = 60) -> Optional[Dict[Any, Any]]:
        """Run VirusTotal security scan on target.
        
        Args:
            target: File path or URL to scan
            recursive: Whether to scan recursively
            timeout: Scan timeout in seconds
            
        Returns:
            Scan results or None if failed
        """
        args = ['scan', 'virustotal', target, f'--timeout={timeout}']
        if recursive:
            args.append('--recursive')
        return self.run_pulsar_scan(args)

    def gateway_send_command(self, gateway: str, command: str, profile: str = "default") -> Optional[Dict[Any, Any]]:
        """Send command to Pulsar gateway (Telegram/Discord).
        
        Args:
            gateway: Gateway name (telegram or discord)
            command: Command to execute
            profile: Agent profile to use
            
        Returns:
            Command execution result or None if failed
        """
        args = ['gateway', 'send', '--gateway', gateway, '--command', command, '--profile', profile]
        return self.run_pulsar_gateway(args)

    def run_pulsar_skill(self, args: list[str]) -> Optional[Dict[Any, Any]]:
        """Run pulsar-skill with given arguments and return parsed JSON output.
        
        Args:
            args: List of arguments to pass to pulsar-skill
            
        Returns:
            Parsed JSON output as dictionary, or None if failed
        """
        try:
            cmd = ['pulsar-skill'] + args
            logger.debug(f"Running command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"pulsar-skill failed with return code {result.returncode}: {result.stderr}")
                return None
            
            # Try to parse as JSON
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning(f"pulsar-skill output is not valid JSON: {result.stdout[:200]}...")
                # Return raw output wrapped in a dict for consistency
                return {"raw_output": result.stdout}
                
        except subprocess.TimeoutExpired:
            logger.error("pulsar-skill command timed out")
            return None
        except Exception as e:
            logger.error(f"Failed to run pulsar-skill: {e}")
            return None

    def run_pulsar_scan(self, args: list[str]) -> Optional[Dict[Any, Any]]:
        """Run pulsar-scan with given arguments and return parsed JSON output.
        
        Args:
            args: List of arguments to pass to pulsar-scan
            
        Returns:
            Parsed JSON output as dictionary, or None if failed
        """
        try:
            cmd = ['pulsar-scan'] + args
            logger.debug(f"Running command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"pulsar-scan failed with return code {result.returncode}: {result.stderr}")
                return None
            
            # Try to parse as JSON
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning(f"pulsar-scan output is not valid JSON: {result.stdout[:200]}...")
                # Return raw output wrapped in a dict for consistency
                return {"raw_output": result.stdout}
                
        except subprocess.TimeoutExpired:
            logger.error("pulsar-scan command timed out")
            return None
        except Exception as e:
            logger.error(f"Failed to run pulsar-scan: {e}")
            return None

    def run_pulsar_gateway(self, args: list[str]) -> Optional[Dict[Any, Any]]:
        """Run pulsar-gateway with given arguments and return parsed JSON output.
        
        Args:
            args: List of arguments to pass to pulsar-gateway
            
        Returns:
            Parsed JSON output as dictionary, or None if failed
        """
        try:
            cmd = ['pulsar-gateway'] + args
            logger.debug(f"Running command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"pulsar-gateway failed with return code {result.returncode}: {result.stderr}")
                return None
            
            # Try to parse as JSON
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning(f"pulsar-gateway output is not valid JSON: {result.stdout[:200]}...")
                # Return raw output wrapped in a dict for consistency
                return {"raw_output": result.stdout}
                
        except subprocess.TimeoutExpired:
            logger.error("pulsar-gateway command timed out")
            return None
        except Exception as e:
            logger.error(f"Failed to run pulsar-gateway: {e}")
            return None
    
    def get_deploy_status(self) -> Optional[Dict[Any, Any]]:
        """Get deployment status.
        
        Returns:
            Deployment status or None if failed
        """
        return self.run_shani_deploy(['--status', '--json'])
    
    def get_deploy_updates(self) -> Optional[Dict[Any, Any]]:
        """Check for available updates.
        
        Returns:
            Update check results or None if failed
        """
        return self.run_shani_deploy(['--check', '--json'])
    
    def get_deploy_history(self) -> Optional[Dict[Any, Any]]:
        """Get deployment history.
        
        Returns:
            Deployment history or None if failed
        """
        return self.run_shani_deploy(['--history', '--json'])

    # shani-backup integration methods

    def run_shani_backup(self, args: list[str]) -> Optional[Dict[Any, Any]]:
        """Run shani-backup with given arguments and return parsed JSON output.
        
        Args:
            args: List of arguments to pass to shani-backup
            
        Returns:
            Parsed JSON output as dictionary, or None if failed
        """
        try:
            cmd = ['shani-backup'] + args
            logger.debug(f"Running command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"shani-backup failed with return code {result.returncode}: {result.stderr}")
                return None
            
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"raw_output": result.stdout}
                
        except FileNotFoundError:
            logger.warning("shani-backup not installed — returning not available")
            return None
        except subprocess.TimeoutExpired:
            logger.error("shani-backup command timed out")
            return None
        except Exception as e:
            logger.error(f"Failed to run shani-backup: {e}")
            return None

    def backup_snapshot_list(self) -> Optional[Dict[Any, Any]]:
        """List Btrfs snapshots.
        
        Returns:
            Snapshot list or None if unavailable
        """
        return self.run_shani_backup(['snapshot', 'list', '/'])

    def backup_scheduler_status(self) -> Optional[Dict[Any, Any]]:
        """Get backup scheduler status.
        
        Returns:
            Scheduler status or None if unavailable
        """
        return self.run_shani_backup(['schedule'])

    # shani-chronoa integration methods

    def run_shani_chronoa(self, args: list[str]) -> Optional[Dict[Any, Any]]:
        """Run shani-chronoa with given arguments and return parsed JSON output.
        
        Args:
            args: List of arguments to pass to shani-chronoa
            
        Returns:
            Parsed JSON output as dictionary, or None if failed
        """
        try:
            cmd = ['shani-chronoa'] + args
            logger.debug(f"Running command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"shani-chronoa failed with return code {result.returncode}: {result.stderr}")
                return None
            
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"raw_output": result.stdout}
                
        except FileNotFoundError:
            logger.warning("shani-chronoa not installed — returning not available")
            return None
        except subprocess.TimeoutExpired:
            logger.error("shani-chronoa command timed out")
            return None
        except Exception as e:
            logger.error(f"Failed to run shani-chronoa: {e}")
            return None

    def chronoa_status(self) -> Optional[Dict[Any, Any]]:
        """Get shani-chronoa status.
        
        Returns:
            Chronoa status or None if unavailable
        """
        return self.run_shani_chronoa(['--status'])

    def chronoa_config(self) -> Optional[Dict[Any, Any]]:
        """Get shani-chronoa configuration.
        
        Returns:
            Configuration dict or None if unavailable
        """
        return self.run_shani_chronoa(['--config'])


# Global instance
_cli_wrapper: Optional[CLIWrapper] = None


def get_cli_wrapper() -> CLIWrapper:
    """Get the global CLI wrapper instance.
    
    Returns:
        The global CLIWrapper instance
    """
    global _cli_wrapper
    if _cli_wrapper is None:
        _cli_wrapper = CLIWrapper()
    return _cli_wrapper