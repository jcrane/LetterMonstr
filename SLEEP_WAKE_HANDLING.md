# Sleep/Wake Handling for LetterMonster

## Overview

LetterMonster now includes robust sleep/wake detection and recovery to handle laptop sleep without requiring manual intervention. The system automatically detects when your laptop has been asleep and takes corrective actions.

## How It Works

### 1. **Sleep Detection** (3-minute threshold)

The scheduler monitors the time between check cycles. If more than 3 minutes have elapsed, the system assumes the laptop was sleeping.

### 2. **Network Readiness Check**

After detecting sleep, the system waits up to 30 seconds for the network to become ready by testing DNS resolution.

### 3. **Connection Validation**

Before running any tasks, the system validates:

- Network connectivity (DNS resolution)
- IMAP connection to Gmail

### 4. **Automatic Recovery**

Once connections are validated:

- Clears the old scheduler
- Creates fresh scheduled jobs
- Runs catch-up tasks immediately
- Resumes normal operations

### 5. **Enhanced Connection Handling**

- IMAP connections now have longer timeouts (30s)
- Automatic reconnection on stale connections
- Exponential backoff on connection failures
- Better error handling for socket timeouts and network issues

## Options for Running LetterMonster

### Option 1: Manual Running (Simple)

Just run the application manually when you want it to process emails:

```bash
cd /Users/jeremycrane/Documents/Dev/lettermonster
source venv/bin/activate
python3 src/periodic_runner.py
```

**Pros:**

- Simple, no setup required
- Full control over when it runs

**Cons:**

- Must remember to run it
- Won't run automatically after sleep
- Stops when terminal is closed

### Option 2: Background Running with Terminal (Basic)

Keep the terminal open with the process running:

```bash
cd /Users/jeremycrane/Documents/Dev/lettermonster
source venv/bin/activate
nohup python3 src/periodic_runner.py &
```

**Pros:**

- Runs in background
- Can close terminal (with nohup)
- Sleep/wake recovery works

**Cons:**

- Stops when you logout
- No automatic restart if crashes
- Must manually start after reboot

### Option 3: LaunchAgent Service (Recommended)

Install as a macOS service using launchd:

```bash
cd /Users/jeremycrane/Documents/Dev/lettermonster
./install_service.sh
```

**Pros:**

- Starts automatically at login
- Automatic restart if crashes
- Survives logout/reboot
- Best wake-from-sleep handling
- Runs with lower priority (won't slow system)

**Cons:**

- Slightly more complex setup
- Need to use launchctl commands

## Installation Instructions

### Installing as a LaunchAgent (Recommended)

1. **Stop any currently running instances:**

   ```bash
   ./stop_lettermonstr.sh
   ```

2. **Install the service:**

   ```bash
   ./install_service.sh
   ```

3. **Verify it's running:**

   ```bash
   launchctl list | grep lettermonster
   ```

4. **View logs:**

   ```bash
   tail -f data/lettermonstr_periodic.log
   ```

### Managing the Service

**Restart the service:**

```bash
./restart_service.sh
```

**Stop the service:**

```bash
launchctl unload ~/Library/LaunchAgents/com.lettermonster.periodic.plist
```

**Start the service:**

```bash
launchctl load ~/Library/LaunchAgents/com.lettermonster.periodic.plist
```

**Uninstall the service:**

```bash
./uninstall_service.sh
```

**Check service status:**

```bash
launchctl list | grep lettermonster
# Look for PID (process ID) - if present, it's running
```

## Configuration for Sleep/Wake Handling

In your `config/config.yaml`, ensure these settings are present:

```yaml
email:
  periodic_fetch: true  # Enable periodic fetching mode
  fetch_interval_hours: 1  # How often to fetch (1 = hourly)
  mark_read_after_summarization: true  # Mark emails as read after sending summary
```

## Troubleshooting

### Service won't start

1. Check the plist file path is correct in `com.lettermonster.periodic.plist`
2. View error logs: `cat data/launchd_stderr.log`
3. Ensure virtual environment exists: `ls -la venv/bin/python3`

### Still having issues after wake

1. Check the logs for sleep detection:

   ```bash
   grep "SLEEP DETECTED" data/lettermonstr_periodic.log
   ```

2. Verify network recovery:

   ```bash
   grep "Network ready" data/lettermonstr_periodic.log
   ```

3. Look for connection errors:

   ```bash
   grep -i "error\|failed" data/lettermonstr_periodic.log | tail -20
   ```

### Application seems stuck

1. Check if process is actually running:

   ```bash
   ps aux | grep periodic_runner
   ```

2. Restart the service:

   ```bash
   ./restart_service.sh
   ```

3. View recent logs:

   ```bash
   tail -50 data/lettermonstr_periodic.log
   ```

## What to Expect

### Normal Operation

- Every hour: Fetches new emails and processes them
- Every 15 minutes: Checks if it's time to send a summary
- At configured delivery time: Sends summary email

### After Laptop Wakes

You should see log entries like:

```log
⚠️  SLEEP DETECTED: XXX seconds (X.X minutes) since last check
Waiting for network to be ready after wake...
Network is ready
✓ Re-scheduled fetch and process to run every hour
✓ Re-scheduled summary check to run every 15 minutes
🚀 Running catch-up tasks after sleep...
✓ Catch-up tasks completed successfully
✓ Sleep recovery completed
```

### Normal Logs Every Minute

```log
IMAP connection verified
```

This means the system is running normally and connections are healthy.

## Benefits of the LaunchAgent Approach

1. **Automatic Recovery:** If the process crashes for any reason, launchd will automatically restart it after 30 seconds.

2. **Network State Awareness:** The service is configured to restart when network state changes, which helps with wake-from-sleep scenarios.

3. **Persistent Operation:** Survives logout, reboot, and system updates.

4. **Resource Friendly:** Runs with lower priority (nice level 5) so it won't interfere with your other work.

5. **Proper Logging:** All output goes to dedicated log files for easy troubleshooting.

## Recommendation

For the best experience with laptop sleep/wake, I strongly recommend **Option 3 (LaunchAgent Service)**. The sleep detection code will work with any method, but the LaunchAgent provides the most robust and hands-free experience.

If you prefer a simpler approach and don't mind manually restarting after sleep occasionally, **Option 2 (Background Running)** is acceptable.

**Option 1 (Manual Running)** is best for testing or if you only want to run summaries occasionally on-demand.
