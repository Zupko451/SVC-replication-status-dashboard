#!/usr/bin/env python3
"""
IBM Storage Virtualize Replication Status Monitor

This script authenticates to the IBM Storage Virtualize REST API and checks
the replication status of all volume groups, highlighting any groups not in
a running state as warnings.

Author: Bob
Date: 2026-06-15
"""

import os
import sys
import json
import logging
import argparse
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import urllib3

try:
    import requests
    from requests.adapters import HTTPAdapter
    from requests.packages.urllib3.util.retry import Retry
except ImportError:
    print("Error: 'requests' library is required. Install it with: pip install requests")
    sys.exit(1)

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    COLORS_AVAILABLE = True
except ImportError:
    COLORS_AVAILABLE = False
    print("Warning: 'colorama' not installed. Install for colored output: pip install colorama")


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Config:
    """Configuration manager for IBM Storage Virtualize connection."""
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize configuration from environment variables or config file.
        
        Args:
            config_file: Optional path to JSON configuration file
        """
        self.host = None
        self.username = None
        self.password = None
        self.token = None
        self.verify_ssl = True
        self.timeout = 30
        self.log_level = "INFO"
        
        if config_file:
            self._load_from_file(config_file)
        else:
            self._load_from_env()
        
        self._validate()
    
    def _load_from_env(self):
        """Load configuration from environment variables."""
        self.host = os.getenv('IBM_SV_HOST')
        self.username = os.getenv('IBM_SV_USER')
        self.password = os.getenv('IBM_SV_PASSWORD')
        self.token = os.getenv('IBM_SV_TOKEN')
        self.verify_ssl = os.getenv('IBM_SV_VERIFY_SSL', 'true').lower() == 'true'
        self.timeout = int(os.getenv('IBM_SV_TIMEOUT', '30'))
        self.log_level = os.getenv('IBM_SV_LOG_LEVEL', 'INFO')
    
    def _load_from_file(self, config_file: str):
        """Load configuration from JSON file."""
        try:
            with open(config_file, 'r') as f:
                config_data = json.load(f)
            
            self.host = config_data.get('host')
            self.username = config_data.get('username')
            self.password = config_data.get('password')
            self.token = config_data.get('token')
            self.verify_ssl = config_data.get('verify_ssl', True)
            self.timeout = config_data.get('timeout', 30)
            self.log_level = config_data.get('log_level', 'INFO')
            
            logger.info(f"Configuration loaded from {config_file}")
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {config_file}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in configuration file: {e}")
            raise
    
    def _validate(self):
        """Validate required configuration parameters."""
        if not self.host:
            raise ValueError("IBM Storage Virtualize host is required (IBM_SV_HOST or config file)")
        
        # Ensure host has protocol
        if not self.host.startswith(('http://', 'https://')):
            self.host = f"https://{self.host}"
        
        # Remove trailing slash
        self.host = self.host.rstrip('/')
        
        # Either username/password or token must be provided
        if not self.token and not (self.username and self.password):
            raise ValueError("Either token or username/password must be provided")
        
        logger.info(f"Configuration validated for host: {self.host}")


class IBMStorageVirtualizeClient:
    """Client for IBM Storage Virtualize REST API."""
    
    # API endpoints
    AUTH_ENDPOINT = "/rest/v1/auth"
    RC_VOLGROUP_ENDPOINT = "/rest/v1/lsvolumegroupreplication"

    # link1_status values returned by lsvolumegroupreplication
    NORMAL_STATES = {
        'running',
    }

    WARNING_STATES = {
        'degraded',
        'syncing',
        'waiting_for_sync',
    }

    ERROR_STATES = {
        'stopped',
        'disconnected',
        'error',
        'failed',
    }
    
    def __init__(self, config: Config):
        """
        Initialize IBM Storage Virtualize API client.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.auth_token = config.token
        self.base_url = config.host

        # Disable SSL warnings if verification is disabled
        if not config.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            logger.warning("SSL verification is disabled")

        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create requests session with retry logic."""
        session = requests.Session()

        # Set verify at the session level so every request — including retries
        # and any followed redirects — inherits the correct SSL behaviour.
        session.verify = self.config.verify_ssl

        # Configure retry strategy — only retry on HTTP status codes, never on
        # connection/SSL failures (connect=0) which are not transient.
        retry_strategy = Retry(
            total=3,
            connect=0,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def authenticate(self) -> bool:
        """
        Authenticate to IBM Storage Virtualize API.
        
        Returns:
            True if authentication successful, False otherwise
        """
        if self.auth_token:
            logger.info("Using provided authentication token")
            return True
        
        try:
            url = f"{self.base_url}{self.AUTH_ENDPOINT}"

            # IBM Storage Virtualize expects credentials as X-Auth-* headers,
            # not HTTP Basic Auth — sending Basic Auth causes a 403
            # "Invalid Username Header" response.
            response = self.session.post(
                url,
                headers={
                    "X-Auth-Username": self.config.username,
                    "X-Auth-Password": self.config.password,
                },
                verify=self.config.verify_ssl,
                timeout=self.config.timeout
            )
            
            if response.status_code == 200:
                # Extract token from response
                auth_data = response.json()
                self.auth_token = auth_data.get('token')
                
                if self.auth_token:
                    logger.info("Authentication successful")
                    return True
                else:
                    logger.error("No token received in authentication response")
                    return False
            else:
                logger.error(f"Authentication failed: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Authentication request failed: {e}")
            return False
    
    def _make_request(self, endpoint: str, method: str = "GET", **kwargs) -> Optional[Dict]:
        """
        Make authenticated request to API.
        
        Args:
            endpoint: API endpoint path
            method: HTTP method (GET, POST, etc.)
            **kwargs: Additional arguments for requests
            
        Returns:
            Response data as dictionary or None on failure
        """
        url = f"{self.base_url}{endpoint}"
        
        headers = kwargs.pop('headers', {})
        headers['X-Auth-Token'] = self.auth_token
        
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                verify=self.config.verify_ssl,
                timeout=self.config.timeout,
                **kwargs
            )
            
            logger.debug("API %s %s -> %s", method, url, response.status_code)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 204:
                return []  # no content — valid empty response
            elif response.status_code == 401:
                logger.error("Authentication token expired or invalid")
                return None
            else:
                logger.error(f"API request failed: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return None
    
    def get_volume_groups(self) -> Optional[List[Dict]]:
        """
        Get all volume groups.
        
        Returns:
            List of volume group dictionaries or None on failure
        """
        logger.info("Fetching volume groups...")
        data = self._make_request(self.VOLUME_GROUPS_ENDPOINT, method="POST")

        if data is None:
            return None  # request failed

        volume_groups = data if isinstance(data, list) else data.get('volumegroups', [])
        logger.info(f"Retrieved {len(volume_groups)} volume groups")
        return volume_groups
    
    def get_rc_relationships(self) -> Optional[List[Dict]]:
        """
        Get all remote copy (replication) relationships.
        
        Returns:
            List of RC relationship dictionaries or None on failure
        """
        logger.info("Fetching remote copy relationships...")

        data = self._make_request(self.RC_VOLGROUP_ENDPOINT, method="POST")
        if data is None:
            return None

        relationships = data if isinstance(data, list) else []
        logger.info("Retrieved %d RC relationships", len(relationships))
        return relationships
    
    def close(self):
        """Close the session."""
        self.session.close()
        logger.info("Session closed")


class StatusAnalyzer:
    """Analyzer for replication status data."""
    
    @staticmethod
    def categorize_state(state: str) -> str:
        """
        Categorize replication state.
        
        Args:
            state: Replication state string
            
        Returns:
            Category: 'normal', 'warning', or 'error'
        """
        state_lower = state.lower()
        
        if state_lower in IBMStorageVirtualizeClient.NORMAL_STATES:
            return 'normal'
        elif state_lower in IBMStorageVirtualizeClient.WARNING_STATES:
            return 'warning'
        elif state_lower in IBMStorageVirtualizeClient.ERROR_STATES:
            return 'error'
        else:
            # Unknown state - treat as warning
            return 'warning'
    
    @staticmethod
    def analyze_relationships(relationships: List[Dict]) -> Dict:
        """
        Analyze replication relationships and generate summary.
        
        Args:
            relationships: List of RC relationship dictionaries
            
        Returns:
            Analysis summary dictionary
        """
        summary = {
            'total': len(relationships),
            'normal': 0,
            'warning': 0,
            'error': 0,
            'details': []
        }
        
        for rel in relationships:
            name  = rel.get('name', rel.get('id', 'Unknown'))
            state = rel.get('link1_status', 'unknown')

            loc1 = rel.get('location1_system_name', 'N/A')
            mode1 = rel.get('location1_replication_mode', '')
            loc2 = rel.get('location2_system_name', 'N/A')
            mode2 = rel.get('location2_replication_mode', '')
            within_rpo = rel.get('location2_within_rpo', '')
            policy = rel.get('replication_policy_name', 'N/A')

            primary_vdisk   = f"{loc1} ({mode1})" if mode1 else loc1
            secondary_vdisk = f"{loc2} ({mode2})" if mode2 else loc2

            category = StatusAnalyzer.categorize_state(state)

            detail = {
                'name': name,
                'state': state,
                'category': category,
                'primary_vdisk': primary_vdisk,
                'secondary_vdisk': secondary_vdisk,
                'within_rpo': within_rpo,
                'policy': policy,
                'raw_data': rel
            }
            
            summary['details'].append(detail)
            summary[category] += 1
        
        return summary


class OutputFormatter:
    """Formatter for console output."""
    
    @staticmethod
    def print_colored(text: str, color: str = 'white', bold: bool = False):
        """
        Print colored text to console.
        
        Args:
            text: Text to print
            color: Color name (green, yellow, red, white)
            bold: Whether to make text bold
        """
        if not COLORS_AVAILABLE:
            print(text)
            return
        
        color_map = {
            'green': Fore.GREEN,
            'yellow': Fore.YELLOW,
            'red': Fore.RED,
            'white': Fore.WHITE,
            'cyan': Fore.CYAN,
            'magenta': Fore.MAGENTA
        }
        
        color_code = color_map.get(color.lower(), Fore.WHITE)
        style = Style.BRIGHT if bold else ''
        
        print(f"{style}{color_code}{text}{Style.RESET_ALL}")
    
    @staticmethod
    def print_header(text: str):
        """Print section header."""
        OutputFormatter.print_colored(f"\n{'=' * 80}", 'cyan')
        OutputFormatter.print_colored(text, 'cyan', bold=True)
        OutputFormatter.print_colored('=' * 80, 'cyan')
    
    @staticmethod
    def print_relationship(detail: Dict):
        """
        Print replication relationship details.
        
        Args:
            detail: Relationship detail dictionary
        """
        category = detail['category']
        name = detail['name']
        state = detail['state']
        primary = detail['primary_vdisk']
        secondary = detail['secondary_vdisk']
        
        # Choose color based on category
        if category == 'normal':
            color = 'green'
            symbol = '✓'
        elif category == 'warning':
            color = 'yellow'
            symbol = '⚠'
        else:
            color = 'red'
            symbol = '✗'
        
        OutputFormatter.print_colored(
            f"{symbol} {name}: {state}",
            color,
            bold=(category != 'normal')
        )
        OutputFormatter.print_colored(
            f"  Primary: {primary} → Secondary: {secondary}",
            'white'
        )
    
    @staticmethod
    def print_summary(summary: Dict):
        """
        Print summary statistics.
        
        Args:
            summary: Summary dictionary from StatusAnalyzer
        """
        OutputFormatter.print_header("REPLICATION STATUS SUMMARY")
        
        total = summary['total']
        normal = summary['normal']
        warning = summary['warning']
        error = summary['error']
        
        print(f"\nTotal Relationships: {total}")
        OutputFormatter.print_colored(f"  ✓ Normal: {normal}", 'green')
        
        if warning > 0:
            OutputFormatter.print_colored(f"  ⚠ Warnings: {warning}", 'yellow', bold=True)
        else:
            OutputFormatter.print_colored(f"  ⚠ Warnings: {warning}", 'white')
        
        if error > 0:
            OutputFormatter.print_colored(f"  ✗ Errors: {error}", 'red', bold=True)
        else:
            OutputFormatter.print_colored(f"  ✗ Errors: {error}", 'white')
        
        # Calculate health percentage
        if total > 0:
            health_pct = (normal / total) * 100
            if health_pct == 100:
                color = 'green'
            elif health_pct >= 80:
                color = 'yellow'
            else:
                color = 'red'
            
            OutputFormatter.print_colored(f"\nOverall Health: {health_pct:.1f}%", color, bold=True)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='IBM Storage Virtualize Replication Status Monitor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using environment variables
  export IBM_SV_HOST="https://storage.example.com"
  export IBM_SV_USER="admin"
  export IBM_SV_PASSWORD="password"
  python ibm_storage_replication_check.py
  
  # Using config file
  python ibm_storage_replication_check.py --config config.json
  
  # With JSON output
  python ibm_storage_replication_check.py --output json > report.json
  
  # Disable SSL verification (for testing only)
  python ibm_storage_replication_check.py --no-verify-ssl
        """
    )
    
    parser.add_argument(
        '--config',
        type=str,
        help='Path to JSON configuration file'
    )
    
    parser.add_argument(
        '--output',
        choices=['console', 'json'],
        default='console',
        help='Output format (default: console)'
    )
    
    parser.add_argument(
        '--no-verify-ssl',
        action='store_true',
        help='Disable SSL certificate verification (not recommended for production)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    return parser.parse_args()


def main():
    """Main execution function."""
    args = parse_arguments()
    
    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Load configuration
        config = Config(config_file=args.config)
        
        # Override SSL verification if specified
        if args.no_verify_ssl:
            config.verify_ssl = False
        
        # Initialize API client
        client = IBMStorageVirtualizeClient(config)
        
        # Authenticate
        OutputFormatter.print_header("IBM STORAGE VIRTUALIZE REPLICATION MONITOR")
        print(f"\nConnecting to: {config.host}")
        
        if not client.authenticate():
            OutputFormatter.print_colored("✗ Authentication failed", 'red', bold=True)
            return 1
        
        OutputFormatter.print_colored("✓ Authentication successful", 'green')
        
        # Get replication relationships
        relationships = client.get_rc_relationships()
        
        if relationships is None:
            OutputFormatter.print_colored("✗ Failed to retrieve replication relationships", 'red', bold=True)
            return 1
        
        if len(relationships) == 0:
            OutputFormatter.print_colored("⚠ No replication relationships found", 'yellow')
            return 0
        
        # Analyze status
        summary = StatusAnalyzer.analyze_relationships(relationships)
        
        # Output results
        if args.output == 'json':
            # JSON output
            output_data = {
                'timestamp': datetime.utcnow().isoformat(),
                'host': config.host,
                'summary': {
                    'total': summary['total'],
                    'normal': summary['normal'],
                    'warning': summary['warning'],
                    'error': summary['error']
                },
                'relationships': [
                    {
                        'name': d['name'],
                        'state': d['state'],
                        'category': d['category'],
                        'primary_vdisk': d['primary_vdisk'],
                        'secondary_vdisk': d['secondary_vdisk']
                    }
                    for d in summary['details']
                ]
            }
            print(json.dumps(output_data, indent=2))
        else:
            # Console output
            OutputFormatter.print_header("REPLICATION RELATIONSHIPS")
            
            # Print all relationships
            for detail in summary['details']:
                OutputFormatter.print_relationship(detail)
            
            # Print summary
            OutputFormatter.print_summary(summary)
            
            # Print warnings if any
            if summary['warning'] > 0 or summary['error'] > 0:
                OutputFormatter.print_header("ATTENTION REQUIRED")
                
                for detail in summary['details']:
                    if detail['category'] in ['warning', 'error']:
                        OutputFormatter.print_relationship(detail)
        
        # Close client
        client.close()
        
        # Return exit code based on status
        if summary['error'] > 0:
            return 2  # Errors found
        elif summary['warning'] > 0:
            return 1  # Warnings found
        else:
            return 0  # All OK
        
    except ValueError as e:
        OutputFormatter.print_colored(f"✗ Configuration error: {e}", 'red', bold=True)
        return 1
    except KeyboardInterrupt:
        OutputFormatter.print_colored("\n✗ Interrupted by user", 'yellow')
        return 130
    except Exception as e:
        logger.exception("Unexpected error occurred")
        OutputFormatter.print_colored(f"✗ Unexpected error: {e}", 'red', bold=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())

# Made with Bob
