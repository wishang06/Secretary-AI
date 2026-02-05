"""
SQLAlchemy Models for the Secretary AI Database

These models match the schema defined in database-erd.txt.
Uses async SQLAlchemy with PostgreSQL (asyncpg driver).
"""

from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Column,
    BigInteger,
    String,
    Text,
    Date,
    ForeignKey,
    TIMESTAMP,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class Committee(Base):
    """
    Committee members table.
    Stores information about all organization members.
    """
    __tablename__ = 'committee'
    __table_args__ = {'schema': 'public'}
    
    member_id = Column(BigInteger, primary_key=True, autoincrement=True)
    member_name = Column(String, nullable=True)
    discord_id = Column(BigInteger, nullable=True)
    discord_dm_channel_id = Column(BigInteger, nullable=True)
    subcommittee = Column(String, nullable=True)
    role = Column(String, nullable=True)
    email = Column(Text, nullable=True)
    ingestion_timestamp = Column(TIMESTAMP, nullable=False, server_default=func.now())
    
    # Relationships
    meeting_members = relationship("MeetingMembers", back_populates="member")
    project_members = relationship("ProjectMembers", back_populates="member")
    task_members = relationship("TaskMembers", back_populates="member")


class Meeting(Base):
    """
    Meetings table.
    Stores meeting metadata and summaries.
    """
    __tablename__ = 'meeting'
    __table_args__ = {'schema': 'public'}
    
    meeting_id = Column(BigInteger, primary_key=True, autoincrement=True)
    meeting_name = Column(String, nullable=False)
    meeting_type = Column(String, nullable=True)
    meeting_summary = Column(Text, nullable=True)
    ingestion_timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    meeting_members = relationship("MeetingMembers", back_populates="meeting")
    meeting_projects = relationship("MeetingProjects", back_populates="meeting")
    meeting_topics = relationship("MeetingTopics", back_populates="meeting")
    meeting_tasks = relationship("MeetingTasks", back_populates="meeting")


class MeetingMembers(Base):
    """
    Junction table linking meetings to members who attended.
    """
    __tablename__ = 'meeting_members'
    __table_args__ = {'schema': 'public'}
    
    meeting_id = Column(BigInteger, ForeignKey('public.meeting.meeting_id'), primary_key=True)
    member_id = Column(BigInteger, ForeignKey('public.committee.member_id'), primary_key=True)
    ingestion_timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    meeting = relationship("Meeting", back_populates="meeting_members")
    member = relationship("Committee", back_populates="meeting_members")


class Project(Base):
    """
    Projects table.
    Stores project information.
    """
    __tablename__ = 'projects'
    __table_args__ = {'schema': 'public'}
    
    project_id = Column(BigInteger, primary_key=True, autoincrement=True)
    project_name = Column(String, nullable=True)
    project_description = Column(Text, nullable=True)
    ingestion_timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    meeting_projects = relationship("MeetingProjects", back_populates="project")
    project_members = relationship("ProjectMembers", back_populates="project")
    project_tasks = relationship("ProjectTasks", back_populates="project")


class MeetingProjects(Base):
    """
    Junction table linking meetings to projects discussed.
    """
    __tablename__ = 'meeting_projects'
    __table_args__ = {'schema': 'public'}
    
    meeting_id = Column(BigInteger, ForeignKey('public.meeting.meeting_id'), primary_key=True)
    project_id = Column(BigInteger, ForeignKey('public.projects.project_id'), primary_key=True)
    ingestion_timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    meeting = relationship("Meeting", back_populates="meeting_projects")
    project = relationship("Project", back_populates="meeting_projects")


class ProjectMembers(Base):
    """
    Junction table linking projects to their team members.
    """
    __tablename__ = 'project_members'
    __table_args__ = {'schema': 'public'}
    
    project_id = Column(BigInteger, ForeignKey('public.projects.project_id'), primary_key=True)
    member_id = Column(BigInteger, ForeignKey('public.committee.member_id'), primary_key=True)
    ingestion_timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    project = relationship("Project", back_populates="project_members")
    member = relationship("Committee", back_populates="project_members")


class Topic(Base):
    """
    Topics table.
    Stores discussion topics that can be linked to meetings.
    """
    __tablename__ = 'topic'
    __table_args__ = {'schema': 'public'}
    
    topic_id = Column(BigInteger, primary_key=True, autoincrement=True)
    topic_name = Column(String, nullable=True)
    topic_description = Column(Text, nullable=True)
    ingestion_timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    meeting_topics = relationship("MeetingTopics", back_populates="topic")


class MeetingTopics(Base):
    """
    Junction table linking meetings to topics discussed.
    """
    __tablename__ = 'meeting_topics'
    __table_args__ = {'schema': 'public'}
    
    meeting_id = Column(BigInteger, ForeignKey('public.meeting.meeting_id'), primary_key=True)
    topic_id = Column(BigInteger, ForeignKey('public.topic.topic_id'), primary_key=True)
    ingestion_timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    meeting = relationship("Meeting", back_populates="meeting_topics")
    topic = relationship("Topic", back_populates="meeting_topics")


class Task(Base):
    """
    Tasks table.
    Stores tasks extracted from meetings with deadlines.
    """
    __tablename__ = 'tasks'
    __table_args__ = {'schema': 'public'}
    
    task_id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_name = Column(String, nullable=True)
    task_description = Column(Text, nullable=True)
    task_deadline = Column(Date, nullable=True)
    ingestion_timestamp = Column(TIMESTAMP, nullable=False, server_default=func.now())
    
    # Relationships
    meeting_tasks = relationship("MeetingTasks", back_populates="task")
    project_tasks = relationship("ProjectTasks", back_populates="task")
    task_members = relationship("TaskMembers", back_populates="task")


class MeetingTasks(Base):
    """
    Junction table linking meetings to tasks assigned during the meeting.
    """
    __tablename__ = 'meeting_tasks'
    __table_args__ = {'schema': 'public'}
    
    meeting_id = Column(BigInteger, ForeignKey('public.meeting.meeting_id'), primary_key=True)
    task_id = Column(BigInteger, ForeignKey('public.tasks.task_id'), primary_key=True)
    ingestion_timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    meeting = relationship("Meeting", back_populates="meeting_tasks")
    task = relationship("Task", back_populates="meeting_tasks")


class ProjectTasks(Base):
    """
    Junction table linking projects to their tasks.
    """
    __tablename__ = 'project_tasks'
    __table_args__ = {'schema': 'public'}
    
    project_id = Column(BigInteger, ForeignKey('public.projects.project_id'), primary_key=True)
    task_id = Column(BigInteger, ForeignKey('public.tasks.task_id'), primary_key=True)
    ingestion_timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    project = relationship("Project", back_populates="project_tasks")
    task = relationship("Task", back_populates="project_tasks")


class TaskMembers(Base):
    """
    Junction table linking tasks to assigned members.
    One task can be assigned to multiple members (creates multiple rows).
    """
    __tablename__ = 'task_members'
    __table_args__ = {'schema': 'public'}
    
    member_id = Column(BigInteger, ForeignKey('public.committee.member_id'), primary_key=True)
    task_id = Column(BigInteger, ForeignKey('public.tasks.task_id'), primary_key=True)
    ingestion_timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    member = relationship("Committee", back_populates="task_members")
    task = relationship("Task", back_populates="task_members")
