#!/usr/bin/env python3
import argparse
import os
import sys
import subprocess
import shutil
import stat
import getpass

# References:
# * https://chatgpt.com/share/67ccb427-f7d8-8007-8248-eb5ac5a78b04
# * https://x.com/i/grok/share/0iFSdGEY0wDtYgKTKlxXGzGqz
# * https://www.phind.com/search/cm80kjc4r00002v6sb3lxmrp5

# Assumptions:
# Script should depend on as little and as standard python libraries
# as possible to be as much as possible Linux portable.
# Having said that should rather rely on linux tools and invoke them.
# Assume ArchLinux and Ubuntu as main users.
#
# Script should auto detect system based on /etc/os-release,
# and offer user to overwrite this with a flag.
# --os {arch|ubuntu|auto} - select os release, by default auto will be based
# on /etc/os-release to determine if NAME="Arch Linux" or NAME="Ubuntu"
#
# Offer command line options to:
#
# Run this regular tasks script:
# * {--run|--dry-run} folder_or_script_or_command
#    will identify if provided parameter is a "file" or "folder" or sth else,
#    and will: run script if file, run all scripts in folder if folder, or
#    treat parameter as command to be executed.
# * shortflags: -n|--dry-run and -f|--run
# * -v|--verbose
#
# And install it to be run by systemd timers:
# * --dependencies {check|script}
#    * `check` - list which required commands are installed and which are not
#    * `script` - suggest installation commands for missing ones
# * --configs {create|edit-timer|edit-service|delete}
#    * `create` - will make service and timer files under
#                 ~/.config/systemd/user/
#        * `create` requires parameter --run-arg (the argument that will be
#          provided to --run when the timer is invoking this script)
#    * `edit-timer|edit-service` will open with $EDITOR the timer or service
#      file for user to edit
#    * `delete` - delete created timer and service file
#
# * --install-systemd-timer {daily|hourly}
# * --Persistent {true|false} - by default "true"
#    - if "true", it adds 'Persistent=true' to the [Timer] section
#      ensuring the script is run after boot if the scheduled time was missed
#      while the system was off
# * --OnCalendar - sets [Timer] OnCalendar; by default '*-*-* 14:00:00'
#    (daily at 2:00 PM local time). (e.g., '09:00:00' for 9:00 AM)
# * --Description [Unit] Description
#    by default "Daily User Run of <script_path>"
#
# * {--status|--enable_and_start|--disable_and_stop}
#   exclusive options for adding or removing the timer
#
# The script should handle these tasks to make systemd user-level timer
# usage convenient.

def detect_os(selected_os: str = "auto") -> str:
    """
    Detect operating system by reading /etc/os-release if selected_os='auto'.
    Otherwise return the forced string if it's 'arch' or 'ubuntu'.
    """
    if selected_os in ["arch", "ubuntu"]:
        return selected_os

    # If selected_os is 'auto', we try to parse /etc/os-release
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            content = f.read().lower()
            if "arch linux" in content:
                return "arch"
            elif "ubuntu" in content:
                return "ubuntu"
            else:
                return "unknown"
    except FileNotFoundError:
        return "unknown"


def is_executable_file(path: str) -> bool:
    """Check if path is a file and is marked executable."""
    if not os.path.isfile(path):
        return False
    st = os.stat(path)
    return bool(st.st_mode & stat.S_IXUSR)


def run_commands(args, run_arg: str, is_dry_run: bool) -> None:
    """
    Identify if run_arg is a folder or a file or other,
    then run or dry-run items accordingly.
    """
    if os.path.isdir(run_arg):
        # Run all scripts in folder if folder
        for item in sorted(os.listdir(run_arg)):
            full_path = os.path.join(run_arg, item)
            if os.path.isfile(full_path) and is_executable_file(full_path):
                if args.verbose:
                    print(f"Found executable script: {full_path}")
                if is_dry_run:
                    print(f"[DRYRUN] Would run: '{full_path}'")
                else:
                    print(f"Running: '{full_path}'")
                    subprocess.run([full_path], check=False)
    elif os.path.isfile(run_arg):
        # If it's a file, run that script
        if is_executable_file(run_arg):
            if is_dry_run:
                print(f"[DRYRUN] Would run file: '{run_arg}'")
            else:
                print(f"Running file: '{run_arg}'")
                subprocess.run([run_arg], check=False)
        else:
            if args.verbose:
                print(f"'{run_arg}' is a file but probably not executable. "
                      "Attempting to run in shell.")
            if is_dry_run:
                print(f"[DRYRUN] Would run via shell: '{run_arg}'")
            else:
                subprocess.run(["bash", run_arg], check=False)
    else:
        # If unknown, treat as command
        if is_dry_run:
            print(f"[DRYRUN] Would run command: {run_arg}")
        else:
            subprocess.run(run_arg, shell=True, check=False)


def check_dependencies(verbose: bool) -> None:
    """
    Check presence of certain commands (like systemctl, bash, etc.).
    For demonstration, let's check systemctl, bash, and nano or vi.
    """
    commands_to_check = ["systemctl", "bash", "nano"]
    for cmd in commands_to_check:
        cmd_path = shutil.which(cmd)
        if cmd_path:
            print(f"[OK]   {cmd} found at {cmd_path}")
        else:
            print(f"[MISS] {cmd} NOT found")
    if verbose:
        print("Dependency check finished.")


def suggest_install_script(verbose: bool) -> None:
    """
    Suggest installation commands for missing tools.
    We'll do a minimal attempt: if on arch, we suggest pacman,
    if on ubuntu, we suggest apt-get, otherwise print generic message.
    """
    user_os = detect_os("auto")
    missing_cmds = []
    for cmd in ["systemctl", "bash", "nano"]:
        if not shutil.which(cmd):
            missing_cmds.append(cmd)

    if not missing_cmds:
        print("All essential commands appear to be installed.")
        return

    if user_os == "arch":
        pkgmgr = "sudo pacman -S"
    elif user_os == "ubuntu":
        pkgmgr = "sudo apt-get install"
    else:
        pkgmgr = "<your_package_manager_install_command>"

    print("Suggested installation commands (based on detected OS):")
    for cmd in missing_cmds:
        print(f"  {pkgmgr} {cmd}")

    if verbose:
        print("Suggested install script generation completed.")


def create_service_and_timer(args):
    """
    Create service and timer files in ~/.config/systemd/user/
    using the provided run_arg, OnCalendar, etc.
    """
    home = os.path.expanduser("~")
    systemd_user_dir = os.path.join(
        home, ".config", "systemd", "user"
    )
    os.makedirs(systemd_user_dir, exist_ok=True)

    script_path = os.path.abspath(__file__)
    default_description = f"Daily User Run of {script_path}"
    description = args.Description if args.Description else default_description
    on_calendar = args.OnCalendar if args.OnCalendar else "*-*-* 14:00:00"

    service_file = os.path.join(systemd_user_dir, "daily_by_hostname.service")
    timer_file = os.path.join(systemd_user_dir, "daily_by_hostname.timer")

    # Build service content
    service_content = [
        "[Unit]",
        f"Description={description}",
        "After=network.target",
        "",
        "[Service]",
        "Type=oneshot",
        f"ExecStart=/usr/bin/env python3 {script_path} --run \"{args.run_arg}\"",
        "",
        "# End of service file\n"
    ]
    # Build timer content
    persistent_value = "true" if args.Persistent is None else args.Persistent
    if persistent_value not in ["true", "false"]:
        persistent_value = "true"
    timer_content = [
        "[Unit]",
        f"Description=Timer for: {description}",
        "",
        "[Timer]",
        f"OnCalendar={on_calendar}",
        f"Persistent={persistent_value}",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
        "# End of timer file\n"
    ]

    # Write them
    with open(service_file, "w", encoding="utf-8") as sf:
        sf.write("\n".join(service_content))
    with open(timer_file, "w", encoding="utf-8") as tf:
        tf.write("\n".join(timer_content))

    print(f"Created service file: {service_file}")
    print(f"Created timer file:   {timer_file}")
    print("You can now enable and start the timer with:")
    print("  $ systemctl --user enable daily_by_hostname.timer")
    print("  $ systemctl --user start daily_by_hostname.timer")


def edit_file_in_editor(file_path: str):
    """
    Open the given file in $EDITOR or fallback to nano, vi.
    """
    editor = os.environ.get("EDITOR", "")
    if not editor:
        # fallback
        for candidate in ["nano", "vi"]:
            if shutil.which(candidate):
                editor = candidate
                break
        if not editor:
            print("No suitable editor found! Please set $EDITOR.")
            return
    subprocess.run([editor, file_path], check=False)


def handle_configs(args):
    """
    Manage creation, editing, or deletion of service/timer files.
    """
    home = os.path.expanduser("~")
    systemd_user_dir = os.path.join(home, ".config", "systemd", "user")
    service_file = os.path.join(systemd_user_dir, "daily_by_hostname.service")
    timer_file = os.path.join(systemd_user_dir, "daily_by_hostname.timer")

    if args.configs == "paths":
        print(f"{service_file}")
        print(f"{timer_file}")
        return
    elif args.configs == "create":
        if not args.run_arg:
            print("Error: --configs create requires --run-arg")
            sys.exit(1)
        create_service_and_timer(args)

    elif args.configs == "edit-service":
        if not os.path.exists(service_file):
            print(f"Service file not found: {service_file}")
            return
        edit_file_in_editor(service_file)

    elif args.configs == "edit-timer":
        if not os.path.exists(timer_file):
            print(f"Timer file not found: {timer_file}")
            return
        edit_file_in_editor(timer_file)

    elif args.configs == "delete":
        if os.path.exists(service_file):
            os.remove(service_file)
            print(f"Deleted service file: {service_file}")
        if os.path.exists(timer_file):
            os.remove(timer_file)
            print(f"Deleted timer file: {timer_file}")


def handle_systemd_install(args):
    """
    If user wants to install a systemd timer (daily or hourly) in some special manner,
    we can do that. For now, let's just note the argument.
    """
    print(f"You requested to install a systemd timer: {args.install_systemd_timer}")
    print("But the recommended way is to run: --configs create, then enable and start.")


def handle_systemd_timer_actions(args):
    """
    Handle --status, --enable_and_start, --disable_and_stop, or --logs for the user-level timer.
    """
    user_cmd = None
    if args.status:
        user_cmd = ["systemctl", "--user", "status", "daily_by_hostname.timer"]
    elif args.enable_and_start:
        user_cmd = ["systemctl", "--user", "enable", "--now", "daily_by_hostname.timer"]
    elif args.disable_and_stop:
        user_cmd = ["systemctl", "--user", "disable", "--now", "daily_by_hostname.timer"]
    elif args.logs:
        user_cmd = ["journalctl", "--user-unit", "daily_by_hostname.service", "--since", "today"]
    if user_cmd:
        print(f"Running: {' '.join(user_cmd)}")
        subprocess.run(user_cmd, check=False)


def main():
    parser = argparse.ArgumentParser(
        description="Daily script by hostname that can be run by systemd timer."
    )
    parser.add_argument("--os", default="auto",
                        choices=["auto", "arch", "ubuntu"],
                        help="Select OS or auto-detect from /etc/os-release")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-f", "--run", dest="run_arg",
                       help="Run tasks in the given file/directory or command. RUN_ARG: directory with scripts to run daily, or script or command.")
    group.add_argument("-n", "--dry-run", dest="dry_run_arg",
                       help="Dry-run tasks in the given file/directory or command. See RUN_ARG for more details.")

    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose output")

    parser.add_argument("--dependencies", choices=["check", "script"],
                        help="Manage or show required dependencies")

    parser.add_argument("--configs", choices=["create", "paths", "edit-timer", "edit-service", "delete"],
                        help="Create, edit or delete systemd service/timer files")

    parser.add_argument("--run-arg", default=None,
                        help="Required argument for the script if used with configs create. RUN_ARG: directory with scripts to run daily, or script or command.")

    parser.add_argument("--install-systemd-timer", choices=["daily", "hourly"],
                        help="Install timer in a daily or hourly manner (placeholder)")

    parser.add_argument("--Persistent", default=None,
                        help="Set Persistent=true/false in the Timer file (default true)")

    parser.add_argument("--OnCalendar", default=None,
                        help="Set [Timer] OnCalendar= (default '*-*-* 14:00:00')")

    parser.add_argument("--Description", default=None,
                        help="Set [Unit] Description= for the service (default uses script path)")

    # systemd timer sub-commands
    parser.add_argument("--status", action="store_true",
                        help="Show systemd user timer status")
    parser.add_argument("--enable_and_start", action="store_true",
                        help="Enable and start systemd user timer")
    parser.add_argument("--disable_and_stop", action="store_true",
                        help="Disable and stop systemd user timer")
    parser.add_argument("--logs", action="store_true",
                        help="Show logs for the systemd user timer service")

    args = parser.parse_args()

    # OS detection
    used_os = detect_os(args.os)
    if args.verbose:
        print(f"Detected/Selected OS: {used_os}")

    # handle dependencies if requested
    if args.dependencies == "check":
        check_dependencies(args.verbose)
        sys.exit(0)
    elif args.dependencies == "script":
        suggest_install_script(args.verbose)
        sys.exit(0)

    # handle configs if requested
    if args.configs:
        handle_configs(args)
        # we carry on after config creation etc, or we can just exit:
        sys.exit(0)

    # handle install-systemd-timer
    if args.install_systemd_timer:
        handle_systemd_install(args)
        sys.exit(0)

    # handle systemd timer actions
    if args.status or args.enable_and_start or args.disable_and_stop or args.logs:
        handle_systemd_timer_actions(args)
        sys.exit(0)

    # handle run or dry-run
    if args.run_arg:
        run_commands(args, args.run_arg, is_dry_run=False)
    elif args.dry_run_arg:
        run_commands(args, args.dry_run_arg, is_dry_run=True)
    else:
        if args.verbose:
            print("No run or dry-run argument provided. Doing nothing.")

if __name__ == "__main__":
    main()
