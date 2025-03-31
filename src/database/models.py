"""
Database models for LetterMonstr application.
"""

import os
import json
import logging
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, text, Float
from sqlalchemy.orm import relationship, sessionmaker, declarative_base
import sqlite3

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

def init_db(db_path):
    """Initialize the database."""
    # Ensure data directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # First set the SQLite pragmas using direct connection
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Configure for better concurrency and performance
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=120000;")  # 120 seconds (2 minutes)
    cursor.execute("PRAGMA temp_store=MEMORY;")
    cursor.execute("PRAGMA cache_size=-40000;")  # About 40MB
    cursor.execute("PRAGMA foreign_keys=ON;")
    conn.commit()
    conn.close()
    
    # Create engine with improved connection settings for concurrent access
    engine = create_engine(
        f'sqlite:///{db_path}', 
        connect_args={
            "check_same_thread": False,
            "timeout": 120  # 120 seconds timeout for locked database
        },
        isolation_level="SERIALIZABLE"  # Ensures transaction integrity
    )
    
    # Create tables
    Base.metadata.create_all(engine)
    
    # Create session factory
    Session = sessionmaker(bind=engine)
    
    return Session

def get_session(db_path):
    """Get a new database session."""
    # Import text function here to avoid circular imports
    from sqlalchemy import text
    
    Session = init_db(db_path)
    session = Session()
    
    # Double-check that settings are applied in this specific session
    session.execute(text("PRAGMA journal_mode=WAL;"))  # Write-Ahead Logging for better concurrency
    session.execute(text("PRAGMA synchronous=NORMAL;"))  # Faster with reasonable safety
    session.execute(text("PRAGMA busy_timeout=120000;"))  # 120 seconds (2 minutes)
    session.execute(text("PRAGMA temp_store=MEMORY;"))  # Keep temporary tables in memory
    session.execute(text("PRAGMA cache_size=-40000;"))  # About 40MB for caching
    session.execute(text("PRAGMA foreign_keys=ON;"))  # Enforce foreign key constraints
    session.execute(text("PRAGMA locking_mode=NORMAL;"))  # Allow multiple readers
    
    return session 