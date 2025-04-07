"""
Content processor for LetterMonstr application.

This module processes and deduplicates content from multiple sources.
"""

import logging
import difflib
import os
import hashlib
from datetime import datetime, timedelta
import copy

from src.database.models import get_session, SummarizedContent

logger = logging.getLogger(__name__)

class ContentProcessor:
    """Processes and deduplicates content from different sources."""
    
    def __init__(self, config):
        """Initialize with content configuration."""
        self.ad_keywords = config['ad_keywords']
        self.similarity_threshold = 0.95  # Raised to require very high content similarity
        self.title_similarity_threshold = 0.95  # Raised to require very high title similarity
        self.db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'data', 'lettermonstr.db')
        self.cross_summary_lookback_days = 14  # Increased from 7 to 14 days for better deduplication
    
    def _generate_content_fingerprint(self, content):
        """Generate a fingerprint for content to use in deduplication.
        
        Args:
            content (str): Content to fingerprint
            
        Returns:
            str: A hash representing the content fingerprint
        """
        if not content or not isinstance(content, str):
            return hashlib.md5("empty_content".encode('utf-8')).hexdigest()
            
        # Take the first 1000 characters to create a fingerprint
        # This is enough to identify duplicate content without using the full text
        fingerprint_text = content[:1000]
        
        # Create a hash of the text
        return hashlib.md5(fingerprint_text.encode('utf-8')).hexdigest()
    
    def process_and_deduplicate(self, items):
        processed_items = []
        for item in items:
            item_copy = copy.deepcopy(item)
            
            # Add logging for content length
            content = item_copy.get('content', '')
            content_length = len(content) if isinstance(content, str) else 0
            title = item_copy.get('source', '')
            
            # Always log as INFO - no more warnings about short content
            logger.info(f"Processing item: {title} (initial content length: {content_length})")
            
            processed_item = self._process_item(item_copy)
            if processed_item:
                processed_items.append(processed_item)
                
        sorted_items, item_sources = self._deduplicate_content(processed_items)
        
        logger.info(f"After deduplication: {len(sorted_items)} unique items from {len(item_sources)} sources")
        return sorted_items
    
    def _filter_previously_summarized(self, items):
        """Filter out content that has already been included in previous summaries."""
        if not items:
            return []
            
        # Open database session
        session = get_session(self.db_path)
        try:
            # Calculate date threshold for historical content
            threshold_date = datetime.now() - timedelta(days=self.cross_summary_lookback_days)
            
            # Get all content fingerprints from recent summaries
            historical_content = session.query(SummarizedContent).filter(
                SummarizedContent.date_summarized >= threshold_date
            ).all()
            
            logger.info(f"Found {len(historical_content)} historical content items from last {self.cross_summary_lookback_days} days")
            
            historical_fingerprints = [item.content_fingerprint for item in historical_content if item.content_fingerprint]
            historical_titles = [item.content_title for item in historical_content if item.content_title]
            historical_hashes = set([item.content_hash for item in historical_content if item.content_hash])
            
            # Filter out content that has already been summarized
            filtered_items = []
            skipped_items = 0
            
            for item in items:
                # Extract title
                title = item.get('source', '')
                if 'Fwd: ' in title:
                    title = title.split('Fwd: ', 1)[1]
                
                # Create content fingerprint and hash
                content = item.get('content', '')
                fingerprint = content[:1000] if content else ''  # Use first 1000 chars as fingerprint
                content_hash = hashlib.md5((title + fingerprint[:100]).encode('utf-8')).hexdigest()
                
                # Check for exact hash match first (most reliable)
                if content_hash in historical_hashes:
                    logger.info(f"Skipping previously summarized content (exact hash match): {title}")
                    skipped_items += 1
                    continue
                
                # Check for title similarity with historical content
                title_match = False
                for hist_title in historical_titles:
                    if self._is_similar_title(title, hist_title):
                        title_match = True
                        break
                
                # Check for content similarity with historical content
                content_match = False
                for hist_fingerprint in historical_fingerprints:
                    if self._is_similar(fingerprint, hist_fingerprint):
                        content_match = True
                        break
                
                # Skip if BOTH title AND content are similar to historical content
                # This is a more balanced deduplication approach requiring both matches
                if (title_match and len(title) > 5) and content_match:
                    logger.info(f"Skipping previously summarized content (title and content match): {title}")
                    skipped_items += 1
                    continue
                
                # Otherwise, include it
                filtered_items.append(item)
            
            logger.info(f"Cross-summary deduplication: {len(items)} items → {len(filtered_items)} items (skipped {skipped_items})")
            return filtered_items
            
        except Exception as e:
            logger.error(f"Error filtering previously summarized content: {e}", exc_info=True)
            return items
        finally:
            session.close()
    
    def store_summarized_content(self, summary_id, content_items):
        """Store signatures of summarized content for future deduplication."""
        if not summary_id or not content_items:
            return
            
        # Open database session
        session = get_session(self.db_path)
        try:
            stored_count = 0
            
            for item in content_items:
                # Extract title
                title = item.get('source', '')
                if 'Fwd: ' in title:
                    title = title.split('Fwd: ', 1)[1]
                
                # Create content fingerprint
                content = item.get('content', '')
                fingerprint = content[:1000] if content else ''  # Use first 1000 chars as fingerprint
                
                # Create a unique hash for this content
                content_hash = hashlib.md5((title + fingerprint[:100]).encode('utf-8')).hexdigest()
                
                # Check if content already exists
                existing = session.query(SummarizedContent).filter_by(content_hash=content_hash).first()
                if existing:
                    logger.debug(f"Content already tracked: {title}")
                    # Update the existing record with the latest summary ID
                    existing.summary_id = summary_id
                    existing.date_summarized = datetime.now()
                    session.add(existing)
                    stored_count += 1
                    continue
                
                # Create signature record
                signature = SummarizedContent(
                    content_hash=content_hash,
                    content_title=title,
                    content_fingerprint=fingerprint,
                    summary_id=summary_id,
                    date_summarized=datetime.now()
                )
                
                session.add(signature)
                stored_count += 1
                
                # Store additional signatures for better deduplication
                # Add a fingerprint based on just the first paragraph to catch similar content with slight modifications
                if content and len(content) > 200:
                    first_paragraph = content.split('\n\n')[0][:300]  # First paragraph, max 300 chars
                    if len(first_paragraph) > 100:  # Only if it's substantial
                        para_hash = hashlib.md5((title + first_paragraph).encode('utf-8')).hexdigest()
                        # Check this variant doesn't already exist
                        if not session.query(SummarizedContent).filter_by(content_hash=para_hash).first():
                            para_signature = SummarizedContent(
                                content_hash=para_hash,
                                content_title=title,
                                content_fingerprint=first_paragraph,
                                summary_id=summary_id,
                                date_summarized=datetime.now()
                            )
                            session.add(para_signature)
                            stored_count += 1
            
            # Commit changes
            session.commit()
            logger.info(f"Stored {stored_count} content signatures for summary {summary_id}")
            
        except Exception as e:
            logger.error(f"Error storing summarized content signatures: {e}", exc_info=True)
            session.rollback()
        finally:
            session.close()
    
    def _process_item(self, item):
        """Process a single content item."""
        try:
            # Get title for logging
            title = item.get('source', 'Unknown')
            
            # Log initial content length for debugging
            initial_content_length = len(item.get('content', '')) if isinstance(item.get('content', ''), str) else 0
            logger.info(f"Processing item: {title} (initial content length: {initial_content_length})")
            
            # Different content structures to check
            original_email = item.get('original_email', {})
            crawled_content = item.get('crawled_content', [])
            articles = item.get('articles', [])
            
            # Initialize combined content
            content_parts = []
            
            # Check direct content first 
            direct_content = item.get('content', '')
            if isinstance(direct_content, str) and len(direct_content) > 0:
                # Add to our content collection
                content_parts.append(direct_content)
                logger.debug(f"Added direct content: {len(direct_content)} chars")
                
            # Check for HTML content
            html_content = item.get('html', '')
            if isinstance(html_content, str) and len(html_content) > 0:
                # Extract text from HTML
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html_content, 'html.parser')
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.extract()
                    # Get text
                    html_text = soup.get_text(separator='\n')
                    # Clean up whitespace
                    html_text = '\n'.join(line.strip() for line in html_text.splitlines() if line.strip())
                    if len(html_text) > 0:
                        content_parts.append(html_text)
                        logger.debug(f"Added extracted HTML text: {len(html_text)} chars")
                except Exception as e:
                    logger.error(f"Error extracting text from HTML: {e}")
                    # Use raw HTML as fallback
                    content_parts.append(html_content)
                    logger.debug(f"Added raw HTML as fallback: {len(html_content)} chars")
            
            # Check for plain text content
            text_content = item.get('text', '')
            if isinstance(text_content, str) and len(text_content) > 0:
                content_parts.append(text_content)
                logger.debug(f"Added text content: {len(text_content)} chars")
            
            # Check for content in original_email if it exists
            if isinstance(original_email, dict):
                # Try content from original email
                email_content = original_email.get('content', '')
                if isinstance(email_content, str) and len(email_content) > 0:
                    content_parts.append(email_content)
                    logger.debug(f"Added original email content: {len(email_content)} chars")
                
                # Also check HTML and text in original email
                email_html = original_email.get('html', '')
                if isinstance(email_html, str) and len(email_html) > 0:
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(email_html, 'html.parser')
                        for script in soup(["script", "style"]):
                            script.extract()
                        email_html_text = soup.get_text(separator='\n')
                        email_html_text = '\n'.join(line.strip() for line in email_html_text.splitlines() if line.strip())
                        if len(email_html_text) > 0:
                            content_parts.append(email_html_text)
                            logger.debug(f"Added extracted original email HTML: {len(email_html_text)} chars")
                    except Exception as e:
                        logger.error(f"Error extracting text from original email HTML: {e}")
                
                email_text = original_email.get('text', '')
                if isinstance(email_text, str) and len(email_text) > 0:
                    content_parts.append(email_text)
                    logger.debug(f"Added original email text: {len(email_text)} chars")
            
            # Add content from any articles
            for article in articles:
                if isinstance(article, dict) and isinstance(article.get('content'), str):
                    article_content = article.get('content', '')
                    if len(article_content) > 0:
                        content_parts.append(f"ARTICLE: {article.get('title', '')}\n{article_content}")
                        logger.debug(f"Added article content: {len(article_content)} chars")
            
            # Add content from crawled content
            for crawled in crawled_content:
                if isinstance(crawled, dict) and isinstance(crawled.get('content'), str):
                    crawled_text = crawled.get('content', '')
                    if len(crawled_text) > 0:
                        content_parts.append(f"CRAWLED: {crawled.get('title', '')}\n{crawled_text}")
                        logger.debug(f"Added crawled content: {len(crawled_text)} chars")
            
            # Combine all content parts
            combined_content = "\n\n".join(content_parts)
            
            # Clean the combined content
            clean_content = self.clean_content(combined_content)
            
            # Calculate total content length
            total_content_length = len(clean_content)
            
            # If the content is empty after cleaning, try to use any raw content
            if total_content_length < 100:
                logger.warning(f"Content for {title} is very short after cleaning: {total_content_length} chars")
                for key in ['raw_content', 'raw_email', 'raw_message']:
                    if key in item and isinstance(item[key], str) and len(item[key]) > total_content_length:
                        logger.info(f"Using {key} as fallback content: {len(item[key])} chars")
                        clean_content = item[key]
                        total_content_length = len(clean_content)
                        break
            
            # Log the final processed item size
            logger.info(f"Processing item: {title} (content size: {total_content_length} chars)")
            
            # Update the content in the item
            item['content'] = clean_content
            
            return item
        except Exception as e:
            logger.error(f"Error processing item: {e}", exc_info=True)
            # Return the original item if there was an error
            return item
    
    def _deduplicate_content(self, items):
        """Remove duplicate content across items while preserving unique articles."""
        if not items:
            return [], []
        
        logger.info(f"Starting deduplication of {len(items)} items")
        
        # Extract titles and content for comparison
        for item in items:
            # Extract a title from the source or content
            source = item.get('source', '')
            if 'Fwd: ' in source:
                # Remove forwarding prefix if present
                item['clean_title'] = source.split('Fwd: ', 1)[1]
            else:
                item['clean_title'] = source
                
            # Create a "fingerprint" of the content using key sentences
            content = item.get('content', '')
            # Instead of just first 500 chars, extract meaningful sentences
            if content:
                sentences = content.split('.')
                # Take first 3 sentences and 3 from middle if available
                first_sentences = '. '.join(sentences[:3]) if len(sentences) >= 3 else content[:300]
                mid_point = len(sentences) // 2
                mid_sentences = '. '.join(sentences[mid_point:mid_point+3]) if len(sentences) > 6 else ""
                item['content_fingerprint'] = first_sentences + " " + mid_sentences
            else:
                item['content_fingerprint'] = ''
        
        # First pass: More selective grouping by very similar titles
        content_groups = []
        
        for item in items:
            assigned_to_group = False
            
            for group in content_groups:
                # For title matching, require both similar title AND similar content
                title_match = self._is_similar_title(item['clean_title'], group[0]['clean_title'])
                content_match = False
                
                # Only check content if titles match
                if title_match:
                    # Verify with content similarity
                    content_match = self._is_similar(item['content_fingerprint'], group[0]['content_fingerprint'])
                
                # Only group if BOTH title and content match
                if title_match and content_match:
                    group.append(item)
                    assigned_to_group = True
                    logger.debug(f"Grouped by similarity: '{item['clean_title']}' with '{group[0]['clean_title']}'")
                    break
            
            # If not assigned to any group, create a new group
            if not assigned_to_group:
                content_groups.append([item])
        
        # For each group, create a merged item
        deduplicated_items = []
        
        # Count how many items were merged
        merged_count = 0
        preserved_count = 0
        
        # Collect all sources
        item_sources = []
        
        for group in content_groups:
            if len(group) == 1:
                # Only one item in group, no deduplication needed
                # Clean up our temporary fields
                item = group[0]
                if 'clean_title' in item:
                    del item['clean_title']
                if 'content_fingerprint' in item:
                    del item['content_fingerprint']
                deduplicated_items.append(item)
                preserved_count += 1
                # Add source to the sources list
                if item.get('source') and item.get('source') not in item_sources:
                    item_sources.append(item.get('source'))
            else:
                # Log that we're merging items
                sources = [item['source'] for item in group]
                logger.info(f"Merging similar content: {sources[0]} (and {len(sources)-1} others)")
                merged_count += len(group) - 1  # Count items that were merged
                
                # Find the most comprehensive item (longest content)
                most_comprehensive = max(group, key=lambda x: len(x['content']))
                
                # Create a merged item combining sources and articles
                merged_item = most_comprehensive.copy()
                
                # Remove our temporary fields
                if 'clean_title' in merged_item:
                    del merged_item['clean_title']
                if 'content_fingerprint' in merged_item:
                    del merged_item['content_fingerprint']
                
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
                
                # Add all sources to the sources list
                for source in all_sources:
                    if source not in item_sources:
                        item_sources.append(source)
        
        # Log metrics about deduplication
        logger.info(f"Deduplication: {len(items)} original items → {len(deduplicated_items)} deduplicated items")
        logger.info(f"Preserved {preserved_count} unique items, merged {merged_count} similar items")
        
        return deduplicated_items, item_sources
    
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
    
    def _is_similar_title(self, title1, title2):
        """Check if two titles are similar enough to be considered the same article."""
        # Special case for identical titles
        if title1 == title2:
            return True
            
        # Special case for very short titles
        if len(title1) < 10 or len(title2) < 10:
            return False
            
        # Clean titles of common prefixes and emojis for better comparison
        def clean_title(title):
            # Remove common emoji patterns
            import re
            title = re.sub(r'[\U00010000-\U0010ffff]', '', title)  # Remove emojis
            title = re.sub(r'🔊|🏆|🧠|🖼️|🤖|💰|🖊️|🛎️|📣', '', title)  # Remove specific emojis
            title = title.strip()
            return title
            
        clean1 = clean_title(title1)
        clean2 = clean_title(title2)
        
        # Get similarity ratio
        similarity = difflib.SequenceMatcher(None, clean1, clean2).ratio()
        
        # Higher threshold for titles
        return similarity >= self.title_similarity_threshold
    
    def clean_content(self, content, content_type='text'):
        """Clean content based on content type.
        
        Handles various input content formats (str, dict) and extracts the most
        meaningful content.
        
        Args:
            content: Content to clean, can be string or dict
            content_type: Type of content ('text', 'html', etc.)
            
        Returns:
            str: Cleaned content
        """
        try:
            # Handle different input types
            if content is None:
                return ""
                
            # Handle dictionary input
            if isinstance(content, dict):
                # Try various fields that might contain the actual content
                for field in ['content', 'main_content', 'raw_content', 'text', 'html']:
                    if field in content and content[field]:
                        # Recursively clean the content from this field
                        return self.clean_content(content[field], content_type)
                
                # If we get here, we didn't find any content field
                logger.warning(f"Dict content without valid content field, keys: {list(content.keys())}")
                return ""
            
            # Convert to string if not already
            if not isinstance(content, str):
                content = str(content)
            
            # Skip if empty
            if not content.strip():
                return ""
            
            # Process based on content type
            if content_type == 'html':
                from bs4 import BeautifulSoup
                try:
                    # Parse with BeautifulSoup
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # Remove script and style tags
                    for tag in soup(['script', 'style', 'header', 'footer', 'nav']):
                        tag.decompose()
                    
                    # Extract text
                    text = soup.get_text(separator='\n')
                    
                    # Basic cleaning
                    cleaned_text = self._clean_text(text)
                    
                    return cleaned_text
                except Exception as e:
                    logger.warning(f"Error cleaning HTML content: {e}")
                    # Fallback to text cleaning
                    return self._clean_text(content)
            else:
                # Text content
                return self._clean_text(content)
                
        except Exception as e:
            logger.error(f"Error cleaning content: {e}", exc_info=True)
            # Return a safe fallback
            if isinstance(content, str):
                return content[:1000]  # Return truncated original
            elif isinstance(content, dict) and 'source' in content:
                return f"Content from {content['source']}"
            else:
                return ""
    
    def _clean_text(self, text):
        """Clean plain text content.
        
        Removes excessive whitespace, normalizes line breaks, and performs other
        basic text cleanup.
        
        Args:
            text (str): Text to clean
            
        Returns:
            str: Cleaned text
        """
        if not text or not isinstance(text, str):
            return ""
            
        # Normalize line endings
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Remove excess whitespace
        lines = [line.strip() for line in text.split('\n')]
        
        # Remove empty lines and join
        cleaned = '\n'.join(line for line in lines if line)
        
        # Remove very common email footers
        for footer in [
            "Sent from my iPhone",
            "Sent from my mobile device",
            "Get Outlook for",
            "If you received this email in error",
            "To unsubscribe",
            "View this email in your browser"
        ]:
            if footer in cleaned:
                # Find the footer position and truncate
                pos = cleaned.find(footer)
                if pos > len(cleaned) // 2:  # Only if in second half of content
                    cleaned = cleaned[:pos]
        
        return cleaned 