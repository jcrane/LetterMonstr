"""
Database models for LetterMonstr application.
"""

import os
import json
import logging
import time
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, text, Float
from sqlalchemy.orm import relationship, sessionmaker, declarative_base
import sqlite3
from sqlalchemy.exc import OperationalError

# Using declarative_base from sqlalchemy.orm instead of sqlalchemy.ext.declarative which is deprecated
Base = declarative_base()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProcessedEmail(Base):
    """Model for tracking processed emails."""
    __tablename__ = 'processed_emails'
    
    id = Column(Integer, primary_key=True)
    message_id = Column(String, unique=True, index=True)
    subject = Column(String)
    sender = Column(String)
    date_received = Column(DateTime)
    date_processed = Column(DateTime, default=datetime.now)
    is_read = Column(Boolean, default=False)
    
    # One-to-many relationships
    contents = relationship("EmailContent", back_populates="email", cascade="all, delete-orphan")
    content_items = relationship("ProcessedContent", back_populates="email")

class EmailContent(Base):
    """Model for storing content extracted from emails."""
    __tablename__ = 'email_contents'
    
    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, ForeignKey('processed_emails.id'))
    content_type = Column(String)  # 'html', 'text', 'raw'
    content = Column(Text)
    
    # Many-to-one relationship with email
    email = relationship("ProcessedEmail", back_populates="contents")
    
    # One-to-many relationship with links
    links = relationship("Link", back_populates="content", cascade="all, delete-orphan")
    
    def set_content(self, content_data):
        """Properly serialize content data before storing it"""
        if isinstance(content_data, dict):
            self.content = json.dumps(content_data)
        else:
            self.content = content_data
            
    def get_content(self):
        """Get content, deserializing if needed"""
        try:
            return json.loads(self.content)
        except (json.JSONDecodeError, TypeError):
            return self.content

class Link(Base):
    """Model for storing links found in email content."""
    __tablename__ = 'links'
    
    id = Column(Integer, primary_key=True)
    content_id = Column(Integer, ForeignKey('email_contents.id'))
    url = Column(String(1024))
    title = Column(String(255))
    crawled = Column(Boolean, default=False)
    date_crawled = Column(DateTime, nullable=True)
    
    # Many-to-one relationship with content
    content = relationship("EmailContent", back_populates="links")
    
    # One-to-one relationship with crawled content
    crawled_content = relationship("CrawledContent", uselist=False, back_populates="link", cascade="all, delete-orphan")

class CrawledContent(Base):
    """Model for storing content crawled from links."""
    __tablename__ = 'crawled_contents'
    
    id = Column(Integer, primary_key=True)
    link_id = Column(Integer, ForeignKey('links.id'), unique=True)
    title = Column(String(255))
    content = Column(Text)
    clean_content = Column(Text)
    is_ad = Column(Boolean, default=False)
    crawl_date = Column(DateTime, default=datetime.now)
    
    # One-to-one relationship with link
    link = relationship("Link", back_populates="crawled_content")

class Summary(Base):
    """Model for storing generated summaries."""
    __tablename__ = 'summaries'
    
    id = Column(Integer, primary_key=True)
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    summary_type = Column(String(50))  # e.g., 'daily', 'weekly', 'monthly'
    summary_text = Column(Text)
    creation_date = Column(DateTime, default=datetime.now)
    sent = Column(Boolean, default=False)
    sent_date = Column(DateTime, nullable=True)
    is_forced = Column(Boolean, default=False)  # Indicates if this was a forced/on-demand summary
    retry_count = Column(Integer, default=0)  # Number of retry attempts
    last_retry_time = Column(DateTime, nullable=True)  # When the last retry was attempted
    max_retries = Column(Integer, default=5)  # Maximum number of retry attempts
    error_message = Column(Text, nullable=True)  # Store the most recent error message

class ProcessedContent(Base):
    """Model for storing content that has been processed but not yet summarized."""
    __tablename__ = 'processed_content'
    
    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, ForeignKey('processed_emails.id'))
    content_type = Column(String)  # 'article', 'newsletter', etc.
    source = Column(String)
    title = Column(String)
    url = Column(String)
    processed_content = Column(Text)
    summary = Column(Text)
    date_processed = Column(DateTime, default=datetime.now)
    is_summarized = Column(Boolean, default=False)
    content_hash = Column(String)  # For deduplication
    email = relationship("ProcessedEmail", back_populates="content_items")
    summary_id = Column(Integer, ForeignKey('summaries.id'), nullable=True)  # Which summary included this content
    
    # Relationships
    summary = relationship("Summary", foreign_keys=[summary_id])
    
    def get_processed_content(self):
        """Retrieve the processed content, handling JSON serialization safely.
        
        Returns:
            dict or str: The processed content, properly deserialized if stored as JSON
        """
        if not self.processed_content:
            return {}
            
        # Try to deserialize JSON, but handle raw strings gracefully
        try:
            # First check if it's already a dict structure serialized to JSON
            content_data = json.loads(self.processed_content)
            
            # Handle the special case of our direct content structure
            if isinstance(content_data, dict) and 'content' in content_data and 'original_length' in content_data:
                # This is our direct content structure
                logger.info(f"Found direct content structure with {content_data.get('original_length', 0)} original chars")
                # Return the content field directly if it's substantial
                if len(content_data['content']) > 1000:
                    return content_data['content']
            
            return content_data
        except (json.JSONDecodeError, TypeError):
            # Not JSON, return the raw content
            logger.info(f"Returning raw content string: {len(self.processed_content)} chars")
            return self.processed_content
    
    def __repr__(self):
        return f"<ProcessedContent(id={self.id}, source='{self.source}', is_summarized={self.is_summarized})>"

class SummarizedContent(Base):
    """Model for tracking content that has been included in summaries to prevent duplicates."""
    __tablename__ = 'summarized_content_history'
    
    id = Column(Integer, primary_key=True)
    content_hash = Column(String(64), unique=True, nullable=False)
    content_title = Column(String(255))
    content_fingerprint = Column(Text)  # Store a representation of the content for matching
    summary_id = Column(Integer, ForeignKey('summaries.id'))
    date_summarized = Column(DateTime, default=datetime.now)
    
    # Relationship with the summary
    summary = relationship("Summary", back_populates="content_signatures")

# Add relationship to Summary model
Summary.content_signatures = relationship("SummarizedContent", back_populates="summary")

def get_engine(db_path=None):
    """Create database engine with proper settings."""
    if not db_path:
        # Use default path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # Create engine with improved SQLite settings for concurrency
    engine = create_engine(
        f'sqlite:///{db_path}',
        connect_args={
            'timeout': 60,  # Increase timeout for locks to 60 seconds
            'check_same_thread': False,  # Allow crossing thread boundaries
        },
        # Use valid SQLAlchemy isolation level
        isolation_level="SERIALIZABLE",  # Most conservative isolation level for data consistency
        pool_recycle=1800,  # Recycle connections after 30 minutes
        pool_pre_ping=True,  # Verify connections before use
        pool_size=5,  # Limit concurrent connections
        max_overflow=10  # Allow up to 10 overflow connections
    )
    
    # Set pragmas for better concurrency
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))  # Use WAL mode for better concurrency
        conn.execute(text("PRAGMA busy_timeout=60000"))  # 60 second busy timeout
        conn.execute(text("PRAGMA synchronous=NORMAL"))  # Balances safety and performance
        conn.execute(text("PRAGMA temp_store=MEMORY"))  # Store temp tables in memory
        conn.execute(text("PRAGMA cache_size=10000"))  # Larger cache (about 10MB)
    
    return engine

def get_session(db_path=None):
    """Get a database session with retry logic for lock errors."""
    engine = get_engine(db_path)
    Session = sessionmaker(bind=engine)
    
    # Initial attempt
    max_retries = 5
    retry_count = 0
    retry_delay = 1  # Start with 1 second delay
    last_error = None
    
    while retry_count < max_retries:
        try:
            session = Session()
            # Test the connection with a simple query
            session.execute(text("SELECT 1"))
            return session
        except OperationalError as e:
            if "database is locked" in str(e) and retry_count < max_retries - 1:
                retry_count += 1
                logger.warning(f"Database locked, retrying in {retry_delay} seconds (attempt {retry_count}/{max_retries})")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                last_error = e
            else:
                # Re-raise if it's not a lock error or we've exhausted retries
                logger.error(f"Database error after {retry_count} retries: {e}")
                raise
    
    # If we get here, we've exhausted retries
    if last_error:
        raise last_error
    else:
        raise OperationalError("Failed to acquire database connection after maximum retries", None, None)

def init_db(db_path):
    """Initialize the database."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    
    logger.info(f"Database initialized at {db_path}")
    
    # Return the engine for session creation
    return engine

# Create tables if needed and return engine - for testing and initial setup
def setup_db():
    """Setup database for initial use."""
    # Use the default path
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    
    # Initialize and return engine
    return init_db(db_path) 