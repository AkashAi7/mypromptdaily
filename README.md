# My Prompt Daily

This workspace contains a Selenium-based Python workflow that:

1. Attaches to an already running Microsoft Edge browser.
2. Opens a new tab to Microsoft 365 Copilot.
3. Switches to a selected Copilot agent.
4. Runs a prompt and waits for the answer.
5. Creates an email in the installed Outlook desktop app without using SMTP.
6. Can be scheduled through Windows Task Scheduler for a daily self-email.

## Requirements

- Windows with Microsoft Edge installed.
- Python 3.11+.
- Outlook desktop installed and signed in.
- An Edge window started with remote debugging enabled.
- An authenticated Microsoft 365 Copilot web session in that Edge profile.

## Install

Target publish/install name:

```powershell
pip install mypromptdaily
```

Once published to a package index, the intended first-run experience is:

1. `pip install mypromptdaily`
2. `mypromptdaily`
3. the CLI detects there is no saved setup yet and immediately launches the setup flow
4. setup writes config and registers Task Scheduler unless the user opts out

For local development:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

That installs the CLI command:

```powershell
mypromptdaily --help
```

If no saved config exists yet, running just `mypromptdaily` will automatically start first-run setup instead of showing the normal menu.

If you only want the dependencies without installing the CLI package:

```powershell
pip install -r requirements.txt
```

## GitHub Setup

If this project is hosted on GitHub, a user can install it directly from the repository without cloning first:

```powershell
python -m pip install "git+https://github.com/<org>/<repo>.git"
```

For development from GitHub:

```powershell
git clone https://github.com/<org>/<repo>.git
cd <repo>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

That gives the user the installed `mypromptdaily` command while keeping the checkout editable.

Create environment settings:

```powershell
Copy-Item .env.example .env
```

Edit `.env` with the prompt, agent, recipient, and preferred email mode.

For slower agents such as `Researcher Agent`, `Analyst Agent`, and others that stream longer responses, you can increase:

- `RESPONSE_TIMEOUT_SECONDS` to allow more total wait time
- `RESPONSE_STABLE_SECONDS` to require the answer text to stop changing before it is emailed

## Start Edge In Debug Mode

Close any Edge instances that use the same profile, then start Edge with a dedicated debug profile:

```powershell
& "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="$env:TEMP\edge-selenium-m365"
```

Sign into Microsoft 365 Copilot in that Edge window before running the workflow.

## CLI Usage

Start the CLI with an interactive menu:

```powershell
mypromptdaily
```

That opens a guided terminal UI with selectable options for:

- Run a one-off prompt
- Set up the daily schedule
- Check scheduled status
- Run the scheduled job now
- Remove the scheduled task

The setup flow now uses dropdown-style agent selection and guided IST time entry.

Run a one-off prompt:

```powershell
mypromptdaily run --agent "Researcher Agent" --prompt "Research the latest Copilot announcements and summarize the business impact." --to "person@example.com" --mode draft
```

For debugging, keep the opened Copilot tab open after the run:

```powershell
mypromptdaily run --agent "Researcher Agent" --prompt "Research the latest Copilot announcements and summarize the business impact." --to "person@example.com" --mode draft --keep-tab-open
```

Equivalent module form:

```powershell
python -m mypromptdaily run --agent "Researcher Agent" --prompt "Research the latest Copilot announcements and summarize the business impact." --to "person@example.com" --mode draft
```

## Time Setup

The daily time is set in IST using 24-hour `HH:MM` format.

- Interactive: `mypromptdaily setup` and answer the `Daily send time in IST, 24-hour HH:MM` prompt.
- Non-interactive: pass `--time-ist`, for example `--time-ist 09:00`.

That time is saved into `daily_schedule_config.json` as `send_time_ist`.
The Windows scheduled task runs every minute, and `mypromptdaily schedule-run` checks the current IST time and only sends once per day after that configured time.
By default the config and state files are stored under `%APPDATA%\mypromptdaily`.

## Legacy Script Usage

```powershell
python .\workflow.py
```

Or override values at runtime:

```powershell
python .\workflow.py --agent "Researcher Agent" --prompt "Research the latest Copilot announcements and summarize the business impact." --to "person@example.com" --mode draft
```

Available agent labels:

- `Researcher Agent`
- `Analyst Agent`
- `Sales Agent`
- `Delivery Agent`
- `Customer Success Agent`
- `Prompt Coach`
- `ECIF Agent`

## Daily Scheduler Setup

Use the interactive setup script to choose the agent, the daily prompt, your self-email address, and the send time in IST using 24-hour format.

```powershell
mypromptdaily setup
```

The script will:

1. Save your settings in `daily_schedule_config.json`.
2. Register a Windows Task Scheduler task that runs every minute.
3. Send only once per day after the configured IST time.

Yes: Task Scheduler is set up automatically when you run `mypromptdaily setup` and keep the default registration enabled.
It is skipped only if you explicitly choose not to register it or pass `--no-register`.

You can also generate the config without registering the task:

```powershell
mypromptdaily setup --no-register
```

To test whether the scheduled runner is due without sending email:

```powershell
mypromptdaily schedule-run --dry-run
```

To inspect the saved schedule and Windows task registration:

```powershell
mypromptdaily status
```

To remove the Windows scheduled task:

```powershell
mypromptdaily remove-schedule
```

The generated scheduled task calls:

```powershell
python -m mypromptdaily schedule-run --config <config-path> --state <state-path>
```

During setup, the tool writes a short launcher script under `%APPDATA%\mypromptdaily` and registers that script with Task Scheduler. This avoids the Windows `/TR` command-length limit.

## Distribution

Yes, this can be distributed from GitHub.

For a true `pip install mypromptdaily` experience, the remaining external step is publishing this package name to a package index such as PyPI or an internal Python feed. The codebase is now prepared for that name.

Common options:

1. Keep the repo on GitHub and let users install directly:

```powershell
python -m pip install "git+https://github.com/<org>/<repo>.git"
```

2. Build a wheel from the repo and attach it to a GitHub Release.

This repo now includes GitHub Actions workflows that:

- validate and build the package on pushes and pull requests
- build wheel and source artifacts on `v*` tags and attach them to a GitHub Release

## Release From GitHub

To cut a GitHub-backed release:

```powershell
git tag v0.1.0
git push origin main --tags
```

The release workflow will build the package artifacts and attach them to the GitHub Release for that tag.

3. Publish the same package to an internal package feed or PyPI later if you want simpler installs.

If the repo lives on GitHub, the current package layout already supports option 1.

## Notes

- `OUTLOOK_MODE=draft` is the safer default. Set `send` only when you want the mail sent immediately.
- `RESPONSE_STABLE_SECONDS=12` is the default settle window before sharing. Increase it if an agent still sends partial output.
- `--keep-tab-open` or `KEEP_TAB_OPEN=true` keeps the opened Copilot tab available for inspection instead of closing it during cleanup.
- The scheduled task uses `send` mode by default because it is intended for unattended daily mail delivery.
- M365 Copilot page markup can change. If the workflow stops finding the agent button, prompt box, or response content, update the selector lists in `workflow.py`.
- The workflow explicitly closes the Copilot tab it opened and then returns focus to the original Edge tab before ending the Selenium session.
- The scheduled task runs only while your Windows session is available and the existing Edge debug session is already open and authenticated.