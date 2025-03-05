"""
Content processor for LetterMonstr application.

This module processes and deduplicates content from multiple sources.
"""

import logging
import difflib
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class ContentProcessor:
    """Processes and deduplicates content from different sources."""
    
    def __init__(self, config):
        """Initialize with content configuration."""
        self.ad_keywords = config['ad_keywords']
        self.similarity_threshold = 0.7  # Content with similarity above this is considered duplicate
    
    def process_and_deduplicate(self, content_items):
        """Process and deduplicate content from different sources."""
        if not content_items:
            logger.warning("No content items to process")
            return []
        
        processed_items = []
        
        try:
            # First pass: process each content item
            for item in content_items:
                processed_item = self._process_item(item)
                if processed_item:
                    processed_items.append(processed_item)
            
            # Second pass: deduplicate content
            deduplicated_items = self._deduplicate_content(processed_items)
            
            # Sort by date, newest first
            sorted_items = sorted(deduplicated_items, key=lambda x: x['date'], reverse=True)
            
            return sorted_items
            
        except Exception as e:
            logger.error(f"Error processing content: {e}", exc_info=True)
            return processed_items
    
    def _process_item(self, item):
        """Process a single content item."""
        try:
            # Extract main content
            email_content = item.get('email_content', {})
            crawled_content = item.get('crawled_content', [])
            
            # Log the structure of email_content for debugging
            logger.debug(f"Email content keys: {email_content.keys() if isinstance(email_content, dict) else 'not a dict'}")
            
            # Get text content from email
            content_text = ''
            if isinstance(email_content, dict):
                # Try to extract content from the dictionary
                if email_content.get('content'):
                    # Direct content field
                    content_text = email_content.get('content', '')
                    logger.debug(f"Using direct content field, length: {len(content_text)}")
                    
                elif email_content.get('content_type') == 'html':
                    # HTML content - extract and clean
                    html_content = email_content.get('content', '')
                    logger.debug(f"Processing HTML content, length: {len(html_content)}")
                    
                    if html_content:
                        # Use BeautifulSoup to extract text from HTML
                        try:
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(html_content, 'html.parser')
                            # Remove script and style elements
                            for script in soup(["script", "style"]):
                                script.extract()
                            # Get text
                            content_text = soup.get_text(separator='\n')
                            # Clean up whitespace
                            content_text = '\n'.join(line.strip() for line in content_text.splitlines() if line.strip())
                            logger.debug(f"Extracted text from HTML, length: {len(content_text)}")
                        except Exception as e:
                            logger.error(f"Error extracting text from HTML: {e}")
                            content_text = html_content  # Use raw HTML if extraction fails
                else:
                    # Plain text content
                    content_text = email_content.get('content', '')
                    logger.debug(f"Using plain text content, length: {len(content_text)}")
            
            # Check if we actually have content
            if not content_text and isinstance(email_content, dict):
                logger.warning(f"No content found in email content dictionary: {email_content.keys()}")
                # Try alternative extraction method - deep search
                for key, value in email_content.items():
                    if isinstance(value, str) and len(value) > len(content_text):
                        content_text = value
                        logger.debug(f"Found larger content in key '{key}', length: {len(content_text)}")
                
                # If still no content, try any dict values recursively
                if not content_text:
                    def search_nested_dict(d, depth=0):
                        if depth > 3:  # Limit recursion depth
                            return None
                            
                        best_text = ''
                        if isinstance(d, dict):
                            for k, v in d.items():
                                if isinstance(v, str) and len(v) > len(best_text):
                                    best_text = v
                                elif isinstance(v, (dict, list)):
                                    nested_text = search_nested_dict(v, depth+1)
                                    if nested_text and len(nested_text) > len(best_text):
                                        best_text = nested_text
                        elif isinstance(d, list):
                            for item in d:
                                nested_text = search_nested_dict(item, depth+1)
                                if nested_text and len(nested_text) > len(best_text):
                                    best_text = nested_text
                        return best_text
                    
                    deep_content = search_nested_dict(email_content)
                    if deep_content and len(deep_content) > len(content_text):
                        content_text = deep_content
                        logger.debug(f"Found content through deep search, length: {len(content_text)}")
            
            # Combine with crawled content
            all_content = content_text
            
            # Add crawled content if available
            article_contents = []
            for article in crawled_content:
                if not article.get('is_ad', False):
                    article_text = f"\n\nARTICLE: {article.get('title', '')}\n{article.get('content', '')}"
                    article_contents.append(article_text)
            
            # Combine email content with crawled content
            combined_content = content_text + "\n\n" + "\n\n".join(article_contents)
            
            # Log the content length to debug
            logger.debug(f"Combined content length: {len(combined_content)}")
            if len(combined_content) < 50:  # Arbitrary threshold for meaningful content
                logger.warning(f"Very short content for source: {item.get('source', '')}, length: {len(combined_content)}")
            
            # Create processed item
            processed_item = {
                'source': item.get('source', ''),
                'date': item.get('date', datetime.now()),
                'content': combined_content,
                'original_email': email_content,
                'articles': crawled_content
            }
            
            return processed_item
            
        except Exception as e:
            logger.error(f"Error processing item: {e}", exc_info=True)
            return None
    
    def _deduplicate_content(self, items):
        """Remove duplicate content across items while preserving unique articles."""
        if not items:
            return []
        
        # Make the similarity threshold more strict to avoid over-merging
        original_threshold = self.similarity_threshold
        self.similarity_threshold = 0.85  # Increased from 0.7 to be more conservative
        
        # Create groups of similar content
        content_groups = []
        
        for item in items:
            assigned_to_group = False
            
            # Check if this item belongs to an existing group
            for group in content_groups:
                # Compare with the first item in the group
                if self._is_similar(item['content'], group[0]['content']):
                    group.append(item)
                    assigned_to_group = True
                    break
            
            # If not assigned to any group, create a new group
            if not assigned_to_group:
                content_groups.append([item])
        
        # For each group, keep the most comprehensive item
        deduplicated_items = []
        
        for group in content_groups:
            if len(group) == 1:
                # Only one item in group, no deduplication needed
                deduplicated_items.append(group[0])
            else:
                # Log that we're merging items
                sources = [item['source'] for item in group]
                logger.info(f"Merging similar content from sources: {sources}")
                
                # Find the most comprehensive item (longest content)
                most_comprehensive = max(group, key=lambda x: len(x['content']))
                
                # Create a merged item combining sources and articles
                merged_item = most_comprehensive.copy()
                
                # Collect sources and articles from all items in the group
                all_sources = [most_comprehensive['source']]
                all_articles = most_comprehensive.get('articles', [])
                
                for item in group:
                    if item != most_comprehensive:
                        if item['source'] not in all_sources:
                            all_sources.append(item['source'])
                        
                        # Add non-duplicate articles
                        for article in item.get('articles', []):
                            if not self._article_exists_in(article, all_articles):
                                all_articles.append(article)
                
                # Update merged item
                merged_item['sources'] = all_sources
                merged_item['articles'] = all_articles
                merged_item['is_merged'] = True
                
                deduplicated_items.append(merged_item)
        
        # Restore original threshold
        self.similarity_threshold = original_threshold
        
        # Log metrics about deduplication
        logger.info(f"Deduplication: {len(items)} original items -> {len(deduplicated_items)} deduplicated items")
        
        return deduplicated_items
    
    def _is_similar(self, text1, text2):
        """Check if two text contents are similar."""
        # Get similarity ratio
        similarity = difflib.SequenceMatcher(None, text1, text2).ratio()
        
        return similarity >= self.similarity_threshold
    
    def _article_exists_in(self, article, article_list):
        """Check if an article already exists in the list of articles."""
        for existing_article in article_list:
            if article.get('url') == existing_article.get('url'):
                return True
            
            # If URLs are different, check content similarity
            if self._is_similar(article.get('content', ''), existing_article.get('content', '')):
                return True
        
        return False 