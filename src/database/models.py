"""
Database models for LetterMonstr application.
"""

import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, text
from sqlalchemy.orm import relationship, sessionmaker, declarative_base
import sqlite3

# Using declarative_base from sqlalchemy.orm instead of sqlalchemy.ext.declarative which is deprecated
Base = declarative_base()

class ProcessedEmail(Base):
    """Model for tracking processed emails."""
    __tablename__ = 'processed_emails'
    
    id = Column(Integer, primary_key=True)
    message_id = Column(String(255), unique=True, nullable=False)
    subject = Column(String(255))
    sender = Column(String(255))
    date_received = Column(DateTime)
    date_processed = Column(DateTime, default=datetime.now)
    
    # One-to-many relationship with content
    contents = relationship("EmailContent", back_populates="email", cascade="all, delete-orphan")

class EmailContent(Base):
    """Model for storing content extracted from emails."""
    __tablename__ = 'email_contents'
    
    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, ForeignKey('processed_emails.id'))
    content_type = Column(String(50))  # e.g., 'text', 'html', 'attachment'
    content = Column(Text)
    
    # Many-to-one relationship with email
    email = relationship("ProcessedEmail", back_populates="contents")
    
    # One-to-many relationship with links
    links = relationship("Link", back_populates="content", cascade="all, delete-orphan")

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
    content_hash = Column(String(64), index=True, unique=True)  # For deduplication
    email_id = Column(Integer, ForeignKey('processed_emails.id'), nullable=True)
    source = Column(String(255))  # Where the content came from (email subject, URL, etc.)
    content_type = Column(String(50))  # 'email', 'crawled', 'combined', etc.
    raw_content = Column(Text)  # Original content
    processed_content = Column(Text)  # Processed and cleaned content
    content_metadata = Column(Text)  # Store additional metadata as JSON
    date_processed = Column(DateTime, default=datetime.now)
    summarized = Column(Boolean, default=False)  # Whether it's been included in a summary
    summary_id = Column(Integer, ForeignKey('summaries.id'), nullable=True)  # Which summary included this content
    
    # Relationships
    email = relationship("ProcessedEmail", foreign_keys=[email_id])
    summary = relationship("Summary", foreign_keys=[summary_id])
    
    def __repr__(self):
        return f"<ProcessedContent(id={self.id}, source='{self.source}', summarized={self.summarized})>"

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