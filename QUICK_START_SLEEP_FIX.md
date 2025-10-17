# Quick Start: Sleep/Wake Fix

## TL;DR - Get Running in 2 Minutes

### Option A: Install as Service (Recommended)

```bash
# 1. Stop any running instances
./stop_lettermonstr.sh

# 2. Install the service
./install_service.sh

# 3. Verify it's running
launchctl list | grep lettermonster

# Done! It will now handle sleep/wake automatically
```

### Option B: Just Run It (Simple)

```bash
# Run it manually - sleep detection still works
source venv/bin/activate
python3 src/periodic_runner.py
```

## Testing It Works

### Quick Test (5 minutes)

1. Let LetterMonster run for 1 minute
2. Put your laptop to sleep for 3+ minutes  
3. Wake it up
4. Check the logs:

   ```bash
   tail -20 data/lettermonstr_periodic.log
   ```

5. You should see "SLEEP DETECTED" and recovery messages

### Diagnostic Check

```bash
./test_sleep_recovery.sh
```

## What You Should See

### Normal Operation

Every minute you'll see:

```log
IMAP connection verified
```

### After Waking from Sleep

You'll see:

```log
⚠️  SLEEP DETECTED: XXX seconds
Network is ready
✓ Re-scheduled fetch and process
✓ Re-scheduled summary check
✓ Sleep recovery completed
```

## Common Questions

**Q: Do I need to change my config?**  
A: No, all existing configs work as-is.

**Q: Will my emails still be processed?**  
A: Yes, the system catches up after wake and resumes normal operation.

**Q: What if it crashes?**  
A: If using the LaunchAgent service, it will auto-restart in 30 seconds.

**Q: Can I still run it manually?**  
A: Yes, the sleep detection works whether running as a service or manually.

**Q: Does this work with the old run_lettermonstr.sh script?**  
A: Yes, but the LaunchAgent service is recommended for the best experience.

## Monitoring

Watch logs in real-time:

```bash
tail -f data/lettermonstr_periodic.log
```

Check if running:

```bash
# If using LaunchAgent:
launchctl list | grep lettermonster

# If running manually:
ps aux | grep periodic_runner
```

## Troubleshooting

### Service won't start

```bash
# Check for errors
cat data/launchd_stderr.log

# Verify paths in plist
cat com.lettermonster.periodic.plist
```

### Still not recovering after sleep

```bash
# View detailed logs
grep -A5 "SLEEP DETECTED" data/lettermonstr_periodic.log

# Check network validation
grep "Network" data/lettermonstr_periodic.log
```

## Need More Help?

- Full documentation: [SLEEP_WAKE_HANDLING.md](SLEEP_WAKE_HANDLING.md)
- Technical details: [SLEEP_WAKE_FIX_SUMMARY.md](SLEEP_WAKE_FIX_SUMMARY.md)
