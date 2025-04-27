#!/usr/bin/env python3
# /// script
# dependencies = [
#   "requests",
#   "tomli",
#   "colorama",
# ]
# ///

"""
modchecker.py - Minecraft Mod Version and Slug Checker/Updater

Checks and updates Minecraft mod versions and IDs using the Modrinth API.
"""

import sys
import argparse
from typing import Dict, List, Optional, Any, Tuple, Callable

import requests
import tomli
from colorama import init, Fore, Style

# Initialize colorama for colored terminal output
init()

# --- Constants ---
MODRINTH_API = "https://api.modrinth.com/v2"
USER_AGENT = "github/LunchChecker/1.0.0 (Minecraft Mod Version Checker)"

# Global debug flag
DEBUG = False

def debug_log(message: str) -> None:
    """Print a debug message if debug mode is enabled."""
    if DEBUG:
        print(f"DEBUG: {message}")


# --- Utility Classes ---
class TomlHandler:
    """Handles reading and updating TOML configuration files."""

    @staticmethod
    def load_config(file_path: str) -> Dict[str, Any]:
        """Load and parse a TOML configuration file."""
        try:
            with open(file_path, "rb") as f:
                return tomli.load(f)
        except (IOError, tomli.TOMLDecodeError) as e:
            print(f"Error loading {file_path}: {e}", file=sys.stderr)
            sys.exit(1)

    @staticmethod
    def _read_file_lines(file_path: str) -> Optional[List[str]]:
        """Helper to read file lines with error handling."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.readlines()
        except IOError as e:
            print(f"Error reading {file_path}: {e}", file=sys.stderr)
            return None

    @staticmethod
    def _write_file_lines(file_path: str, lines: List[str]) -> bool:
        """Helper to write file lines with error handling."""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            return True
        except IOError as e:
            print(f"Error writing {file_path}: {e}", file=sys.stderr)
            return False

    def _update_toml_field(
        self,
        file_path: str,
        find_predicate: Callable[[str], bool],
        update_predicate: Callable[[str], bool],
        update_func: Callable[[str], str],
    ) -> bool:
        """Generic method to find and update fields in TOML files.

        Args:
            file_path: Path to TOML file
            find_predicate: Function that returns True when the target section is found
            update_predicate: Function that returns True when the line to update is found
            update_func: Function that receives the line and returns the updated line
        """
        lines = self._read_file_lines(file_path)
        if not lines:
            debug_log(f"Failed to read file lines from {file_path}")
            return False

        found_target = False
        updated = False
        debug_counter = 0

        for i, line in enumerate(lines):
            line_stripped = line.strip()

            # Debug print for target lines
            if debug_counter < 20:  # Limit debug output
                if find_predicate(line_stripped):
                    debug_log(f"Found target at line {i}: '{line_stripped}'")
                if update_predicate(line_stripped):
                    debug_log(f"Found update candidate at line {i}: '{line_stripped}'")
                debug_counter += 1

            if find_predicate(line_stripped):
                found_target = True
                debug_log(f"Set found_target = True at line {i}")
                continue

            if found_target and update_predicate(line_stripped):
                old_line = lines[i]
                lines[i] = update_func(line)
                updated = True
                debug_log(f"Updated line {i} from '{old_line.strip()}' to '{lines[i].strip()}'")
                break

            # Reset search when we hit a section boundary
            if found_target and line_stripped.startswith("[["):
                debug_log(f"Reset found_target at line {i} due to section boundary: '{line_stripped}'")
                found_target = False

        if not updated:
            debug_log("No matching line was found to update")

        result = updated and self._write_file_lines(file_path, lines)
        debug_log(f"Final result of update operation: {result}")
        return result

    def update_version(self, file_path: str, mod_id: str, new_version: str) -> bool:
        """Update a mod's version in the TOML file."""
        lines = self._read_file_lines(file_path)
        if not lines:
            debug_log(f"Failed to read file lines from {file_path}")
            return False

        updated = False
        in_mod_section = False

        debug_log(f"Looking for mod with ID '{mod_id}' to update version to {new_version}")

        for i, line in enumerate(lines):
            line_stripped = line.strip()

            # Check for the start of a mod section
            if line_stripped == "[[mods]]":
                in_mod_section = True
                debug_log(f"Found mod section at line {i}")
                continue

            # If we're in a mod section, look for the correct mod ID
            if in_mod_section and line_stripped == f'id = "{mod_id}"':
                debug_log(f"Found target mod with ID '{mod_id}' at line {i}")

                # Look for the version line in the next few lines
                for j in range(i + 1, min(i + 5, len(lines))):  # Check next few lines
                    version_line = lines[j].strip()
                    if version_line.startswith("version = "):
                        # Found the version line, update it
                        old_line = lines[j]
                        indent = lines[j][: lines[j].index("version")]
                        lines[j] = f'{indent}version = "{new_version}"\n'
                        updated = True
                        debug_log(f"Updated version at line {j} from '{old_line.strip()}' to '{lines[j].strip()}'")
                        break

                # If we found the right mod ID, no need to continue checking other mods
                break

            # Reset when we hit a new section (but not at the initial [[mods]] line)
            if in_mod_section and i > 0 and (line_stripped.startswith("[[") and line_stripped != "[[mods]]"):
                in_mod_section = False
                debug_log(f"End of mod section at line {i}")

        if not updated:
            debug_log(f"Failed to find version line for mod '{mod_id}'")

        # Only write to the file if we actually made a change
        if updated:
            result = self._write_file_lines(file_path, lines)
            debug_log(f"File write result: {result}")
            return result
        return False

    def update_id_to_slug(self, file_path: str, mod_id: str, slug: str) -> bool:
        """Update a mod's ID to its slug in the TOML file."""
        lines = self._read_file_lines(file_path)
        if not lines:
            return False

        updated = False

        for i, line in enumerate(lines):
            line_stripped = line.strip()

            if line_stripped == f'id = "{mod_id}"':
                indent = line[: line.index("id")]
                lines[i] = f'{indent}id = "{slug}"\n'
                updated = True
                break

        return updated and self._write_file_lines(file_path, lines)


class ModrinthClient:
    """Client for interacting with the Modrinth API."""

    def __init__(self, api_base: str = MODRINTH_API, user_agent: str = USER_AGENT):
        self.api_base = api_base
        self.headers = {"User-Agent": user_agent}

    def get_mod_info(self, mod_id: str) -> Optional[Dict[str, Any]]:
        """Fetch mod information from Modrinth API."""
        try:
            response = requests.get(f"{self.api_base}/project/{mod_id}", headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching mod {mod_id}: {e}", file=sys.stderr)
            return None

    def get_mod_versions(self, mod_id: str, mc_version: str, mod_loader: str) -> List[Dict[str, Any]]:
        """Fetch and filter mod versions from Modrinth API."""
        try:
            response = requests.get(f"{self.api_base}/project/{mod_id}/version", headers=self.headers)
            response.raise_for_status()
            versions = response.json()

            # Filter versions by Minecraft version and mod loader
            filtered_versions = self._filter_versions(versions, mc_version, mod_loader)

            # Sort versions by publish date (newest first)
            filtered_versions.sort(key=lambda x: x.get("date_published", ""), reverse=True)
            return filtered_versions
        except requests.RequestException as e:
            print(f"Error fetching versions for mod {mod_id}: {e}", file=sys.stderr)
            return []

    @staticmethod
    def _filter_versions(versions: List[Dict[str, Any]], mc_version: str, mod_loader: str) -> List[Dict[str, Any]]:
        """Filter versions by Minecraft version and mod loader."""
        return [
            v
            for v in versions
            if (
                mod_loader in [loader.lower() for loader in v.get("loaders", [])]
                and mc_version in v.get("game_versions", [])
            )
        ]


class ModManager:
    """Manager for handling Minecraft mods and their configuration."""

    def __init__(self, config_path: str, mc_version: str, mod_loader: str):
        self.config_path = config_path
        self.mc_version = mc_version
        self.mod_loader = mod_loader
        self.client = ModrinthClient()
        self.toml_handler = TomlHandler()
        self.config = self.toml_handler.load_config(config_path)

    # --- User Interaction ---
    @staticmethod
    def prompt_yes_no(question: str) -> bool:
        """Prompt the user for a yes/no answer."""
        while True:
            answer = input(f"{question} (y/n): ").lower().strip()
            if answer in ["y", "yes"]:
                return True
            if answer in ["n", "no"]:
                return False
            print("Please answer 'y' or 'n'")

    # --- Version Comparison and Formatting ---
    @staticmethod
    def get_version_color(current_ver: str, latest_ver: str) -> str:
        """Determine the color to use for version display based on version difference significance."""
        current_base = current_ver.split("+")[0].split("-")[0]
        latest_base = latest_ver.split("+")[0].split("-")[0]
        try:
            current_parts = current_base.split(".")
            latest_parts = latest_base.split(".")
            for i in range(min(len(current_parts), len(latest_parts))):
                if latest_parts[i] != current_parts[i]:
                    if i == 0:  # Major version change
                        return Fore.RED
                    elif i == 1:  # Minor version change
                        return Fore.YELLOW
                    else:  # Patch version change
                        return Fore.GREEN
        except (ValueError, IndexError):
            pass
        return Fore.GREEN

    @staticmethod
    def format_changelog(changelog: str, width: int = 70) -> str:
        """Format changelog text for display with line wrapping."""
        if not changelog:
            return ""

        # Split into lines and filter empty ones
        lines = [line.strip() for line in changelog.split("\n") if line.strip()]
        formatted_lines = []

        for line in lines:
            if len(line) > width:
                # Word wrap long lines
                wrapped_lines = ModManager._wrap_line(line, width)
                formatted_lines.extend(wrapped_lines)
            else:
                formatted_lines.append(line)

        # Add indentation to each line
        return "\n".join(f"  {line}" for line in formatted_lines)

    @staticmethod
    def _wrap_line(line: str, width: int) -> List[str]:
        """Wrap a single line to the specified width."""
        wrapped_lines = []
        current_line = ""

        for word in line.split():
            if len(current_line) + len(word) + 1 <= width:
                current_line += f" {word}" if current_line else word
            else:
                wrapped_lines.append(current_line)
                current_line = word

        if current_line:
            wrapped_lines.append(current_line)

        return wrapped_lines

    # --- Mod Status and Update Logic ---
    def display_mod_status(
        self,
        mod_info: Dict[str, Any],
        versions: List[Dict[str, Any]],
        current_version_id: str,
        update_mode: bool = False,
    ) -> Tuple[bool, int]:
        """Display the status of a mod and prompt for updates if in update mode."""
        mod_id = mod_info["id"]
        mod_title = mod_info["title"]

        # Display basic mod info
        print(f"Mod: {mod_title} ({mod_id})")
        self._display_slug_info(mod_info, mod_id)

        if not versions:
            print("Status: No compatible version found")
            print("-" * 80)
            return False, 0

        # Get version information
        latest_version = versions[0]
        current_version = next((v for v in versions if v["id"] == current_version_id), None)

        # Display version information
        self._display_version_info(current_version, current_version_id, latest_version)

        # Check if update is needed
        needs_update = not current_version or latest_version["id"] != current_version_id
        updates_performed = 0

        if needs_update:
            updates_performed = self._handle_update_needed(
                current_version,
                current_version_id,
                latest_version,
                mod_id,
                mod_title,
                update_mode,
            )
        else:
            print("Status: Up to date")

        print("-" * 80)
        return needs_update, updates_performed

    def _display_slug_info(self, mod_info: Dict[str, Any], mod_id: str) -> None:
        """Display slug information if different from mod ID."""
        if "slug" in mod_info and mod_info["slug"] != mod_id:
            print(f"Slug: {Fore.CYAN}{mod_info['slug']}{Style.RESET_ALL}")

    def _display_version_info(
        self,
        current_version: Optional[Dict[str, Any]],
        current_version_id: str,
        latest_version: Dict[str, Any],
    ) -> None:
        """Display current and latest version information."""
        if current_version:
            version_type = current_version.get("version_type", "release")
            print(f"Current Version: {current_version['version_number']} ({version_type})")
        else:
            print(f"Current Version: {current_version_id} (version info not found)")

        version_type = latest_version.get("version_type", "release")
        print(f"Latest Version: {latest_version['version_number']} ({version_type})")

    def _handle_update_needed(
        self,
        current_version: Optional[Dict[str, Any]],
        current_version_id: str,
        latest_version: Dict[str, Any],
        mod_id: str,
        mod_title: str,
        update_mode: bool,
    ) -> int:
        """Handle the case when a mod needs an update. Returns number of updates performed."""
        # Determine color based on version difference
        color = Fore.GREEN
        if current_version:
            color = self.get_version_color(
                current_version.get("version_number", "0.0.0"),
                latest_version.get("version_number", "0.0.0"),
            )

        # Display update information
        date = latest_version.get("date_published", "").split("T")[0]
        print(f"Status: {color}Update Available!{Style.RESET_ALL} (published {date})")

        # Display changelog if available
        changelog = latest_version.get("changelog", "").strip()
        if changelog:
            print("\nChangelog:")
            print(self.format_changelog(changelog))

        # Prompt for update if in update mode
        if update_mode:
            return self._perform_update(mod_id, mod_title, current_version_id, latest_version, color)
        return 0

    def _perform_update(
        self,
        mod_id: str,
        mod_title: str,
        current_version_id: str,
        latest_version: Dict[str, Any],
        color: str,
    ) -> int:
        """Perform the update if user confirms. Returns 1 if updated, 0 otherwise."""
        if self.prompt_yes_no(f"Do you want to update this mod to version {latest_version['version_number']}?"):
            print(f"Updating version from {current_version_id} to {color}{latest_version['id']}{Style.RESET_ALL}")

            # Get mod info to find the slug
            mod_info = self.client.get_mod_info(mod_id)
            if not mod_info or "slug" not in mod_info:
                print(f"Error: Could not find slug for mod {mod_id}")
                return 0

            mod_slug = mod_info["slug"]
            debug_log(f"Using slug '{mod_slug}' to update mod with ID '{mod_id}'")

            if self.toml_handler.update_version(self.config_path, mod_slug, latest_version["id"]):
                print(f"Successfully updated {mod_title}!")
                return 1
            else:
                print(f"Failed to update version for {mod_title}")
        else:
            print("Skipping version update.")
        return 0

    def update_slugs(self) -> int:
        """Update mod IDs to slugs without changing versions. Returns the number of slugs updated."""
        slugs_updated = 0
        for mod in self.config.get("mods", []):
            # Skip non-Modrinth mods
            if mod.get("type") != "modrinth":
                continue

            mod_id = mod.get("id")
            if not mod_id:
                continue

            # Get mod info from Modrinth
            mod_info = self.client.get_mod_info(mod_id)
            if not mod_info:
                continue

            # Skip if no slug or slug is same as ID
            if "slug" not in mod_info or mod_info["slug"] == mod_id:
                continue

            # Display mod and slug info
            print(f"\nMod: {mod_info['title']} ({mod_id})")
            print(f"Slug: {Fore.CYAN}{mod_info['slug']}{Style.RESET_ALL}")

            # Prompt for slug update
            if self._should_update_to_slug(mod_id, mod_info["slug"]):
                print(f"Updating ID from {mod_id} to {Fore.CYAN}{mod_info['slug']}{Style.RESET_ALL}")
                if self.toml_handler.update_id_to_slug(self.config_path, mod_id, mod_info["slug"]):
                    slugs_updated += 1
            else:
                print("Keeping current mod ID.")

        return slugs_updated

    def _should_update_to_slug(self, mod_id: str, slug: str) -> bool:
        """Check if the mod ID should be updated to the slug."""
        return self.prompt_yes_no(f"Do you want to use the readable slug '{slug}' instead of ID '{mod_id}'?")

    def check_mods(self, update_mode: bool = False, specific_mods: Optional[List[str]] = None) -> Tuple[List[str], int]:
        """Check mods for updates and optionally update them."""
        needs_update = []
        updates_performed = 0

        for mod in self.config.get("mods", []):
            # Skip non-Modrinth mods
            if mod.get("type") != "modrinth":
                continue

            mod_id = mod.get("id")
            current_version_id = mod.get("version")

            # Skip mods without ID or version
            if not mod_id or not current_version_id:
                continue

            # Skip mods not in the specific list if provided
            if specific_mods and mod_id not in specific_mods:
                continue

            # Get mod info and versions
            mod_info = self.client.get_mod_info(mod_id)
            if not mod_info:
                continue

            versions = self.client.get_mod_versions(mod_id, self.mc_version, self.mod_loader)

            # Display mod status and handle updates
            mod_needs_update, mod_updated = self.display_mod_status(mod_info, versions, current_version_id, update_mode)

            if mod_needs_update:
                needs_update.append(mod_id)
            updates_performed += mod_updated

        return needs_update, updates_performed


# --- Argument Parsing and Main Entrypoint ---
def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Check and update Minecraft mod versions and IDs.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--update",
        nargs="*",
        metavar="MOD_ID",
        help="Update specified mods to latest versions (or all if no mods specified)",
    )
    group.add_argument("--slugs", action="store_true", help="Convert mod IDs to readable slugs")
    parser.add_argument(
        "--file",
        default="server.toml",
        help="Server configuration file path (default: server.toml)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode for detailed output",
    )
    return parser.parse_args()


def main():
    """Main entry point for the script."""
    args = parse_args()
    global DEBUG
    DEBUG = args.debug
    file_path = args.file

    # Initialize and load config
    toml_handler = TomlHandler()
    config = toml_handler.load_config(file_path)

    # Get Minecraft version and mod loader from config
    mc_version = config.get("mc_version")
    mod_loader = config.get("jar", {}).get("type", "fabric").lower()

    if not mc_version:
        print(f"Error: Could not find Minecraft version in {file_path}", file=sys.stderr)
        sys.exit(1)

    # Initialize mod manager
    manager = ModManager(file_path, mc_version, mod_loader)

    # Handle slug conversion mode
    if args.slugs:
        handle_slug_conversion(manager, file_path)
        return

    # Handle regular mod checking/updating
    handle_mod_updates(manager, config, mc_version, mod_loader, file_path, args)


def handle_slug_conversion(manager: ModManager, file_path: str) -> None:
    """Handle the slug conversion mode."""
    print(f"Checking mod IDs for slug conversion in {file_path}...")
    slugs_updated = manager.update_slugs()
    print(
        f"\n{'Successfully updated' if slugs_updated else 'No'} "
        f"{slugs_updated} mod ID(s) {'to readable slugs!' if slugs_updated else 'were updated.'}"
    )


def handle_mod_updates(
    manager: ModManager,
    config: Dict[str, Any],
    mc_version: str,
    mod_loader: str,
    file_path: str,
    args: argparse.Namespace,
) -> None:
    """Handle checking and updating mods."""
    mods = config.get("mods", [])
    print(f"Checking {len(mods)} mods for Minecraft {mc_version} ({mod_loader})...")
    print("\nMod Status:")
    print("-" * 80)

    # Determine update mode and specific mods
    update_mode = args.update is not None
    specific_mods = args.update if update_mode and args.update else None

    # Check mods for updates
    needs_update, updates_performed = manager.check_mods(update_mode, specific_mods)

    # Display summary
    display_update_summary(update_mode, updates_performed, file_path, needs_update)


def display_update_summary(update_mode: bool, updates_performed: int, file_path: str, needs_update: List[str]) -> None:
    """Display a summary of the update check/perform operation."""
    if update_mode:
        if updates_performed > 0:
            print(f"\nSuccessfully updated {updates_performed} mod version(s) in {file_path}!")
            print("Please restart your server for the changes to take effect.")
        else:
            print("\nNo updates were made to the server configuration.")
    else:
        update_count = len(needs_update)
        if update_count > 0:
            print(f"\nFound {update_count} mod(s) that need updating.")
            print("Run with --update to update all mods or --update MOD_ID to update specific mods.")
        else:
            print("\nAll mods are up to date!")


if __name__ == "__main__":
    main()
