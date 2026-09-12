from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.i18n import Language


def utc_now() -> datetime:
    return datetime.now(UTC)


class MediaType(StrEnum):
    TEXT = "text"
    VIDEO = "video"
    PHOTO = "photo"
    DOCUMENT = "document"


class BroadcastStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BroadcastRecipientStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EngagementKind(StrEnum):
    RECIPE = "recipe"
    LESSON = "lesson"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(32))
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    language_code: Mapped[Language | None] = mapped_column(
        Enum(
            Language,
            native_enum=False,
            values_callable=lambda enum_type: [item.value for item in enum_type],
            length=2,
            create_constraint=True,
            name="language_code",
        )
    )
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscription_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscription_prompt_message_id: Mapped[int | None] = mapped_column(BigInteger)
    first_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_start_source: Mapped[str | None] = mapped_column(String(128))
    last_start_source: Mapped[str | None] = mapped_column(String(128))
    is_reachable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    unreachable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_chat_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    join_url: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class ContentOption(Base):
    __tablename__ = "content_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name_uz: Mapped[str] = mapped_column(String(64), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(64), nullable=False)
    name_en: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (Index("ix_content_options_active_order", "is_active", "sort_order", "id"),)


class OptionContentItem(Base):
    __tablename__ = "option_content_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    option_id: Mapped[int] = mapped_column(
        ForeignKey("content_options.id", ondelete="CASCADE"), nullable=False
    )
    telegram_file_id: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[MediaType] = mapped_column(
        Enum(
            MediaType,
            native_enum=False,
            values_callable=lambda enum_type: [item.value for item in enum_type],
            length=20,
        ),
        nullable=False,
    )
    original_filename: Mapped[str | None] = mapped_column(String(255))
    text_uz: Mapped[str] = mapped_column(Text, nullable=False)
    text_ru: Mapped[str] = mapped_column(Text, nullable=False)
    text_en: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (Index("ix_option_content_items_order", "option_id", "sort_order", "id"),)


class VideoLesson(Base):
    __tablename__ = "video_lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title_uz: Mapped[str] = mapped_column(String(64), nullable=False)
    title_ru: Mapped[str] = mapped_column(String(64), nullable=False)
    title_en: Mapped[str] = mapped_column(String(64), nullable=False)
    text_uz: Mapped[str] = mapped_column(Text, nullable=False)
    text_ru: Mapped[str] = mapped_column(Text, nullable=False)
    text_en: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (Index("ix_video_lessons_active_order", "is_active", "sort_order", "id"),)


class VideoLessonVideo(Base):
    __tablename__ = "video_lesson_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("video_lessons.id", ondelete="CASCADE"), nullable=False
    )
    telegram_file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(255))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (Index("ix_video_lesson_videos_order", "lesson_id", "sort_order", "id"),)


class EngagementEvent(Base):
    __tablename__ = "engagement_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[EngagementKind] = mapped_column(
        Enum(
            EngagementKind,
            native_enum=False,
            values_callable=lambda enum_type: [item.value for item in enum_type],
            length=20,
        ),
        nullable=False,
    )
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        Index("ix_engagement_events_kind_target", "kind", "target_id", "created_at"),
        Index("ix_engagement_events_user_kind", "user_id", "kind", "created_at"),
    )


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    admin_language: Mapped[Language] = mapped_column(
        Enum(
            Language,
            native_enum=False,
            values_callable=lambda enum_type: [item.value for item in enum_type],
            length=2,
        ),
        nullable=False,
    )
    media_type: Mapped[MediaType] = mapped_column(
        Enum(
            MediaType,
            native_enum=False,
            values_callable=lambda enum_type: [item.value for item in enum_type],
            length=20,
        ),
        nullable=False,
    )
    telegram_file_id: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(255))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    text_uz: Mapped[str] = mapped_column(Text, nullable=False)
    text_ru: Mapped[str] = mapped_column(Text, nullable=False)
    text_en: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[BroadcastStatus] = mapped_column(
        Enum(
            BroadcastStatus,
            native_enum=False,
            values_callable=lambda enum_type: [item.value for item in enum_type],
            length=20,
        ),
        default=BroadcastStatus.QUEUED,
        nullable=False,
    )
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_broadcasts_status_id", "status", "id"),)


class BroadcastRecipient(Base):
    __tablename__ = "broadcast_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broadcast_id: Mapped[int] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    language_code: Mapped[Language] = mapped_column(
        Enum(
            Language,
            native_enum=False,
            values_callable=lambda enum_type: [item.value for item in enum_type],
            length=2,
        ),
        nullable=False,
    )
    status: Mapped[BroadcastRecipientStatus] = mapped_column(
        Enum(
            BroadcastRecipientStatus,
            native_enum=False,
            values_callable=lambda enum_type: [item.value for item in enum_type],
            length=20,
        ),
        default=BroadcastRecipientStatus.PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("broadcast_id", "telegram_id", name="uq_broadcast_recipient"),
        Index(
            "ix_broadcast_recipients_work",
            "broadcast_id",
            "status",
            "next_attempt_at",
            "id",
        ),
    )
