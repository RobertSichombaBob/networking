# models.py
# -----------------------------------------------------------------------------
# DERIV.ED — Product-grade social + job matching platform (LinkedIn-class core)
#
# GOALS:
# - Strong trust + moderation + auditability
# - Predictable state machines + constraints
# - Scale-friendly: counters, indexes, denormalized search indexes
# - Matching pipeline support: indexing + embeddings + match results + work queue
# - Social: posts, comments, likes, follows, connections, blocking, reporting
# - Messaging: direct & group conversations, delivery/read receipts (per user)
# - Ads: campaigns, creatives, events (impression/click), simple budget tracking
# - Security: login attempts, device sessions, verification codes
#
# REQUIRED SETTINGS:
#   AUTH_USER_MODEL = "portfolio.CustomUser"   # replace `portfolio` with your app label
#
# DB RECOMMENDATION:
#   PostgreSQL (for conditional unique constraints, performance, JSON querying).
#
# NOTE ON EMBEDDINGS:
# - This file uses BinaryField placeholders for embeddings.
# - If you use pgvector, replace BinaryField with VectorField.
# -----------------------------------------------------------------------------

from __future__ import annotations

import uuid
import hashlib
from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator, URLValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q, F
from django.utils import timezone
from django.utils.text import slugify


# =============================================================================
# HELPERS
# =============================================================================

def now_plus(hours: int = 0, minutes: int = 0) -> timezone.datetime:
    return timezone.now() + timedelta(hours=hours, minutes=minutes)


def unique_slugify(instance: models.Model, value: str, slug_field: str = "slug", max_len: int = 240) -> str:
    base = (slugify(value) or "item")[:max_len].strip("-") or "item"
    slug = base
    Model = instance.__class__
    i = 2
    while Model.objects.filter(**{slug_field: slug}).exclude(pk=getattr(instance, "pk", None)).exists():
        suffix = f"-{i}"
        slug = (base[: max_len - len(suffix)].strip("-") or "item") + suffix
        i += 1
    setattr(instance, slug_field, slug)
    return slug


def stable_hash(value: str) -> str:
    # Use for IP hashing / privacy-safe indexing (never store raw IP)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# =============================================================================
# BASE ABSTRACT MODELS
# =============================================================================

class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDPk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class SoftDelete(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        abstract = True

    def soft_delete(self, *, save: bool = True):
        if not self.is_deleted:
            self.is_deleted = True
            self.deleted_at = timezone.now()
            if save:
                self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])


class Moderation(models.Model):
    class ModerationStatus(models.TextChoices):
        OK = "ok", "OK"
        UNDER_REVIEW = "under_review", "Under review"
        REMOVED = "removed", "Removed"

    moderation_status = models.CharField(
        max_length=20,
        choices=ModerationStatus.choices,
        default=ModerationStatus.OK,
        db_index=True,
    )
    moderation_reason = models.CharField(max_length=240, blank=True)

    class Meta:
        abstract = True

    def require_review(self, reason: str = ""):
        self.moderation_status = self.ModerationStatus.UNDER_REVIEW
        self.moderation_reason = (reason or "")[:240]
        self.save(update_fields=["moderation_status", "moderation_reason", "updated_at"])

    def remove(self, reason: str = ""):
        self.moderation_status = self.ModerationStatus.REMOVED
        self.moderation_reason = (reason or "")[:240]
        self.save(update_fields=["moderation_status", "moderation_reason", "updated_at"])

    @property
    def is_removed(self) -> bool:
        return self.moderation_status == self.ModerationStatus.REMOVED


# =============================================================================
# USER (EMAIL-FIRST) + TRUST
# =============================================================================

class CustomUserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("Email must be set.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
            user.last_password_change_at = timezone.now()
        else:
            user.set_unusable_password()
        user.full_clean()
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", CustomUser.Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class CustomUser(AbstractUser, UUIDPk, TimeStamped):
    """
    Email-first login, username removed for trust + predictable UX.
    Includes account safety, privacy controls, and platform role.
    """
    class Role(models.TextChoices):
        JOB_SEEKER = "job_seeker", "Job Seeker"
        EMPLOYER = "employer", "Employer"
        ADMIN = "admin", "Administrator"
        VISITOR = "visitor", "Visitor"

    username = None  # remove username entirely
    email = models.EmailField("email address", unique=True)

    phone = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        validators=[RegexValidator(r"^[0-9+\-\s()]{6,32}$", "Invalid phone format.")],
    )

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VISITOR, db_index=True)

    # Verification / trust
    email_verified = models.BooleanField(default=False, db_index=True)
    phone_verified = models.BooleanField(default=False, db_index=True)

    # Professional headline
    headline = models.CharField(max_length=200, blank=True)
    current_position = models.CharField(max_length=200, blank=True)

    # Privacy / safety
    is_profile_public = models.BooleanField(default=True, db_index=True)
    allow_messages_from = models.CharField(
        max_length=20,
        choices=[("everyone", "Everyone"), ("connections", "Connections"), ("none", "No one")],
        default="connections",
        db_index=True,
    )

    # Account safety
    failed_login_count = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(blank=True, null=True)
    last_password_change_at = models.DateTimeField(blank=True, null=True)

    # Preferences (notifications, UI, etc.)
    preferences = models.JSONField(default=dict, blank=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        constraints = [
            models.UniqueConstraint(
                fields=["phone"],
                condition=Q(phone__isnull=False) & ~Q(phone=""),
                name="uniq_phone_when_present",
            ),
        ]
        indexes = [
            models.Index(fields=["role", "email_verified"]),
            models.Index(fields=["locked_until"]),
        ]

    def __str__(self):
        return f"{self.email} ({self.role})"

    def display_name(self) -> str:
        full = (f"{self.first_name} {self.last_name}").strip()
        return full or self.email.split("@")[0]

    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > timezone.now())

    def lock_for_minutes(self, minutes: int = 15):
        self.locked_until = now_plus(minutes=minutes)
        self.save(update_fields=["locked_until", "updated_at"])

    def can_receive_dm_from(self, sender: "CustomUser") -> bool:
        if self.allow_messages_from == "everyone":
            return True
        if self.allow_messages_from == "none":
            return False
        if sender == self:
            return True
        if self.allow_messages_from == "connections":
            return Connection.objects.filter(
                Q(from_user=sender, to_user=self, status=Connection.Status.ACCEPTED) |
                Q(from_user=self, to_user=sender, status=Connection.Status.ACCEPTED)
            ).exists()
        return False


class UserProfile(UUIDPk, TimeStamped):
    """
    Extended profile information for both job seekers and employers (personal info).
    Employer company identity should use Company/EmployerProfile below.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")

    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    cover_image = models.ImageField(upload_to="covers/", blank=True, null=True)

    location = models.CharField(max_length=120, blank=True)
    website = models.URLField(blank=True, validators=[URLValidator()])
    linkedin = models.URLField(blank=True)
    github = models.URLField(blank=True)
    twitter = models.URLField(blank=True)

    # Job seeker preferences
    open_to_work = models.BooleanField(default=True, db_index=True)
    open_to_relocation = models.BooleanField(default=False)
    preferred_job_types = models.JSONField(default=list, blank=True)     # ["full_time", "remote", ...]
    preferred_locations = models.JSONField(default=list, blank=True)    # ["Lusaka", "Remote", ...]

    resume = models.FileField(upload_to="resumes/", blank=True, null=True)

    def __str__(self):
        return f"Profile: {self.user.display_name()}"


# =============================================================================
# COMPANY + EMPLOYER TRUST
# =============================================================================

class Company(UUIDPk, TimeStamped, Moderation):
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    website = models.URLField(blank=True)
    industry = models.CharField(max_length=120, blank=True)
    size = models.CharField(max_length=50, blank=True)  # e.g., 1-10, 11-50...
    logo = models.ImageField(upload_to="companies/logos/", blank=True, null=True)

    is_verified = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            unique_slugify(self, self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class EmployerProfile(UUIDPk, TimeStamped):
    """
    Employer identity & permissions for a user who hires.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employer_profile")
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, related_name="team")
    title = models.CharField(max_length=120, blank=True)
    is_company_admin = models.BooleanField(default=False, db_index=True)

    verification_notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.display_name()} @ {self.company.name if self.company else 'No company'}"


class CompanyVerification(UUIDPk, TimeStamped):
    """
    Verification workflow for companies (docs, reviewer, status).
    """
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="verifications")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="company_verifications_submitted")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED, db_index=True)

    document = models.FileField(upload_to="companies/verification_docs/", blank=True, null=True)
    notes = models.TextField(blank=True)

    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="company_verifications_reviewed")
    reviewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=["status", "created_at"])]

    def approve(self, reviewer: CustomUser):
        self.status = self.Status.VERIFIED
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
        Company.objects.filter(pk=self.company_id).update(is_verified=True)

    def reject(self, reviewer: CustomUser, notes: str = ""):
        self.status = self.Status.REJECTED
        self.notes = (notes or "") + (("\n" + self.notes) if self.notes else "")
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save(update_fields=["status", "notes", "reviewed_by", "reviewed_at", "updated_at"])


# =============================================================================
# SKILLS & ENDORSEMENTS
# =============================================================================

class Skill(UUIDPk, TimeStamped):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slugify(self, self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class UserSkill(UUIDPk, TimeStamped):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="skills")
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="users")

    endorsement_count = models.PositiveIntegerField(default=0, db_index=True)
    level = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(5)])  # self-rated (optional)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "skill"], name="uniq_user_skill"),
        ]
        indexes = [
            models.Index(fields=["user", "-endorsement_count"]),
            models.Index(fields=["skill", "-endorsement_count"]),
        ]

    def __str__(self):
        return f"{self.user.display_name()} - {self.skill.name}"


class Endorsement(UUIDPk, TimeStamped):
    endorser = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="endorsements_given")
    user_skill = models.ForeignKey(UserSkill, on_delete=models.CASCADE, related_name="endorsements")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["endorser", "user_skill"], name="uniq_endorsement"),
        ]

    def clean(self):
        if self.endorser_id == self.user_skill.user_id:
            raise ValidationError("You cannot endorse yourself.")

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        self.full_clean()
        super().save(*args, **kwargs)
        if is_new:
            UserSkill.objects.filter(pk=self.user_skill_id).update(endorsement_count=F("endorsement_count") + 1)

    def delete(self, *args, **kwargs):
        UserSkill.objects.filter(pk=self.user_skill_id, endorsement_count__gt=0).update(endorsement_count=F("endorsement_count") - 1)
        super().delete(*args, **kwargs)


# =============================================================================
# EXPERIENCE & EDUCATION
# =============================================================================

class Experience(UUIDPk, TimeStamped):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="experiences")

    title = models.CharField(max_length=200)
    company = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)

    is_current = models.BooleanField(default=False, db_index=True)
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)

    description = models.TextField(blank=True)
    media = models.FileField(upload_to="experience/", blank=True, null=True)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(check=Q(is_current=True) | Q(end_date__isnull=False), name="chk_experience_end_date_if_not_current"),
            models.CheckConstraint(check=Q(end_date__isnull=True) | Q(end_date__gt=F("start_date")), name="chk_experience_end_gt_start"),
        ]
        indexes = [models.Index(fields=["user", "-start_date"])]

    def clean(self):
        if self.is_current and self.end_date:
            raise ValidationError("End date should be empty for current position.")
        if not self.is_current and not self.end_date:
            raise ValidationError("End date is required for past positions.")
        if self.end_date and self.end_date <= self.start_date:
            raise ValidationError("End date must be after start date.")

    def __str__(self):
        return f"{self.title} at {self.company}"


class Education(UUIDPk, TimeStamped):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="education")

    school = models.CharField(max_length=200)
    degree = models.CharField(max_length=200)
    field_of_study = models.CharField(max_length=200, blank=True)
    grade = models.CharField(max_length=50, blank=True)

    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    is_current = models.BooleanField(default=False, db_index=True)

    description = models.TextField(blank=True)
    activities = models.TextField(blank=True)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(check=Q(is_current=True) | Q(end_date__isnull=False), name="chk_education_end_date_if_not_current"),
            models.CheckConstraint(check=Q(end_date__isnull=True) | Q(end_date__gt=F("start_date")), name="chk_education_end_gt_start"),
        ]
        indexes = [models.Index(fields=["user", "-start_date"])]

    def clean(self):
        if self.is_current and self.end_date:
            raise ValidationError("End date should be empty for current education.")
        if not self.is_current and not self.end_date:
            raise ValidationError("End date is required for completed education.")
        if self.end_date and self.end_date <= self.start_date:
            raise ValidationError("End date must be after start date.")

    def __str__(self):
        return f"{self.degree} at {self.school}"


# =============================================================================
# NETWORKING (CONNECTIONS + FOLLOW)
# =============================================================================

class Connection(UUIDPk, TimeStamped):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        BLOCKED = "blocked", "Blocked"

    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="connection_requests_sent")
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="connection_requests_received")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["from_user", "to_user"], name="uniq_connection"),
            models.CheckConstraint(check=~Q(from_user=F("to_user")), name="chk_no_self_connection"),
        ]
        indexes = [models.Index(fields=["to_user", "status"])]

    def clean(self):
        if Block.objects.filter(
            Q(blocker=self.from_user, blocked=self.to_user) | Q(blocker=self.to_user, blocked=self.from_user)
        ).exists():
            raise ValidationError("Cannot connect with a blocked user.")

    def accept(self):
        if self.status != self.Status.PENDING:
            return
        self.status = self.Status.ACCEPTED
        self.save(update_fields=["status", "updated_at"])
        Notification.create_social(self.to_user, "Connection accepted", f"{self.from_user.display_name()} accepted your connection request.", target=self)

    def decline(self):
        if self.status == self.Status.PENDING:
            self.status = self.Status.DECLINED
            self.save(update_fields=["status", "updated_at"])


class Follow(UUIDPk, TimeStamped):
    follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="following")
    following = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="followers")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["follower", "following"], name="uniq_follow"),
            models.CheckConstraint(check=~Q(follower=F("following")), name="chk_no_self_follow"),
        ]
        indexes = [
            models.Index(fields=["following", "-created_at"]),
        ]


# =============================================================================
# TRUST: BLOCKING + REPORTING
# =============================================================================

class Block(UUIDPk, TimeStamped):
    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_initiated")
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_received")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="uniq_block"),
            models.CheckConstraint(check=~Q(blocker=F("blocked")), name="chk_no_self_block"),
        ]
        indexes = [models.Index(fields=["blocked", "created_at"])]

    def __str__(self):
        return f"{self.blocker.email} blocked {self.blocked.email}"


class Report(UUIDPk, TimeStamped):
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports")

    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    target = GenericForeignKey("content_type", "object_id")

    reason = models.CharField(max_length=200)
    details = models.TextField(blank=True)

    is_resolved = models.BooleanField(default=False, db_index=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reports_resolved")
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=["is_resolved", "-created_at"])]

    def resolve(self, resolver: CustomUser):
        self.is_resolved = True
        self.resolved_by = resolver
        self.resolved_at = timezone.now()
        self.save(update_fields=["is_resolved", "resolved_by", "resolved_at", "updated_at"])


# =============================================================================
# POSTS / COMMENTS / LIKES
# =============================================================================

class Post(UUIDPk, TimeStamped, SoftDelete, Moderation):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        CONNECTIONS = "connections", "Connections"
        PRIVATE = "private", "Private"

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="posts")

    content = models.TextField(blank=True)
    media = models.FileField(upload_to="posts/media/", blank=True, null=True)

    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.PUBLIC, db_index=True)
    tags = models.JSONField(default=list, blank=True)

    like_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["author", "-created_at"]),
            models.Index(fields=["visibility", "-created_at"]),
            models.Index(fields=["moderation_status", "is_deleted"]),
        ]

    def clean(self):
        if self.visibility == self.Visibility.PRIVATE and not (self.content.strip() or self.media):
            raise ValidationError("Private post cannot be empty.")
        if not (self.content.strip() or self.media):
            raise ValidationError("Post cannot be empty.")

    def can_view(self, user: CustomUser | None) -> bool:
        if self.is_deleted or self.is_removed:
            return False
        if self.visibility == self.Visibility.PUBLIC:
            return True
        if user is None or not user.is_authenticated:
            return False
        if Block.objects.filter(Q(blocker=self.author, blocked=user) | Q(blocker=user, blocked=self.author)).exists():
            return False
        if user == self.author:
            return True
        if self.visibility == self.Visibility.PRIVATE:
            return False
        if self.visibility == self.Visibility.CONNECTIONS:
            return Connection.objects.filter(
                Q(from_user=user, to_user=self.author, status=Connection.Status.ACCEPTED) |
                Q(from_user=self.author, to_user=user, status=Connection.Status.ACCEPTED)
            ).exists()
        return False


class PostLike(UUIDPk, TimeStamped):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_likes")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["post", "user"], name="uniq_post_like"),
        ]
        indexes = [models.Index(fields=["post", "-created_at"])]

    @staticmethod
    def like(post: Post, user: CustomUser):
        if not post.can_view(user):
            raise ValidationError("You cannot like a post you cannot view.")
        obj, created = PostLike.objects.get_or_create(post=post, user=user)
        if created:
            Post.objects.filter(pk=post.pk).update(like_count=F("like_count") + 1)
            if post.author_id != user.id:
                Notification.create_social(post.author, "New like", f"{user.display_name()} liked your post.", target=post)
        return obj

    @staticmethod
    def unlike(post: Post, user: CustomUser):
        deleted, _ = PostLike.objects.filter(post=post, user=user).delete()
        if deleted:
            Post.objects.filter(pk=post.pk, like_count__gt=0).update(like_count=F("like_count") - 1)


class PostComment(UUIDPk, TimeStamped, SoftDelete, Moderation):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_comments")
    content = models.TextField()
    parent = models.ForeignKey("self", on_delete=models.CASCADE, blank=True, null=True, related_name="replies")

    class Meta:
        indexes = [
            models.Index(fields=["post", "parent", "created_at"]),
            models.Index(fields=["moderation_status", "is_deleted"]),
        ]

    def clean(self):
        if not self.content or not self.content.strip():
            raise ValidationError("Comment cannot be empty.")
        if self.parent and self.parent.post_id != self.post_id:
            raise ValidationError("Reply must belong to the same post.")
        # The author must be able to view the post
        if not self.post.can_view(self.author):
            raise ValidationError("You cannot comment on a post you cannot view.")

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        self.full_clean()
        super().save(*args, **kwargs)
        if is_new:
            Post.objects.filter(pk=self.post_id).update(comment_count=F("comment_count") + 1)
            if self.post.author_id != self.author_id:
                Notification.create_social(self.post.author, "New comment", f"{self.author.display_name()} commented on your post.", target=self.post)

    def soft_delete(self, *, save: bool = True):
        if not self.is_deleted:
            super().soft_delete(save=save)
            Post.objects.filter(pk=self.post_id, comment_count__gt=0).update(comment_count=F("comment_count") - 1)


# =============================================================================
# MESSAGING
# =============================================================================

class Conversation(UUIDPk, TimeStamped):
    """
    - direct_key enables dedupe of 1:1 conversations (same pair -> one thread)
    - For group chats, direct_key stays blank.
    """
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="conversations")
    is_group = models.BooleanField(default=False, db_index=True)
    title = models.CharField(max_length=200, blank=True)
    last_message_at = models.DateTimeField(blank=True, null=True, db_index=True)

    # Store "minUUID:maxUUID" for direct conversations (set by service method)
    direct_key = models.CharField(max_length=80, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_group", "-last_message_at"]),
        ]
        constraints = [
            # PostgreSQL supports conditional unique constraints; SQLite will ignore condition.
            models.UniqueConstraint(
                fields=["direct_key"],
                condition=Q(is_group=False) & ~Q(direct_key=""),
                name="uniq_direct_conversation_key",
            ),
        ]

    def touch(self):
        self.last_message_at = timezone.now()
        self.save(update_fields=["last_message_at", "updated_at"])

    def can_participate(self, user: CustomUser) -> bool:
        return self.participants.filter(pk=user.pk).exists()

    @staticmethod
    def build_direct_key(user_a_id: uuid.UUID, user_b_id: uuid.UUID) -> str:
        a, b = sorted([str(user_a_id), str(user_b_id)])
        return f"{a}:{b}"

    @classmethod
    def get_or_create_direct(cls, user_a: CustomUser, user_b: CustomUser):
        if user_a.id == user_b.id:
            raise ValidationError("Cannot create a direct conversation with yourself.")
        direct_key = cls.build_direct_key(user_a.id, user_b.id)
        with transaction.atomic():
            obj, created = cls.objects.get_or_create(is_group=False, direct_key=direct_key)
            if created:
                obj.save()
                obj.participants.add(user_a, user_b)
        return obj


class DirectMessage(UUIDPk, TimeStamped, SoftDelete, Moderation):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages")

    content = models.TextField(blank=True)
    attachment = models.FileField(upload_to="messages/attachments/", blank=True, null=True)

    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(blank=True, null=True)

    # Abuse signal (your safety agent can update this)
    spam_score = models.PositiveSmallIntegerField(default=0, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["moderation_status", "is_deleted"]),
            models.Index(fields=["sender", "-created_at"]),
        ]

    def clean(self):
        if not (self.content and self.content.strip()) and not self.attachment:
            raise ValidationError("Message cannot be empty.")
        if not self.conversation.can_participate(self.sender):
            raise ValidationError("Sender is not a participant of this conversation.")

    @staticmethod
    def send(conversation: Conversation, sender: CustomUser, content: str = "", attachment=None):
        if not conversation.can_participate(sender):
            raise ValidationError("You cannot send messages in a conversation you're not in.")

        participant_ids = list(conversation.participants.values_list("id", flat=True))

        # Block rules
        if Block.objects.filter(blocker_id__in=participant_ids, blocked=sender).exists():
            raise ValidationError("You cannot message this user.")
        if Block.objects.filter(blocker=sender, blocked_id__in=participant_ids).exists():
            raise ValidationError("You cannot message a blocked user.")

        # Recipient preference for 1:1 (message requests rule)
        if not conversation.is_group and len(participant_ids) == 2:
            recipient = conversation.participants.exclude(pk=sender.pk).first()
            if recipient and not recipient.can_receive_dm_from(sender):
                raise ValidationError("This user does not accept messages from you.")

        msg = DirectMessage.objects.create(conversation=conversation, sender=sender, content=content, attachment=attachment)
        conversation.touch()

        # Create delivery rows for participants (for read receipts / inbox queries)
        deliveries = []
        for p_id in participant_ids:
            deliveries.append(MessageDelivery(message=msg, user_id=p_id))
        MessageDelivery.objects.bulk_create(deliveries, ignore_conflicts=True)

        # Notify others
        for p in conversation.participants.exclude(pk=sender.pk):
            Notification.create_social(p, "New message", f"New message from {sender.display_name()}.", target=conversation)

        return msg

    def edit(self, editor: CustomUser, new_content: str):
        if editor.id != self.sender_id:
            raise ValidationError("Only the sender can edit a message.")
        if self.is_deleted or self.is_removed:
            raise ValidationError("Cannot edit a deleted/removed message.")
        if not new_content.strip():
            raise ValidationError("Edited message cannot be empty.")
        self.content = new_content
        self.is_edited = True
        self.edited_at = timezone.now()
        self.save(update_fields=["content", "is_edited", "edited_at", "updated_at"])


class MessageDelivery(UUIDPk, TimeStamped):
    """
    Per-user delivery/read status (scales better than M2M read_by).
    """
    message = models.ForeignKey(DirectMessage, on_delete=models.CASCADE, related_name="deliveries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="message_deliveries")

    delivered_at = models.DateTimeField(blank=True, null=True, db_index=True)
    read_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["message", "user"], name="uniq_message_delivery"),
        ]
        indexes = [
            models.Index(fields=["user", "read_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def mark_delivered(self):
        if not self.delivered_at:
            self.delivered_at = timezone.now()
            self.save(update_fields=["delivered_at", "updated_at"])

    def mark_read(self):
        if not self.read_at:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at", "updated_at"])


# =============================================================================
# NOTIFICATIONS
# =============================================================================

class Notification(UUIDPk, TimeStamped):
    class Type(models.TextChoices):
        SYSTEM = "system", "System"
        SOCIAL = "social", "Social"
        JOB = "job", "Job"
        APPLICATION = "application", "Application"
        MESSAGE = "message", "Message"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    notif_type = models.CharField(max_length=20, choices=Type.choices, default=Type.SYSTEM, db_index=True)

    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)

    target_content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    target_object_id = models.CharField(max_length=64, blank=True)
    target = GenericForeignKey("target_content_type", "target_object_id")

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(blank=True, null=True)

    priority = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(5)])

    class Meta:
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"]),
            models.Index(fields=["notif_type", "-created_at"]),
        ]

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at", "updated_at"])

    @classmethod
    def _create(cls, recipient: CustomUser, notif_type: str, title: str, body: str, target=None, priority: int = 3):
        prefs = recipient.preferences or {}
        disabled = set(prefs.get("notifications_disabled_types", []))
        if notif_type in disabled:
            return None
        return cls.objects.create(
            recipient=recipient,
            notif_type=notif_type,
            title=title[:200],
            body=body,
            target=target,
            priority=priority,
        )

    @classmethod
    def create_social(cls, recipient: CustomUser, title: str, body: str, target=None):
        return cls._create(recipient, cls.Type.SOCIAL, title, body, target=target)

    @classmethod
    def create_job(cls, recipient: CustomUser, title: str, body: str, target=None):
        return cls._create(recipient, cls.Type.JOB, title, body, target=target)

    @classmethod
    def create_application(cls, recipient: CustomUser, title: str, body: str, target=None):
        return cls._create(recipient, cls.Type.APPLICATION, title, body, target=target)


# =============================================================================
# EVENT LOG (AUDIT / ANALYTICS)
# =============================================================================

class EventLog(UUIDPk, TimeStamped):
    class Event(models.TextChoices):
        SIGNUP = "signup", "Signup"
        LOGIN = "login", "Login"
        VIEW_PROFILE = "view_profile", "View Profile"
        VIEW_JOB = "view_job", "View Job"
        APPLY_JOB = "apply_job", "Apply Job"
        SAVE_JOB = "save_job", "Save Job"
        POST_CREATED = "post_created", "Post Created"
        CONNECTION_REQUEST = "connection_request", "Connection Request"
        MESSAGE_SENT = "message_sent", "Message Sent"
        PAYMENT = "payment", "Payment"
        AD_IMPRESSION = "ad_impression", "Ad impression"
        AD_CLICK = "ad_click", "Ad click"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    event = models.CharField(max_length=50, choices=Event.choices, db_index=True)

    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    obj = GenericForeignKey("content_type", "object_id")

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["event", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]


# =============================================================================
# JOBS & APPLICATIONS
# =============================================================================

class Job(UUIDPk, TimeStamped, SoftDelete, Moderation):
    class EmploymentType(models.TextChoices):
        FULL_TIME = "full_time", "Full-time"
        PART_TIME = "part_time", "Part-time"
        CONTRACT = "contract", "Contract"
        INTERNSHIP = "internship", "Internship"
        TEMPORARY = "temporary", "Temporary"
        VOLUNTEER = "volunteer", "Volunteer"

    class ExperienceLevel(models.TextChoices):
        ENTRY = "entry", "Entry level"
        MID = "mid", "Mid level"
        SENIOR = "senior", "Senior level"
        LEAD = "lead", "Lead / Manager"
        EXECUTIVE = "executive", "Executive"

    class RemoteStatus(models.TextChoices):
        ONSITE = "onsite", "On-site"
        HYBRID = "hybrid", "Hybrid"
        REMOTE = "remote", "Remote"

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)

    employer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="jobs_posted",
        limit_choices_to=Q(role=CustomUser.Role.EMPLOYER) | Q(role=CustomUser.Role.ADMIN),
    )

    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs")

    description = models.TextField()
    responsibilities = models.TextField(blank=True)
    requirements = models.TextField(blank=True)
    benefits = models.TextField(blank=True)

    employment_type = models.CharField(max_length=20, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME)
    experience_level = models.CharField(max_length=20, choices=ExperienceLevel.choices, default=ExperienceLevel.MID)
    remote_status = models.CharField(max_length=20, choices=RemoteStatus.choices, default=RemoteStatus.ONSITE)

    location = models.CharField(max_length=200)
    location_country = models.CharField(max_length=100, blank=True, db_index=True)
    location_city = models.CharField(max_length=100, blank=True, db_index=True)

    salary_min = models.PositiveIntegerField(blank=True, null=True)
    salary_max = models.PositiveIntegerField(blank=True, null=True)
    salary_currency = models.CharField(max_length=10, default="ZMW")
    salary_visible = models.BooleanField(default=True)

    skills_required = models.ManyToManyField(Skill, blank=True, related_name="jobs")

    application_deadline = models.DateTimeField(blank=True, null=True)
    external_application_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    views = models.PositiveIntegerField(default=0)
    applications_count = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["employer", "is_active"]),
            models.Index(fields=["employment_type", "experience_level"]),
            models.Index(fields=["location_country", "location_city"]),
            models.Index(fields=["-created_at"]),
        ]

    def clean(self):
        if self.salary_min and self.salary_max and self.salary_max < self.salary_min:
            raise ValidationError("salary_max must be >= salary_min.")
        if self.application_deadline and self.application_deadline < timezone.now() - timedelta(days=3650):
            raise ValidationError("application_deadline looks invalid.")

    def save(self, *args, **kwargs):
        if not self.slug:
            company_name = ""
            if self.company_id:
                company_name = self.company.name
            else:
                # fall back to employer profile company if linked
                try:
                    ep = self.employer.employer_profile  # type: ignore[attr-defined]
                    if ep.company:
                        company_name = ep.company.name
                except Exception:
                    company_name = ""
            base = f"{company_name}-{self.title}" if company_name else f"{self.title}-{self.employer.display_name()}"
            unique_slugify(self, base)
        self.full_clean()
        super().save(*args, **kwargs)

    def bump_views(self):
        Job.objects.filter(pk=self.pk).update(views=F("views") + 1)

    def __str__(self):
        cname = self.company.name if self.company_id else ""
        return f"{self.title} @ {cname or self.employer.display_name()}"


class SavedJob(UUIDPk, TimeStamped):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_jobs")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="saved_by")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "job"], name="uniq_saved_job"),
        ]
        indexes = [models.Index(fields=["user", "-created_at"])]


class JobApplication(UUIDPk, TimeStamped):
    class Status(models.TextChoices):
        APPLIED = "applied", "Applied"
        UNDER_REVIEW = "under_review", "Under Review"
        INTERVIEWING = "interviewing", "Interviewing"
        OFFERED = "offered", "Offered"
        HIRED = "hired", "Hired"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="job_applications")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="applications")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.APPLIED, db_index=True)

    cover_letter = models.TextField(blank=True)
    resume = models.FileField(upload_to="application_resumes/", blank=True, null=True)
    additional_docs = models.FileField(upload_to="application_docs/", blank=True, null=True)

    employer_notes = models.TextField(blank=True)

    applied_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    interviewed_at = models.DateTimeField(blank=True, null=True)
    offered_at = models.DateTimeField(blank=True, null=True)
    hired_at = models.DateTimeField(blank=True, null=True)
    rejected_at = models.DateTimeField(blank=True, null=True)
    withdrawn_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "job"], name="uniq_job_application"),
        ]
        indexes = [
            models.Index(fields=["job", "status"]),
            models.Index(fields=["user", "status"]),
            models.Index(fields=["-applied_at"]),
        ]

    def clean(self):
        if self.user_id == self.job.employer_id:
            raise ValidationError("You cannot apply to your own job posting.")

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        self.full_clean()
        super().save(*args, **kwargs)
        if is_new:
            Job.objects.filter(pk=self.job_id).update(applications_count=F("applications_count") + 1)
            Notification.create_application(self.job.employer, "New application", f"{self.user.display_name()} applied for {self.job.title}.", target=self)

    def update_status(self, new_status: str, by_user: CustomUser):
        if new_status not in dict(self.Status.choices):
            raise ValidationError("Invalid status.")
        self.status = new_status
        now = timezone.now()

        if new_status == self.Status.UNDER_REVIEW and not self.reviewed_at:
            self.reviewed_at = now
        elif new_status == self.Status.INTERVIEWING and not self.interviewed_at:
            self.interviewed_at = now
        elif new_status == self.Status.OFFERED and not self.offered_at:
            self.offered_at = now
        elif new_status == self.Status.HIRED and not self.hired_at:
            self.hired_at = now
        elif new_status == self.Status.REJECTED and not self.rejected_at:
            self.rejected_at = now
        elif new_status == self.Status.WITHDRAWN and not self.withdrawn_at:
            self.withdrawn_at = now

        self.save(update_fields=[
            "status", "reviewed_at", "interviewed_at", "offered_at", "hired_at",
            "rejected_at", "withdrawn_at", "updated_at"
        ])

        Notification.create_application(
            self.user,
            "Application status updated",
            f"Your application for {self.job.title} is now {self.get_status_display()}.",
            target=self,
        )


class JobAlert(UUIDPk, TimeStamped):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="job_alerts")
    name = models.CharField(max_length=100, default="My Alert")

    keywords = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=200, blank=True)

    employment_type = models.CharField(max_length=20, choices=Job.EmploymentType.choices, blank=True)
    experience_level = models.CharField(max_length=20, choices=Job.ExperienceLevel.choices, blank=True)
    remote_status = models.CharField(max_length=20, choices=Job.RemoteStatus.choices, blank=True)

    frequency = models.CharField(
        max_length=20,
        choices=[("daily", "Daily"), ("weekly", "Weekly"), ("instant", "Instant")],
        default="daily",
    )

    is_active = models.BooleanField(default=True, db_index=True)
    last_triggered_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=["user", "is_active"])]


# =============================================================================
# RECOMMENDATIONS (SOCIAL PROOF)
# =============================================================================

class Recommendation(UUIDPk, TimeStamped):
    recommender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendations_given")
    recommendee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendations_received")

    relationship = models.CharField(max_length=100)
    content = models.TextField()
    is_public = models.BooleanField(default=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["recommender", "recommendee"], name="uniq_recommendation"),
            models.CheckConstraint(check=~Q(recommender=F("recommendee")), name="chk_no_self_recommendation"),
        ]

    def clean(self):
        if self.recommender_id == self.recommendee_id:
            raise ValidationError("You cannot recommend yourself.")

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        self.full_clean()
        super().save(*args, **kwargs)
        if is_new:
            Notification.create_social(self.recommendee, "New recommendation", f"{self.recommender.display_name()} wrote you a recommendation.", target=self)


# =============================================================================
# PAYMENTS (PREMIUM / PROMOTIONS)
# =============================================================================

class PaymentTransaction(UUIDPk, TimeStamped):
    class Status(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    payer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    currency = models.CharField(max_length=10, default="ZMW")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INITIATED, db_index=True)

    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    billable = GenericForeignKey("content_type", "object_id")

    provider_ref = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["payer", "-created_at"]),
        ]

    def mark_success(self):
        if self.status == self.Status.SUCCESS:
            return
        self.status = self.Status.SUCCESS
        self.save(update_fields=["status", "updated_at"])

        Notification._create(self.payer, Notification.Type.SYSTEM, "Payment successful", f"Payment of {self.amount} {self.currency} completed.", target=self.billable)
        EventLog.objects.create(user=self.payer, event=EventLog.Event.PAYMENT, obj=self.billable, metadata={"amount": str(self.amount), "currency": self.currency})


# =============================================================================
# VERIFICATION CODES (EMAIL / PASSWORD RESET / MFA STEPUP)
# =============================================================================

class VerificationCode(UUIDPk, TimeStamped):
    class Type(models.TextChoices):
        EMAIL = "email", "Email verification"
        PASSWORD_RESET = "password_reset", "Password reset"
        MFA = "mfa", "Multi-factor auth"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verification_codes")
    code = models.CharField(max_length=8, db_index=True)
    code_type = models.CharField(max_length=20, choices=Type.choices, default=Type.EMAIL, db_index=True)

    expires_at = models.DateTimeField(db_index=True)
    is_used = models.BooleanField(default=False, db_index=True)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "code_type", "is_used"]),
            models.Index(fields=["expires_at"]),
        ]

    def clean(self):
        # sanity check: prevent obviously wrong expires dates
        if self.expires_at <= timezone.now() - timedelta(days=3650):
            raise ValidationError("expires_at looks invalid.")

    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def mark_used(self):
        self.is_used = True
        self.save(update_fields=["is_used", "updated_at"])


# =============================================================================
# SECURITY: LOGIN ATTEMPTS + DEVICE SESSIONS (TOKEN REVOCATION)
# =============================================================================

class LoginAttempt(UUIDPk, TimeStamped):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    email = models.EmailField(blank=True)

    success = models.BooleanField(default=False, db_index=True)

    ip_hash = models.CharField(max_length=64, db_index=True)
    user_agent = models.CharField(max_length=240, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["email", "-created_at"]),
            models.Index(fields=["ip_hash", "-created_at"]),
        ]


class DeviceSession(UUIDPk, TimeStamped):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions")

    refresh_token_hash = models.CharField(max_length=128, unique=True)
    ip_hash = models.CharField(max_length=64, db_index=True)
    user_agent = models.CharField(max_length=240, blank=True)

    last_seen_at = models.DateTimeField(auto_now=True)
    revoked_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "revoked_at"]),
            models.Index(fields=["ip_hash", "-last_seen_at"]),
        ]

    def revoke(self):
        if not self.revoked_at:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at", "updated_at"])


# =============================================================================
# SEARCH / INDEXING (FOR AGENTS + FAST FEEDS)
# =============================================================================

class ProfileIndex(UUIDPk, TimeStamped):
    """
    Denormalized index row for search + matching.
    Embedding is BinaryField placeholder. Use pgvector VectorField if available.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="search_index")

    searchable_text = models.TextField(blank=True)
    embedding = models.BinaryField(blank=True, null=True)  # replace with VectorField(dim=...) if using pgvector

    completeness_score = models.PositiveSmallIntegerField(default=0, db_index=True)
    quality_score = models.PositiveSmallIntegerField(default=0, db_index=True)

    updated_by_agent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["-quality_score"]),
            models.Index(fields=["-completeness_score"]),
        ]


class JobIndex(UUIDPk, TimeStamped):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name="search_index")

    searchable_text = models.TextField(blank=True)
    embedding = models.BinaryField(blank=True, null=True)  # replace with VectorField(dim=...) if using pgvector

    quality_score = models.PositiveSmallIntegerField(default=0, db_index=True)
    updated_by_agent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["-quality_score"]),
        ]


class MatchResult(UUIDPk, TimeStamped):
    """
    Precomputed matches for fast recommendation feeds on both sides.
    """
    class TargetType(models.TextChoices):
        JOB_FOR_USER = "job_for_user", "Job for User"
        USER_FOR_JOB = "user_for_job", "User for Job"

    target_type = models.CharField(max_length=20, choices=TargetType.choices, db_index=True)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="match_results")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="match_results")

    score = models.DecimalField(max_digits=6, decimal_places=3, db_index=True)
    reasons = models.JSONField(default=list, blank=True)  # ["Skill overlap: Python", "Remote match", ...]
    model_version = models.CharField(max_length=50, default="rules_v1")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["target_type", "user", "job"], name="uniq_match_result"),
        ]
        indexes = [
            models.Index(fields=["user", "target_type", "-score"]),
            models.Index(fields=["job", "target_type", "-score"]),
        ]


class WorkItem(UUIDPk, TimeStamped):
    """
    A DB-backed queue for agent tasks (optional if you already use Celery broker).
    Your agents can pull WorkItems to index, embed, moderate, match, etc.
    """
    class Type(models.TextChoices):
        PROFILE_UPDATED = "profile_updated", "Profile updated"
        JOB_UPDATED = "job_updated", "Job updated"
        POST_CREATED = "post_created", "Post created"
        MESSAGE_SENT = "message_sent", "Message sent"
        COMPANY_VERIFICATION_SUBMITTED = "company_verification_submitted", "Company verification submitted"

    type = models.CharField(max_length=40, choices=Type.choices, db_index=True)
    object_type = models.CharField(max_length=50)  # "user", "job", "post", "message", "company"
    object_id = models.CharField(max_length=64)

    status = models.CharField(max_length=20, default="queued", db_index=True)  # queued/running/done/failed
    attempts = models.PositiveSmallIntegerField(default=0)

    priority = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(5)])
    not_before = models.DateTimeField(blank=True, null=True, db_index=True)

    payload = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "priority", "not_before", "created_at"]),
        ]


# =============================================================================
# ADS SYSTEM (CAMPAIGNS / CREATIVES / EVENTS)
# =============================================================================

class AdCampaign(UUIDPk, TimeStamped):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ad_campaigns")
    name = models.CharField(max_length=120)

    objective = models.CharField(max_length=50, default="traffic")  # traffic/leads/sales
    daily_budget = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_budget = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    spent = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), db_index=True)

    start_at = models.DateTimeField()
    end_at = models.DateTimeField(blank=True, null=True)

    is_active = models.BooleanField(default=True, db_index=True)

    # Targeting rules (kept simple + flexible)
    targeting = models.JSONField(default=dict, blank=True)
    # Example:
    # {"countries":["ZM"], "cities":["Lusaka"], "skills":["django"], "interests":["jobs"]}

    class Meta:
        indexes = [
            models.Index(fields=["is_active", "start_at", "end_at"]),
            models.Index(fields=["owner", "-created_at"]),
        ]

    def is_running(self) -> bool:
        now = timezone.now()
        if not self.is_active:
            return False
        if self.start_at and now < self.start_at:
            return False
        if self.end_at and now > self.end_at:
            return False
        if self.total_budget > 0 and self.spent >= self.total_budget:
            return False
        return True


class AdCreative(UUIDPk, TimeStamped, Moderation):
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name="creatives")

    title = models.CharField(max_length=80)
    body = models.CharField(max_length=200)
    image = models.ImageField(upload_to="ads/images/", blank=True, null=True)
    url = models.URLField()

    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["campaign", "is_active"]),
            models.Index(fields=["moderation_status"]),
        ]


class AdEvent(UUIDPk, TimeStamped):
    class Type(models.TextChoices):
        IMPRESSION = "impression", "Impression"
        CLICK = "click", "Click"

    creative = models.ForeignKey(AdCreative, on_delete=models.CASCADE, related_name="events")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=20, choices=Type.choices, db_index=True)

    # Privacy-safe metadata: store hashes instead of raw identifiers
    ip_hash = models.CharField(max_length=64, blank=True, db_index=True)
    user_agent = models.CharField(max_length=240, blank=True)
    placement = models.CharField(max_length=80, blank=True)  # e.g. "feed_top", "jobs_sidebar"

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_type", "-created_at"]),
            models.Index(fields=["creative", "event_type", "-created_at"]),
        ]


# =============================================================================
# OPTIONAL: JOB PROMOTION (BILLABLE EXAMPLE)
# =============================================================================

class JobPromotion(UUIDPk, TimeStamped):
    """
    A billable object you can attach to PaymentTransaction.billable.
    """
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="promotions")
    campaign_name = models.CharField(max_length=120, default="Boost")

    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["is_active", "start_at", "end_at"])]

    def is_running(self) -> bool:
        now = timezone.now()
        return self.is_active and self.start_at <= now <= self.end_at


# =============================================================================
# SANITY: A SIMPLE "CAN VIEW PROFILE" UTILITY MODEL (OPTIONAL)
# =============================================================================

class ProfileView(UUIDPk, TimeStamped):
    """
    Track profile views (privacy-safe, rate limitable).
    """
    viewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="profile_views_made")
    viewed = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile_views_received")

    ip_hash = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["viewed", "-created_at"]),
            models.Index(fields=["viewer", "-created_at"]),
        ]


# -----------------------------------------------------------------------------
# END OF FILE
# -----------------------------------------------------------------------------