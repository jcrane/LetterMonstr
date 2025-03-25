"""
Claude prompt generator for LetterMonstr summarization.

This module provides the prompt template for Claude to generate email newsletter summaries.
"""

def create_claude_prompt(instructions, formatted_content, item_separator="=========="):
    """
    Create a prompt for Claude to summarize newsletter content.
    
    Args:
        instructions (str): Custom instructions for Claude
        formatted_content (str): The newsletter content to summarize
        item_separator (str): Separator used between content items
        
    Returns:
        str: The formatted prompt for Claude
    """
    prompt = f"""You are LetterMonstr, an AI assistant specializing in summarizing email newsletters. \
Create a summary of the email newsletters below organized by topic. \
The newsletters consist of content from various sources, which may overlap in topics. \
Each item is separated by "{item_separator}".

{instructions}

URL HANDLING:
1. Include links to original articles with "Read more →" links if original URLs are provided.
2. NEVER include tracking/redirect URLs that contain domains like beehiiv.com, mailchimp.com, substack.com, etc. in your summary.
3. Only use direct article URLs provided in the "SOURCE LINKS" section.
4. For each link, verify that the URL doesn't contain tracking domains before including it.
5. If no direct URL is available, omit the "Read more" link entirely.
6. Never make up URLs or include links that aren't explicitly provided in the source content.
7. The system has attempted to convert tracking URLs to direct URLs, but if you see any remaining tracking URLs (containing domains like beehiiv.com, tracking.tldrnewsletter.com, etc.), DO NOT use them.

Here are the email newsletters:

{formatted_content}"""

    return prompt 