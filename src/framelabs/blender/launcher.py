"""Blender executable discovery and launching for FrameLabs.

Feature 10's "Launch Blender" step. Pure logic -- no Qt. Finds a real
Blender install (searching common per-OS locations, or a manually
-located path remembered in Config), and launches it running the
generator script produced from a BlenderManifest.

Per the Developer Handbook, Blender integration is isolated to this
package -- the core app never imports bpy.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from framelabs.core.config import Config
from framelabs.core.logger import get_logger

logger = get_logger("blender.launcher")

# Common install locations, checked in order, per OS. Not exhaustive --
# a user with a non-default install location is expected to use "Locate
# Blender Executable" instead, which remembers the chosen path in Config
# so this search is only ever needed once per machine.
_WINDOWS_SEARCH_PATHS = (
    r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
)
_MACOS_SEARCH_PATHS = ("/Applications/Blender.app/Contents/MacOS/Blender",)
_LINUX_SEARCH_PATHS = (
    "/usr/bin/blender",
    "/usr/local/bin/blender",
    "/snap/bin/blender",
    "/var/lib/flatpak/exports/bin/org.blender.Blender",
)


class BlenderLaunchError(Exception):
    """Raised when no Blender executable can be found, or launching it
    fails."""


class BlenderExecutableNotFoundError(BlenderLaunchError):
    """Raised specifically when neither a remembered path nor the
    per-OS auto-detect search found a real Blender executable.

    A BlenderLaunchError subtype, not a separate exception -- existing
    `except BlenderLaunchError` handling still catches this. Split out
    so callers (e.g. the UI layer) that specifically want to prompt for
    "Locate Blender Executable" (the Feature Spec's named failure case)
    can distinguish that from every other kind of launch failure
    (e.g. Popen itself failing) without parsing the error message.
    """


def _search_paths() -> tuple[str, ...]:
    """Common install paths to check for the current OS."""
    system = platform.system()
    if system == "Windows":
        return _WINDOWS_SEARCH_PATHS
    if system == "Darwin":
        return _MACOS_SEARCH_PATHS
    return _LINUX_SEARCH_PATHS


def auto_detect_executable() -> Path | None:
    """Search common per-OS install locations for a Blender executable.

    Returns:
        The first existing path found, or None if nothing matched --
        the caller should fall back to prompting the user for
        "Locate Blender Executable" per the Feature Spec's failure case.
    """
    for candidate in _search_paths():
        path = Path(candidate)
        if path.is_file():
            return path
    return None


class BlenderLauncher:
    """Resolves a real Blender executable and launches it.

    Tracks the subprocess.Popen of any Blender instance THIS launcher
    itself started, for as long as this object lives (i.e. one app
    session) -- per the deliberate v1 scope decision, we do not attempt
    to detect a Blender instance running outside FrameLabs (no OS-level
    process scanning). See has_running_instance()'s docstring for what
    "reuse" actually means given this.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._process: subprocess.Popen | None = None

    def resolve_executable(self) -> Path:
        """Find a real Blender executable to launch.

        Checks Config's remembered `blender_executable_path` first (if
        set, and the file still exists there), then falls back to
        auto_detect_executable()'s per-OS search.

        Returns:
            A verified, existing path to a Blender executable.

        Raises:
            BlenderLaunchError: If neither the remembered path nor the
                auto-detected search found a real file. The caller
                should show "Locate Blender Executable" (Feature Spec's
                failure case) and call remember_executable() with the
                user's choice.
        """
        remembered = self._config.get("blender_executable_path")
        if remembered:
            path = Path(remembered)
            if path.is_file():
                return path
            logger.warning("Remembered Blender path no longer exists: %s", remembered)

        detected = auto_detect_executable()
        if detected is not None:
            return detected

        raise BlenderExecutableNotFoundError(
            "No Blender executable found. Locate it manually to continue."
        )

    def remember_executable(self, path: Path) -> None:
        """Save a user-located Blender executable to Config, so future
        sessions never need to search or ask again.

        Args:
            path: The executable the user picked via a file dialog.

        Raises:
            BlenderLaunchError: If path isn't a real file.
        """
        if not path.is_file():
            raise BlenderLaunchError(f"Not a real file: {path}")
        self._config.set("blender_executable_path", str(path))
        self._config.save()
        logger.info("Blender executable remembered: %s", path)

    def has_running_instance(self) -> bool:
        """Whether a Blender process THIS launcher started is still
        alive.

        Only ever true if launch() was called earlier in this same app
        session and that process hasn't exited. Per the v1 scope
        decision, this cannot detect a Blender instance the user opened
        by hand, or one from a previous FrameLabs session -- see the
        class docstring.
        """
        return self._process is not None and self._process.poll() is None

    def launch(self, script_path: Path) -> subprocess.Popen:
        """Start Blender, running `script_path` on startup via --python.

        Always starts a genuinely new OS process. There is no supported
        way to hand a new --python script to an already-running Blender
        window from the outside -- Blender has no built-in remote
        -scripting server, so "reusing" a running instance can only ever
        mean "don't launch a second one on top of it," not "inject this
        new scene into the existing window." See has_running_instance()
        -- the UI layer is expected to use that to implement the Feature
        Spec's Reuse/New Instance prompt, understanding that Reuse
        currently means "leave the existing window alone, don't launch
        anything new."

        Args:
            script_path: Absolute path to the generator script Blender
                should run via --python on startup.

        Returns:
            The started subprocess.Popen, also stored as the tracked
            instance for has_running_instance().

        Raises:
            BlenderLaunchError: If the executable can't be resolved, or
                the process fails to start.
        """
        executable = self.resolve_executable()
        try:
            process = subprocess.Popen([str(executable), "--python", str(script_path)])
        except OSError as exc:
            raise BlenderLaunchError(f"Failed to launch Blender: {exc}") from exc

        self._process = process
        logger.info("Blender launched (pid %d): %s", process.pid, executable)
        return process

    def launch_background(self, script_path: Path) -> subprocess.CompletedProcess:
        """Run `script_path` in Blender's `--background` mode and wait
        for it to finish, rather than opening an interactive window.

        Used for "Export .blend" (see scene_builder.py's generated
        script, which already ends by calling
        `bpy.ops.wm.save_as_mainfile()`) -- headless mode runs the
        script once and exits on its own with no window ever appearing,
        which is exactly what a save-and-quit export needs and an
        interactive launch() doesn't offer. Deliberately blocking
        (subprocess.run, not Popen): the caller is expected to already
        be on a worker thread (see ui/blender_controller.py), and the
        whole point of this call is "wait until the .blend is actually
        written, then report success or failure" -- unlike launch(),
        there is no window left open afterwards to hand control back to.

        Does not touch `self._process`/has_running_instance() -- those
        track the interactive launch() path specifically (an
        Open-in-Blender window a later click might need to know is
        still running); a background export process has already exited
        by the time this returns, so there is nothing left to track.

        Args:
            script_path: Absolute path to the generator script Blender
                should run via --python before exiting.

        Returns:
            The completed subprocess.CompletedProcess. Callers should
            check .returncode -- a non-zero exit means the script raised
            inside Blender (e.g. the scene_builder.py bug described in
            the project hand-off), which this method itself can't detect
            since it never imports bpy.

        Raises:
            BlenderLaunchError: If the executable can't be resolved, or
                the process fails to start at all.
        """
        executable = self.resolve_executable()
        try:
            result = subprocess.run(
                [str(executable), "--background", "--python", str(script_path)],
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise BlenderLaunchError(f"Failed to launch Blender: {exc}") from exc

        logger.info(
            "Blender background export finished (exit %d): %s",
            result.returncode,
            executable,
        )
        return result
