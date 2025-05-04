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
        """Crawl the provided links and extract content.
        
        Args:
            links: Either a single URL string, a dictionary with URL, or a list of link dictionaries
            depth: Current depth of crawling (for recursive crawling)
        
        Returns:
            list: List of crawled content dictionaries
        """
        if not links:
            return []
            
        # Stop if we've reached maximum depth
        if depth >= self.max_depth:
            logger.info(f"Reached maximum crawl depth ({self.max_depth}), stopping")
            return []
        
        # Convert single string URL to a link dictionary
        if isinstance(links, str):
            links = [{'url': links, 'title': links}]
        # Convert single link dictionary to a list
        elif isinstance(links, dict) and 'url' in links:
            links = [links]
        
        # Resolve redirects and get actual content URLs
        links = self.get_content_urls(links)
        
        # Limit the number of links to crawl
        if len(links) > self.max_links:
            logger.info(f"Limiting crawl to {self.max_links} of {len(links)} links")
            links = links[:self.max_links]
        
        crawled_content = []
        session = get_session(self.db_path)
        
        try:
            for link_data in links:
                # Skip if we don't have a URL
                if not isinstance(link_data, dict) or 'url' not in link_data:
                    logger.warning(f"Invalid link data, skipping: {link_data}")
                    continue
                    
                url = link_data['url']
                
                # Skip if not a valid HTTP URL
                if not url.lower().startswith(('http://', 'https://')):
                    logger.warning(f"Skipping non-HTTP URL: {url}")
                    continue
                
                # Skip already crawled links
                if self._is_crawled(session, url):
                    logger.debug(f"Skipping already crawled URL: {url}")
                    continue
                
                # Fetch and process the page
                logger.info(f"Crawling URL: {url}")
                page_content = self._fetch_page(url)
                
                if not page_content:
                    logger.warning(f"No content fetched from URL: {url}")
                    continue
                
                # Extract content from the page
                extracted_content = self._extract_content(url, page_content)
                
                # Skip if we didn't extract meaningful content
                if not extracted_content or not extracted_content.get('clean_text'):
                    logger.warning(f"No meaningful content extracted from URL: {url}")
                    continue
                
                # Check if content appears to be an advertisement
                is_ad = self._is_advertisement(extracted_content)
                if is_ad:
                    logger.info(f"Content from {url} appears to be an advertisement, skipping")
                    continue
                
                # Store the crawled content
                content_id = self._store_content(session, url, extracted_content, is_ad)
                
                # Add to results
                crawled_content.append({
                    'url': url,
                    'title': extracted_content['title'],
                    'content': extracted_content['clean_text'],
                    'is_ad': is_ad,
                    'content_id': content_id
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
            title = self._extract_title(soup)
            
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
    
    def _extract_title(self, soup):
        """Extract title from BeautifulSoup object."""
        if not soup:
            return ""
            
        # Try to find title tag
        title_tag = soup.find('title')
        if title_tag and title_tag.text:
            return title_tag.text.strip()
            
        # Try h1 if no title tag or empty title
        h1_tag = soup.find('h1')
        if h1_tag and h1_tag.text:
            return h1_tag.text.strip()
            
        # Try meta title
        meta_title = soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            return meta_title['content'].strip()
            
        # Fallback to empty string
        return ""
    
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
    
    def resolve_redirect(self, url):
        """Follow redirects to get the actual destination URL."""
        try:
            # Skip non-HTTP URLs
            if not url.lower().startswith(('http://', 'https://')):
                return url
                
            # Check if this is a root domain without a path (excluding common homepage indicators)
            parsed_url = urlparse(url)
            if not parsed_url.path or parsed_url.path == '/' or parsed_url.path.lower() in ['/index.html', '/index.php', '/home']:
                logger.info(f"Skipping root domain URL without specific content path: {url}")
                return None  # Don't use bare domains as content links
                
            # Also skip common newsletter/tracking domains with no specific content
            problematic_domains = [
                'beehiiv.com', 'media.beehiiv.com', 'link.mail.beehiiv.com',
                'mailchimp.com', 'substack.com', 'bytebytego.com',
                'sciencealert.com', 'leapfin.com', 'cutt.ly',
                'genai.works', 'link.genai.works'
            ]
            
            if any(domain in parsed_url.netloc.lower() for domain in problematic_domains) and (not parsed_url.path or parsed_url.path == '/' or len(parsed_url.path) < 5):
                logger.info(f"Skipping known newsletter/tracking domain without specific content: {url}")
                return None
                
            # Send a HEAD request first to get the final URL after redirects
            logger.info(f"Resolving URL: {url}")
            head_response = requests.head(url, headers=self.headers, allow_redirects=True, timeout=self.timeout)
            final_url = head_response.url
            
            if final_url != url:
                logger.info(f"URL {url} redirected to {final_url}")
                
                # Check if the final URL is also a root domain
                final_parsed = urlparse(final_url)
                if not final_parsed.path or final_parsed.path == '/' or final_parsed.path.lower() in ['/index.html', '/index.php', '/home']:
                    logger.info(f"Redirect ended at root domain without specific content: {final_url}")
                    return None  # Don't use bare domains as content links
                
            return final_url
            return url
            
        except Exception as e:
            logger.error(f"Error resolving URL {url}: {e}", exc_info=True)
            return url
            
    def get_content_urls(self, links):
        """Process a list of links to get actual content URLs.
        
        Args:
            links: List of link dictionaries or URLs
            
        Returns:
            list: List of dictionaries with resolved URLs
        """
        result = []
        
        # Process each link
        for link in links:
            try:
                # Extract URL from link object
                if isinstance(link, dict) and 'url' in link:
                    url = link['url']
                    title = link.get('title', '')
                elif isinstance(link, str):
                    url = link
                    title = ''
                else:
                    logger.warning(f"Invalid link format: {link}")
                    continue
                    
                # Skip non-HTTP URLs
                if not url.lower().startswith(('http://', 'https://')):
                    continue
                    
                # Resolve redirects to get the actual content URL
                resolved_url = self.resolve_redirect(url)
                
                # Skip if we couldn't get a valid content URL
                if not resolved_url:
                    continue
                    
                # Add to results
                result.append({
                    'url': resolved_url,
                    'title': title,
                    'original_url': url if resolved_url != url else None
                })
                
            except Exception as e:
                logger.error(f"Error processing link {link}: {e}", exc_info=True)
                
        return result
            
    def _is_ad_content(self, content, title):
        """Check if content looks like an advertisement."""
        # Check title first - quicker
        if title:
            for keyword in self.ad_keywords:
                if keyword.lower() in title.lower():
                    return True 