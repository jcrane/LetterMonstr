# URL Handling Fix Summary

## Problem Identified
Summary emails often contained generic URLs (publisher homepages) instead of direct links to actual articles, making it difficult for users to read the full source content.

## Root Causes

### 1. **Flat URL List** ❌
All URLs were dumped in a flat "SOURCE LINKS:" list without prioritization or clear labeling of which URL was the primary article link.

### 2. **No Clear Guidance to Claude** ❌
The LLM received multiple URLs per content item but no clear instruction about which one was the main article URL.

### 3. **No URL Prioritization** ❌
URLs were collected in order encountered:
- Generic root domain URLs could appear first
- Actual article URLs buried in the list
- Tracking/redirect URLs mixed in

## Fixes Implemented ✅

### 1. **Smart URL Prioritization**
URLs are now prioritized in this order:
1. **Item URL** (if it's a specific article, not a root domain)
2. **Article URLs** from crawled content (actual content pages)
3. **Extracted URLs** from item metadata
4. **Regex-extracted URLs** from content (last resort)

### 2. **Clear PRIMARY URL Labeling**
Each content block now has:
```
**PRIMARY SOURCE URL (USE THIS FOR 'READ MORE' LINK):**
https://techcrunch.com/2025/10/20/actual-article-slug

Additional source URLs:
- https://secondsource.com/article
- https://thirdsource.com/story
```

### 3. **Explicit Instructions to Claude**
Updated prompts to tell Claude:
- "Each content item has a **PRIMARY SOURCE URL** marked clearly - USE THIS as your main 'Read more' link"
- "ONLY use specific article URLs - NEVER use homepage or root domain URLs"
- "If additional source URLs are listed, create separate 'Read more' links for each distinct topic/article"

### 4. **Root Domain Filtering**
The `is_root_domain()` check ensures URLs like:
- ❌ `https://techcrunch.com`
- ❌ `https://example.com/`

Are filtered out in favor of specific paths like:
- ✅ `https://techcrunch.com/2025/10/20/article-title`
- ✅ `https://example.com/blog/post-slug`

### 5. **Secondary URL Support**
When content covers multiple topics from different sources, up to 3 additional URLs are included, allowing Claude to create multiple "Read more" links for different sections.

## How It Works Now

### Before:
```
==== Newsletter Title ====

Content here...

SOURCE LINKS:
- https://example.com
- https://tracking.beehiiv.com/redirect?url=...
- https://actual-article.com/story
- https://another-domain.com/article
```

Claude would sometimes pick the first URL (root domain) or a tracking URL.

### After:
```
==== Newsletter Title ====

Content here...

**PRIMARY SOURCE URL (USE THIS FOR 'READ MORE' LINK):**
https://actual-article.com/story

Additional source URLs:
- https://another-domain.com/article
```

Claude is explicitly told to use the PRIMARY URL and knows additional URLs are for separate topics.

## Expected Results

### ✅ **Better URL Quality:**
- Primary URL is the most specific, relevant article link
- No more root domain links in summaries
- No tracking/redirect URLs

### ✅ **Multiple Sources Handled Correctly:**
- When a newsletter covers 3 different articles, you'll get 3 separate "Read more" links
- Each link points to the actual article

### ✅ **Consistent Link Format:**
- Descriptive link text: `<a href="URL">Read more from TechCrunch</a>`
- Not generic: ~~`Read more`~~

## Configuration

The URL prioritization logic is in `src/summarize/generator.py`:
- Lines 266-326: URL extraction and prioritization (full content path)
- Lines 381-442: URL extraction and prioritization (scaled content path)

The prompt instructions are in:
- `src/summarize/generator.py`: System prompts (lines 33-44 and 56-68)
- `src/summarize/claude_summarizer.py`: URL handling section (lines 47-57)

## Testing

After restarting the service, check the next summary for:
1. **Specific article URLs** - each "Read more" link goes to an actual article, not a homepage
2. **Multiple URLs per section** - if a newsletter section covers 3 stories, you'll see 3 "Read more" links
3. **Descriptive link text** - "Read more from The Verge" instead of just "Read more"

## Restart Required

Restart the service to apply these changes:
```bash
./restart_service.sh
```

---
**Note:** This fix improves URL selection and presentation to Claude. The quality of links will be as good as the URLs extracted from the original newsletter content.
