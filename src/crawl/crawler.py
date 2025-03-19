"""
Web crawler for LetterMonstr application.

This module follows links found in newsletters and extracts their content.
"""

import os
import logging
import requests
import time
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse

from src.database.models import get_session, Link, CrawledContent

logger = logging.getLogger(__name__)

class WebCrawler:
    """Fetches and extracts content from links."""
    
    def __init__(self, config):
        """Initialize with content configuration."""
        self.max_links = config['max_links_per_email']
        self.max_depth = config['max_link_depth']
        self.user_agent = config['user_agent']
        self.timeout = config['request_timeout']
        self.ad_keywords = config['ad_keywords']
        self.db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'data', 'lettermonstr.db')
        self.headers = {
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    
    def crawl(self, links, depth=0):
        """Crawl the provided links and extract content."""
        if not links or depth >= self.max_depth:
            return []
        
        # Limit the number of links to crawl
        if len(links) > self.max_links:
            links = links[:self.max_links]
        
        crawled_content = []
        session = get_session(self.db_path)
        
        try:
            for link_data in links:
                url = link_data['url']
                
                # Skip already crawled links
                if self._is_crawled(session, url):
                    logger.debug(f"Skipping already crawled URL: {url}")
                    continue
                
                # Fetch and process the page
                page_content = self._fetch_page(url)
                
                if not page_content:
                    continue
                
                # Extract content from the page
                extracted_content = self._extract_content(url, page_content)
                
                # Check if content appears to be an advertisement
                is_ad = self._is_advertisement(extracted_content)
                
                # Store the crawled content
                content_id = self._store_content(session, url, extracted_content, is_ad)
                
                if not is_ad:
                    crawled_content.append({
                        'url': url,
                        'title': extracted_content['title'],
                        'content': extracted_content['clean_text'],
                        'is_ad': is_ad
                    })
                
                # Add a small delay to be nice to servers
                time.sleep(1)
            
            return crawled_content
            
        except Exception as e:
            logger.error(f"Error in crawl process: {e}", exc_info=True)
            return crawled_content
        finally:
            session.close()
    
    def _fetch_page(self, url):
        """Fetch a web page and return its content."""
        try:
            logger.info(f"Fetching URL: {url}")
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            
            if response.status_code == 200:
                return response.text
            else:
                logger.warning(f"Failed to fetch URL: {url} (Status code: {response.status_code})")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching page {url}: {e}", exc_info=True)
            return None
    
    def _extract_content(self, url, html_content):
        """Extract content from HTML."""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract title
            title = soup.title.string if soup.title else ''
            
            # Extract meta description
            meta_desc = ''
            meta_tag = soup.find('meta', attrs={'name': 'description'})
            if meta_tag and 'content' in meta_tag.attrs:
                meta_desc = meta_tag['content']
            
            # Remove unwanted elements
            for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside']):
                tag.decompose()
            
            # Extract the main article content
            article = soup.find('article')
            if article:
                main_content = article
            else:
                # Look for typical content containers
                main_content = soup.find('main') or soup.find(id=['content', 'main', 'article']) or soup.body
            
            # Clean the content
            clean_text = self._clean_text(main_content.get_text(' ', strip=True)) if main_content else ''
            
            return {
                'url': url,
                'title': title,
                'description': meta_desc,
                'raw_html': str(soup),
                'clean_text': clean_text
            }
            
        except Exception as e:
            logger.error(f"Error extracting content from {url}: {e}", exc_info=True)
            return {
                'url': url,
                'title': '',
                'description': '',
                'raw_html': html_content,
                'clean_text': ''
            }
    
    def _clean_text(self, text):
        """Clean extracted text content."""
        # Remove extra whitespace
        text = ' '.join(text.split())
        return text
    
    def _is_advertisement(self, content):
        """Check if content is likely an advertisement."""
        if not content:
            return False
            
        # Check title and description for ad keywords
        try:
            # Handle potential None values safely
            title = content.get('title', '') or ''
            description = content.get('description', '') or ''
            clean_text = content.get('clean_text', '') or ''
            
            # Combine the fields for checking
            lower_content = (title + ' ' + description + ' ' + clean_text).lower()
            
            # Check for ad keywords
            for keyword in self.ad_keywords:
                if keyword.lower() in lower_content:
                    logger.info(f"Identified advertisement content: {content.get('url', '')} (matched keyword: {keyword})")
                    return True
        except Exception as e:
            logger.error(f"Error checking if content is advertisement: {e}")
            # Be conservative - don't flag as ad if we can't tell
            return False
            
        return False
    
    def _is_crawled(self, session, url):
        """Check if a URL has already been crawled."""
        try:
            # Normalize the URL
            normalized_url = self._normalize_url(url)
            
            # Check if any link with this URL exists and has been crawled
            link = session.query(Link).filter(Link.url.like(f"%{normalized_url}%"), Link.crawled == True).first()
            
            return link is not None
            
        except Exception as e:
            logger.error(f"Error checking if URL is crawled: {e}", exc_info=True)
            return False
    
    def _normalize_url(self, url):
        """Normalize a URL for comparison."""
        parsed = urlparse(url)
        # Remove www. prefix, query parameters, and trailing slashes
        normalized = parsed.netloc.replace('www.', '') + parsed.path.rstrip('/')
        return normalized
    
    def _store_content(self, session, url, content, is_ad):
        """Store crawled content in the database."""
        try:
            # Find the link in the database
            link = session.query(Link).filter(Link.url == url).first()
            
            if not link:
                logger.warning(f"Link not found in database: {url}")
                return None
            
            # Update the link as crawled
            link.crawled = True
            link.date_crawled = datetime.now()
            
            # Create crawled content entry
            crawled_content = CrawledContent(
                link_id=link.id,
                title=content['title'],
                content=content['raw_html'],
                clean_content=content['clean_text'],
                is_ad=is_ad,
                crawl_date=datetime.now()
            )
            
            session.add(crawled_content)
            session.commit()
            
            return crawled_content.id
            
        except Exception as e:
            logger.error(f"Error storing crawled content: {e}", exc_info=True)
            session.rollback()
            return None 