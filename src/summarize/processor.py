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
import json

from src.database.models import get_session, SummarizedContent, EmailContent

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
        """Process and deduplicate a list of content items."""
        processed_items = []
        
        # Early check for empty items
        if not items:
            logger.warning("No items to process")
            return []
        
        try:
            logger.info(f"Processing {len(items)} items for summarization")
            
            # Process each item
            for item in items:
                processed_item = self._process_item(item)
                
                # Add DB ID if it was in the original item
                if hasattr(item, 'id') and not hasattr(processed_item, 'id'):
                    processed_item['db_id'] = item.id
                    
                if processed_item:
                    processed_items.append(processed_item)
                
            # If this is a database object with email_id, retrieve original content
            for item in processed_items:
                if 'db_id' in item and isinstance(item, dict) and 'content' in item:
                    item_content_length = len(item['content']) if isinstance(item['content'], str) else 0
                    
                    # If content is too short, try to get original email content
                    if item_content_length < 1000 and hasattr(item, 'email_id'):
                        try:
                            # Get original email content from database
                            session = get_session()
                            email_contents = session.query(EmailContent).filter_by(email_id=item.email_id).all()
                            session.close()
                            
                            # Use the largest content available
                            if email_contents:
                                best_content = None
                                best_content_len = 0
                                
                                for content_record in email_contents:
                                    content_text = content_record.content
                                    if content_text and len(content_text) > best_content_len:
                                        best_content = content_text
                                        best_content_len = len(content_text)
                                
                                if best_content and best_content_len > item_content_length:
                                    item['content'] = best_content
                                    logger.info(f"Retrieved original email content: {best_content_len} chars")
                        except Exception as e:
                            logger.error(f"Error retrieving original email content: {e}")
            
            # Log the content length for each item
            for i, item in enumerate(processed_items):
                content = item.get('content', '')
                content_length = len(content) if isinstance(content, str) else 0
                logger.info(f"Item {i+1}: Content length = {content_length} chars")
            
            # Check if we have enough content
            if not processed_items:
                logger.warning("No content to process after processing step")
                return []
            
            # Deduplicate the processed items
            logger.info("Starting deduplication of {} items".format(len(processed_items)))
            deduplicated_items = self._deduplicate_items(processed_items)
            
            # Log the results of deduplication
            logger.info(f"Deduplication: {len(processed_items)} original items → {len(deduplicated_items)} deduplicated items")
            merged_count = len(processed_items) - len(deduplicated_items)
            logger.info(f"Preserved {len(deduplicated_items)} unique items, merged {merged_count} similar items")
            
            # Count sources
            source_count = len(set(item.get('source', '') for item in deduplicated_items))
            logger.info(f"After deduplication: {len(deduplicated_items)} unique items from {source_count} sources")
            
            return deduplicated_items
            
        except Exception as e:
            logger.error(f"Error in process_and_deduplicate: {e}", exc_info=True)
            # Return empty list on error to avoid crashing the application
            return []
    
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
        """Process a single item for summarization.
        
        Args:
            item: Dict containing content to process
            
        Returns:
            Processed item with cleaned text
        """
        try:
            # Log the initial item for debugging
            title = item.get('source', 'Unknown')
            initial_content_length = 0
            
            if isinstance(item, dict):
                # Standard dictionary input
                if 'content' in item and isinstance(item['content'], str):
                    initial_content_length = len(item['content'])
            elif hasattr(item, 'processed_content') and hasattr(item, 'source'):
                # This is a database ProcessedContent object
                title = item.source
                
                # Use the get_processed_content method if available
                if hasattr(item, 'get_processed_content'):
                    db_content = item.get_processed_content()
                    
                    # Handle various return types from get_processed_content
                    if isinstance(db_content, dict):
                        # If it's a dictionary, we'll use it directly
                        item = db_content
                        if 'content' in item and isinstance(item['content'], str):
                            initial_content_length = len(item['content'])
                    elif isinstance(db_content, str):
                        # If it's a raw string, use it as content
                        initial_content_length = len(db_content)
                        item = {
                            'source': title,
                            'content': db_content
                        }
                elif item.processed_content:
                    # Fallback: Try to deserialize the content directly
                    try:
                        # Try to parse as JSON
                        db_content = json.loads(item.processed_content)
                        if isinstance(db_content, dict):
                            item = db_content
                            if 'content' in item and isinstance(item['content'], str):
                                initial_content_length = len(item['content'])
                        else:
                            # Not a dict, use as raw content
                            initial_content_length = len(item.processed_content)
                            item = {
                                'source': title,
                                'content': item.processed_content
                            }
                    except (json.JSONDecodeError, TypeError):
                        # Not JSON, use as raw content
                        initial_content_length = len(item.processed_content)
                        item = {
                            'source': title,
                            'content': item.processed_content
                        }
                    
            logger.info(f"Processing item: {title} (initial content length: {initial_content_length})")
            
            # Initialize with empty content if needed
            if not item.get('content'):
                item['content'] = ''
            
            # Check if we have direct content - prioritize HTML
            direct_html = item.get('html', '')
            direct_text = item.get('text', '')
            
            # If we have HTML content, extract text using BeautifulSoup
            if direct_html and len(direct_html) > len(item['content']):
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(direct_html, 'html.parser')
                    extracted_text = soup.get_text(separator='\n', strip=True)
                    if len(extracted_text) > len(item['content']):
                        item['content'] = extracted_text
                        logger.info(f"Using HTML content for {title}: {len(extracted_text)} chars")
                except Exception as e:
                    logger.warning(f"Error extracting text from HTML: {e}")
                
            # If we have plain text and it's longer than current content, use it
            if direct_text and len(direct_text) > len(item['content']):
                item['content'] = direct_text
                logger.info(f"Using plain text content for {title}: {len(direct_text)} chars")
                
            # Check if we need to extract content from original_email
            if not item['content'] or len(item['content']) < 100:
                if 'original_email' in item and isinstance(item['original_email'], dict):
                    email_content = item['original_email'].get('content', '')
                    if isinstance(email_content, str) and len(email_content) > len(item['content']):
                        item['content'] = email_content
                        logger.info(f"Using original email content for {title}: {len(email_content)} chars")
                        
                    # Also check for HTML and text in original_email
                    email_html = item['original_email'].get('html', '')
                    if email_html and len(email_html) > len(item['content']):
                        try:
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(email_html, 'html.parser')
                            extracted_text = soup.get_text(separator='\n', strip=True)
                            if len(extracted_text) > len(item['content']):
                                item['content'] = extracted_text
                                logger.info(f"Using original email HTML for {title}: {len(extracted_text)} chars")
                        except Exception as e:
                            logger.warning(f"Error extracting text from email HTML: {e}")
            
            # Check for articles
            if 'articles' in item and isinstance(item['articles'], list):
                combined_article_content = ""
                for article in item['articles']:
                    if isinstance(article, dict) and isinstance(article.get('content'), str):
                        combined_article_content += "\n\n" + article.get('content', '')
                
                if combined_article_content and len(combined_article_content) > 100:
                    # If we have article content and it's substantial, add it to the main content
                    if item['content']:
                        item['content'] += "\n\n--- Articles ---\n" + combined_article_content
                    else:
                        item['content'] = combined_article_content
                    logger.info(f"Added article content for {title}: {len(combined_article_content)} chars")
            
            # Check for crawled content
            if 'crawled_content' in item and isinstance(item['crawled_content'], list):
                combined_crawled = ""
                for content in item['crawled_content']:
                    if isinstance(content, dict):
                        if 'clean_content' in content and isinstance(content['clean_content'], str):
                            combined_crawled += "\n\n" + content['clean_content']
                        elif 'content' in content and isinstance(content['content'], str):
                            combined_crawled += "\n\n" + content['content']
                
                if combined_crawled and len(combined_crawled) > 100:
                    # If we have crawled content and it's substantial, add it to the main content
                    if item['content']:
                        item['content'] += "\n\n--- Crawled Content ---\n" + combined_crawled
                    else:
                        item['content'] = combined_crawled
                    logger.info(f"Added crawled content for {title}: {len(combined_crawled)} chars")
            
            # If content is still too short after all checks, log a warning and try raw content
            if not item['content'] or len(item['content']) < 50:
                logger.warning(f"Very short content for {title}: {len(item['content'])} chars")
                
                # Last resort: check for raw_content
                raw_content = item.get('raw_content', '')
                if raw_content and len(raw_content) > len(item['content']):
                    item['content'] = raw_content
                    logger.info(f"Using raw content for {title}: {len(raw_content)} chars")
            
            # Clean the content
            item['content'] = self._clean_text(item['content'])
            
            # Log the processed item size
            logger.info(f"Processing item: {title} (content size: {len(item['content'])} chars)")
            
            return item
        except Exception as e:
            logger.error(f"Error processing item: {e}", exc_info=True)
            # Return the original item if processing fails
            return item
    
    def _deduplicate_items(self, items):
        """Deduplicate items based on content similarity."""
        if not items:
            return []
        
        # First, let's deduplicate by exact title match
        unique_by_title = {}
        for item in items:
            title = item.get('source', '')
            # Skip items with no title
            if not title:
                continue
            
            # If this title already exists, take the one with more content
            if title in unique_by_title:
                existing_content = unique_by_title[title].get('content', '')
                new_content = item.get('content', '')
                
                existing_len = len(existing_content) if isinstance(existing_content, str) else 0
                new_len = len(new_content) if isinstance(new_content, str) else 0
                
                # Keep the one with more content
                if new_len > existing_len:
                    unique_by_title[title] = item
            else:
                unique_by_title[title] = item
        
        # Create a list of all content items as dictionaries for further processing
        # Content items from unique_by_title plus any items without titles
        deduplicated_items = list(unique_by_title.values())
        for item in items:
            title = item.get('source', '')
            if not title:  # Add items without titles
                deduplicated_items.append(item)
        
        # Second pass: further deduplicate by content hashes
        content_hash_map = {}
        for item in deduplicated_items:
            content = item.get('content', '')
            if not content or not isinstance(content, str):
                continue
            
            # Generate a hash of the first 1000 chars for comparison
            content_sample = content[:1000]
            content_hash = hashlib.md5(content_sample.encode('utf-8')).hexdigest()
            
            if content_hash in content_hash_map:
                # If we already have this content, keep the longer version
                existing_content = content_hash_map[content_hash].get('content', '')
                existing_len = len(existing_content) if isinstance(existing_content, str) else 0
                new_len = len(content) if isinstance(content, str) else 0
                
                if new_len > existing_len:
                    content_hash_map[content_hash] = item
            else:
                content_hash_map[content_hash] = item
        
        return list(content_hash_map.values())
    
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