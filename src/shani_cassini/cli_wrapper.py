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