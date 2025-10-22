# Deduplication Fix Summary

## Problem Identified
The application was showing duplicate content across multiple email summaries because the cross-summary deduplication system was **not being used**.

## Root Causes Found

### 1. **Deduplication Not Called** ❌
The `_filter_previously_summarized()` method existed but was **never called** in the processing flow.

### 2. **Empty History Table** ❌  
The `summarized_content_history` table was empty (0 entries), so even if called, it had no data to check against.

### 3. **Too Conservative Logic** ❌
The original logic required **BOTH** title AND content to match before skipping - allowing many duplicates through.

### 4. **High Similarity Thresholds** ❌
- Title similarity: 95% (too high)
- Content similarity: 85% (too high)

## Fixes Implemented ✅

### 1. **Enable Cross-Summary Deduplication**
- Added call to `_filter_previously_summarized()` in the main `process_and_deduplicate()` flow
- Now checks last 7 days of summaries for duplicate content

### 2. **More Aggressive Deduplication Logic**
**Before:** Required BOTH title AND content match  
**After:** Requires EITHER title OR content match

This means if a story was in yesterday's summary, it won't appear again even if the newsletter rewrites it slightly.

### 3. **Lowered Similarity Thresholds**
- **Title similarity:** 95% → 90% (catches more similar titles)
- **Content similarity:** 85% → 80% (catches more similar content)
- **Lookback window:** 7 days

### 4. **Improved Logging**
Added detailed logging to track:
- How many items are filtered out
- What type of match triggered the skip (title/content/both)
- Number of content signatures stored for future deduplication

## How It Works Now

```
1. Fetch new emails → Process content
2. Deduplicate within current batch (as before)
3. 🆕 Check against last 7 days of summaries
4. Filter out content matching previous summaries
5. Generate summary with only NEW content
6. Store content signatures for future deduplication
```

## Configuration

The deduplication settings in `src/summarize/processor.py`:

```python
self.similarity_threshold = 0.80              # 80% content similarity
self.title_similarity_threshold = 0.90         # 90% title similarity  
self.cross_summary_lookback_days = 7           # Check last 7 days
```

## What To Expect

### ✅ **Going Forward:**
- **No duplicate stories** across summaries within 7 days
- **All new content** will still be included (nothing missed)
- **Similar rewrites** of the same story will be filtered out

### 📊 **In The Logs:**
```
INFO: Checking for previously summarized content...
INFO: Found 15 historical content items from last 7 days
INFO: Skipping previously summarized content (title match): Tech Company Launches AI...
INFO: Filtered out 3 items that were already in recent summaries
INFO: Successfully stored 12 content signatures for future deduplication
```

## Testing The Fix

After restarting the service:
1. Check that `summarized_content_history` table gets populated
2. Look for "Filtered out X items" messages in logs
3. Verify next summary doesn't repeat stories from recent summaries

```bash
# Check stored signatures
sqlite3 data/lettermonstr.db "SELECT COUNT(*) FROM summarized_content_history;"

# Watch deduplication in action
tail -f data/lettermonstr_periodic.log | grep -i "filtered\|skipping"
```

## Restart Required

Restart the service to apply these changes:
```bash
./restart_service.sh
```

---
**Note:** The first summary after restart will still include all unsummarized content. The deduplication will start working for *subsequent* summaries.
