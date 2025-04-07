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
                logger.debug(f"No content found in email content dictionary: {email_content.keys()}")
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
                # Check if we actually have substantial content elsewhere in the item
                full_content_length = len(combined_content)
                # Check other content sources for the real content length
                if item.get('original_email') and isinstance(item.get('original_email'), dict):
                    email_content = item.get('original_email', {})
                    if isinstance(email_content.get('content'), str):
                        full_content_length = max(full_content_length, len(email_content.get('content')))
                
                # Check articles content
                article_texts = []
                for article in item.get('articles', []):
                    if isinstance(article.get('content'), str):
                        article_texts.append(article.get('content'))
                        full_content_length += len(article.get('content'))
                
                # Always use INFO level - no more warnings about short content
                logger.info(f"Processing item: {item.get('source', '')} (content size: {full_content_length} chars)")
            else:
                # Log regular content
                logger.info(f"Processing item: {item.get('source', '')} (content size: {len(combined_content)} chars)")
            
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