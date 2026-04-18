# services.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    UserProfile, ProfileView,
    Company, EmployerProfile, CompanyVerification,
    Post, PostLike, PostComment,
    Job, SavedJob, JobApplication,
    Conversation, DirectMessage,
    Connection, Follow, Block,
    Notification, EventLog,
    AdCampaign, AdCreative, AdEvent,
    ProfileIndex, JobIndex, MatchResult, WorkItem,
)

User = get_user_model()


# =============================================================================
# SMALL TYPES
# =============================================================================

@dataclass(frozen=True)
class MatchRow:
    user_id: str
    job_id: str
    score: float
    reasons: list[str]


# =============================================================================
# FEED
# =============================================================================

class FeedService:
    @staticmethod
    def get_feed_posts(viewer: Optional[User], limit: int = 50):
        qs = Post.objects.select_related("author").order_by("-created_at")
        if viewer is None or not viewer.is_authenticated:
            qs = qs.filter(
                visibility=Post.Visibility.PUBLIC,
                is_deleted=False,
                moderation_status=Post.ModerationStatus.OK
            )
            return qs[:limit]

        # Filter out deleted / removed
        qs = qs.filter(is_deleted=False).exclude(moderation_status=Post.ModerationStatus.REMOVED)

        # Exclude blocks
        blocked_ids = Block.objects.filter(blocker=viewer).values_list("blocked_id", flat=True)
        blocker_ids = Block.objects.filter(blocked=viewer).values_list("blocker_id", flat=True)
        qs = qs.exclude(author_id__in=blocked_ids).exclude(author_id__in=blocker_ids)

        # Find accepted connections
        connection_ids = Connection.objects.filter(
            Q(from_user=viewer, status=Connection.Status.ACCEPTED) |
            Q(to_user=viewer, status=Connection.Status.ACCEPTED)
        ).values_list("from_user_id", "to_user_id")

        connected_user_ids = set()
        for a, b in connection_ids:
            connected_user_ids.add(a)
            connected_user_ids.add(b)
        connected_user_ids.discard(viewer.id)

        qs = qs.filter(
            Q(visibility=Post.Visibility.PUBLIC) |
            Q(author=viewer) |
            Q(visibility=Post.Visibility.CONNECTIONS, author_id__in=connected_user_ids)
        )

        return qs[:limit]


# =============================================================================
# PROFILE
# =============================================================================

class ProfileService:
    @staticmethod
    def get_or_create_profile(user: User) -> UserProfile:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile

    @staticmethod
    def can_view_profile(viewer: Optional[User], target: User) -> bool:
        if target.is_profile_public:
            if viewer and viewer.is_authenticated:
                if Block.objects.filter(
                    Q(blocker=target, blocked=viewer) | Q(blocker=viewer, blocked=target)
                ).exists():
                    return False
            return True
        # private profiles: only self, admin, or accepted connections
        if viewer is None or not viewer.is_authenticated:
            return False
        if viewer.id == target.id or getattr(viewer, "role", "") == "admin":
            return True
        return Connection.objects.filter(
            Q(from_user=viewer, to_user=target, status=Connection.Status.ACCEPTED) |
            Q(from_user=target, to_user=viewer, status=Connection.Status.ACCEPTED)
        ).exists()

    @staticmethod
    def get_profile_context(viewer: Optional[User], target: User) -> dict:
        if not ProfileService.can_view_profile(viewer, target):
            return {"user": target, "forbidden": True}

        profile = UserProfile.objects.filter(user=target).first()
        return {
            "user": target,
            "profile": profile,
            "forbidden": False,
        }

    @staticmethod
    def track_profile_view(viewer: Optional[User], viewed: User, ip_hash: str = ""):
        """
        Call from view after obtaining ip_hash (e.g. hashlib.sha256(ip.encode()).hexdigest())
        """
        ProfileView.objects.create(
            viewer=viewer if viewer and viewer.is_authenticated else None,
            viewed=viewed,
            ip_hash=ip_hash
        )

    @staticmethod
    def enqueue_profile_updated(user: User):
        WorkItem.objects.create(
            type=WorkItem.Type.PROFILE_UPDATED,
            object_type="user",
            object_id=str(user.id),
            payload={"reason": "profile_saved"},
            priority=3,
        )


# =============================================================================
# POSTS
# =============================================================================

class PostService:
    @staticmethod
    def create_post(author: User, form) -> Post:
        post: Post = form.save(commit=False)
        post.author = author
        post.full_clean()
        post.save()
        EventLog.objects.create(user=author, event=EventLog.Event.POST_CREATED, obj=post)
        WorkItem.objects.create(
            type=WorkItem.Type.POST_CREATED,
            object_type="post",
            object_id=str(post.id),
            payload={}
        )
        return post

    @staticmethod
    def toggle_like(user: User, post: Post) -> bool:
        """returns True if liked, False if unliked"""
        if not post.can_view(user):
            raise ValueError("Cannot like a post you cannot view.")

        obj = PostLike.objects.filter(post=post, user=user).first()
        if obj:
            PostLike.unlike(post, user)
            return False
        PostLike.like(post, user)
        return True

    @staticmethod
    def get_like_count(post: Post) -> int:
        post.refresh_from_db(fields=["like_count"])
        return post.like_count

    @staticmethod
    def add_comment(user: User, post: Post, form) -> PostComment:
        comment: PostComment = form.save(commit=False)
        comment.post = post
        comment.author = user
        comment.full_clean()
        comment.save()
        return comment


# =============================================================================
# JOBS
# =============================================================================

class JobService:
    @staticmethod
    def search_jobs(request, limit: int = 50):
        qs = Job.objects.select_related("employer", "company").filter(
            is_active=True,
            is_deleted=False
        ).exclude(moderation_status=Job.ModerationStatus.REMOVED)

        q = (request.GET.get("q") or "").strip()
        country = (request.GET.get("country") or "").strip()
        city = (request.GET.get("city") or "").strip()
        remote = (request.GET.get("remote") or "").strip()

        if q:
            qs = qs.filter(
                Q(title__icontains=q) |
                Q(description__icontains=q) |
                Q(requirements__icontains=q)
            )
        if country:
            qs = qs.filter(location_country__iexact=country)
        if city:
            qs = qs.filter(location_city__iexact=city)
        if remote in {"remote", "hybrid", "onsite"}:
            qs = qs.filter(remote_status=remote)

        return qs.order_by("-created_at")[:limit]

    @staticmethod
    def create_job(employer: User, form) -> Job:
        job: Job = form.save(commit=False)
        job.employer = employer
        job.full_clean()
        job.save()
        form.save_m2m()
        WorkItem.objects.create(
            type=WorkItem.Type.JOB_UPDATED,
            object_type="job",
            object_id=str(job.id),
            payload={"reason": "created"},
            priority=3,
        )
        return job

    @staticmethod
    def bump_view(job: Job, viewer: Optional[User]):
        job.bump_views()
        if viewer and viewer.is_authenticated:
            EventLog.objects.create(user=viewer, event=EventLog.Event.VIEW_JOB, obj=job)

    @staticmethod
    def toggle_save_job(user: User, job: Job) -> bool:
        obj = SavedJob.objects.filter(user=user, job=job).first()
        if obj:
            obj.delete()
            return False
        SavedJob.objects.create(user=user, job=job)
        EventLog.objects.create(user=user, event=EventLog.Event.SAVE_JOB, obj=job)
        return True

    @staticmethod
    def apply_to_job(user: User, job: Job, form) -> JobApplication:
        with transaction.atomic():
            existing = JobApplication.objects.filter(user=user, job=job).first()
            if existing:
                raise ValueError("You already applied to this job.")
            app: JobApplication = form.save(commit=False)
            app.user = user
            app.job = job
            app.full_clean()
            app.save()
            EventLog.objects.create(user=user, event=EventLog.Event.APPLY_JOB, obj=job)
            return app


# =============================================================================
# MESSAGING
# =============================================================================

class MessagingService:
    @staticmethod
    def get_inbox_conversations(user: User, limit: int = 50):
        return Conversation.objects.filter(participants=user).order_by("-last_message_at")[:limit]

    @staticmethod
    def get_or_create_direct_thread(user: User, other: User) -> Conversation:
        if Block.objects.filter(
            Q(blocker=user, blocked=other) | Q(blocker=other, blocked=user)
        ).exists():
            raise ValueError("Cannot message this user.")
        return Conversation.get_or_create_direct(user, other)

    @staticmethod
    def get_messages(conversation: Conversation, user: User, limit: int = 100):
        if not conversation.can_participate(user):
            raise ValueError("Forbidden.")
        return conversation.messages.select_related("sender").order_by("-created_at")[:limit]

    @staticmethod
    def send_message(conversation: Conversation, sender: User, content: str, attachment=None) -> DirectMessage:
        msg = DirectMessage.send(conversation, sender, content=content, attachment=attachment)
        EventLog.objects.create(user=sender, event=EventLog.Event.MESSAGE_SENT, obj=conversation)
        WorkItem.objects.create(
            type=WorkItem.Type.MESSAGE_SENT,
            object_type="message",
            object_id=str(msg.id),
            payload={"conversation_id": str(conversation.id)}
        )
        return msg


# =============================================================================
# NETWORKING
# =============================================================================

class NetworkService:
    @staticmethod
    def request_connection(from_user: User, to_user: User) -> Connection:
        if from_user.id == to_user.id:
            raise ValueError("Cannot connect to yourself.")

        if Block.objects.filter(
            Q(blocker=from_user, blocked=to_user) | Q(blocker=to_user, blocked=from_user)
        ).exists():
            raise ValueError("Cannot connect with a blocked user.")

        conn, created = Connection.objects.get_or_create(from_user=from_user, to_user=to_user)
        if not created and conn.status == Connection.Status.ACCEPTED:
            return conn

        conn.status = Connection.Status.PENDING
        conn.full_clean()
        conn.save(update_fields=["status", "updated_at"])
        EventLog.objects.create(user=from_user, event=EventLog.Event.CONNECTION_REQUEST, obj=conn)
        Notification.create_social(
            to_user,
            "New connection request",
            f"{from_user.display_name()} wants to connect.",
            target=conn
        )
        return conn

    @staticmethod
    def accept_connection(conn: Connection, acting_user: User):
        if conn.to_user_id != acting_user.id and acting_user.role != "admin":
            raise ValueError("Forbidden.")
        conn.accept()

    @staticmethod
    def toggle_follow(follower: User, following: User) -> bool:
        if follower.id == following.id:
            return False
        obj = Follow.objects.filter(follower=follower, following=following).first()
        if obj:
            obj.delete()
            return False
        Follow.objects.create(follower=follower, following=following)
        return True

    @staticmethod
    def toggle_block(blocker: User, blocked: User) -> bool:
        if blocker.id == blocked.id:
            return False
        obj = Block.objects.filter(blocker=blocker, blocked=blocked).first()
        if obj:
            obj.delete()
            return False

        with transaction.atomic():
            Block.objects.create(blocker=blocker, blocked=blocked)
            Connection.objects.filter(
                Q(from_user=blocker, to_user=blocked) | Q(from_user=blocked, to_user=blocker)
            ).delete()
            Follow.objects.filter(
                Q(follower=blocker, following=blocked) | Q(follower=blocked, following=blocker)
            ).delete()
        return True


# =============================================================================
# ADS
# =============================================================================

class AdsService:
    @staticmethod
    def create_campaign(owner: User, form) -> AdCampaign:
        camp: AdCampaign = form.save(commit=False)
        camp.owner = owner
        camp.full_clean()
        camp.save()
        return camp

    @staticmethod
    def create_creative(owner: User, form) -> AdCreative:
        creative: AdCreative = form.save(commit=False)
        if creative.campaign.owner_id != owner.id and owner.role != "admin":
            raise ValueError("Forbidden.")
        creative.full_clean()
        creative.save()
        return creative

    @staticmethod
    def track_ad_event(
        creative: AdCreative,
        event_type: str,
        user: Optional[User],
        ip_hash: str = "",
        user_agent: str = "",
        placement: str = ""
    ):
        AdEvent.objects.create(
            creative=creative,
            event_type=event_type,
            user=user if user and user.is_authenticated else None,
            ip_hash=ip_hash,
            user_agent=user_agent[:240],
            placement=placement[:80],
        )
        EventLog.objects.create(
            user=user if user and user.is_authenticated else None,
            event=("ad_click" if event_type == "click" else "ad_impression"),
            obj=creative
        )


# =============================================================================
# MATCHING SERVICE (RULE‑BASED V1, READY FOR ML)
# =============================================================================

class MatchingService:
    """
    V1: rules‑based scoring (fast, deterministic, works now).
    V2: plug in embeddings/ML in the same interface.
    """

    @staticmethod
    def enqueue_job_updated(job: Job, reason: str = "updated"):
        WorkItem.objects.create(
            type=WorkItem.Type.JOB_UPDATED,
            object_type="job",
            object_id=str(job.id),
            payload={"reason": reason},
            priority=3,
        )

    @staticmethod
    def enqueue_profile_updated(user: User, reason: str = "updated"):
        WorkItem.objects.create(
            type=WorkItem.Type.PROFILE_UPDATED,
            object_type="user",
            object_id=str(user.id),
            payload={"reason": reason},
            priority=3,
        )

    # -----------------------------
    # Public API used by views
    # -----------------------------
    @staticmethod
    def get_top_jobs_for_user(user: User, limit: int = 30):
        qs = MatchResult.objects.filter(
            target_type=MatchResult.TargetType.JOB_FOR_USER,
            user=user
        ).select_related("job").order_by("-score")[:limit]
        if qs.exists():
            return qs

        # fallback: compute on the fly (cheap)
        MatchingService.compute_matches_for_user(user, limit=limit)
        return MatchResult.objects.filter(
            target_type=MatchResult.TargetType.JOB_FOR_USER,
            user=user
        ).select_related("job").order_by("-score")[:limit]

    @staticmethod
    def get_top_candidates_for_job(job: Job, limit: int = 30):
        qs = MatchResult.objects.filter(
            target_type=MatchResult.TargetType.USER_FOR_JOB,
            job=job
        ).select_related("user").order_by("-score")[:limit]
        if qs.exists():
            return qs
        MatchingService.compute_matches_for_job(job, limit=limit)
        return MatchResult.objects.filter(
            target_type=MatchResult.TargetType.USER_FOR_JOB,
            job=job
        ).select_related("user").order_by("-score")[:limit]

    # -----------------------------
    # V1 Rule scoring
    # -----------------------------
    @staticmethod
    def compute_matches_for_user(user: User, limit: int = 200):
        profile = UserProfile.objects.filter(user=user).first()
        user_skill_ids = set(user.skills.values_list("skill_id", flat=True))

        jobs = Job.objects.filter(
            is_active=True,
            is_deleted=False
        ).exclude(
            moderation_status=Job.ModerationStatus.REMOVED
        ).prefetch_related("skills_required")[:2000]

        rows: list[tuple[Job, float, list[str]]] = []
        for job in jobs:
            score, reasons = MatchingService._score_user_job(
                user, profile, user_skill_ids, job
            )
            if score > 0:
                rows.append((job, score, reasons))

        rows.sort(key=lambda x: x[1], reverse=True)
        rows = rows[:limit]

        with transaction.atomic():
            MatchResult.objects.filter(
                target_type=MatchResult.TargetType.JOB_FOR_USER,
                user=user
            ).delete()
            MatchResult.objects.bulk_create([
                MatchResult(
                    target_type=MatchResult.TargetType.JOB_FOR_USER,
                    user=user,
                    job=job,
                    score=score,
                    reasons=reasons,
                    model_version="rules_v1",
                )
                for job, score, reasons in rows
            ])

    @staticmethod
    def compute_matches_for_job(job: Job, limit: int = 200):
        required_skill_ids = set(job.skills_required.values_list("id", flat=True))

        candidates = User.objects.filter(
            role="job_seeker",
            is_active=True,
            is_profile_public=True
        ).prefetch_related("skills")[:2000]

        rows: list[tuple[User, float, list[str]]] = []
        for u in candidates:
            profile = UserProfile.objects.filter(user=u).first()
            user_skill_ids = set(u.skills.values_list("skill_id", flat=True))
            score, reasons = MatchingService._score_user_job(
                u, profile, user_skill_ids, job
            )
            if score > 0:
                rows.append((u, score, reasons))

        rows.sort(key=lambda x: x[1], reverse=True)
        rows = rows[:limit]

        with transaction.atomic():
            MatchResult.objects.filter(
                target_type=MatchResult.TargetType.USER_FOR_JOB,
                job=job
            ).delete()
            MatchResult.objects.bulk_create([
                MatchResult(
                    target_type=MatchResult.TargetType.USER_FOR_JOB,
                    user=u,
                    job=job,
                    score=score,
                    reasons=reasons,
                    model_version="rules_v1",
                )
                for u, score, reasons in rows
            ])

    @staticmethod
    def _score_user_job(
        user: User,
        profile: Optional[UserProfile],
        user_skill_ids: set,
        job: Job
    ) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0

        # Skill overlap
        job_skill_ids = set(job.skills_required.values_list("id", flat=True))
        if job_skill_ids:
            overlap = len(user_skill_ids.intersection(job_skill_ids))
            skill_ratio = overlap / max(len(job_skill_ids), 1)
            score += 60.0 * skill_ratio
            if overlap > 0:
                reasons.append(f"Skills match: {overlap}/{len(job_skill_ids)}")

        # Remote/location preference
        if profile:
            prefs = set(profile.preferred_job_types or [])
            if job.remote_status in prefs:
                score += 10.0
                reasons.append(f"Preference match: {job.get_remote_status_display()}")

            plocs = [str(x).lower() for x in (profile.preferred_locations or [])]
            if plocs:
                loc = (job.location or "").lower()
                if any(p in loc for p in plocs):
                    score += 10.0
                    reasons.append("Location matches your preference")

        # Recency boost
        days = (timezone.now() - job.created_at).days
        if days <= 3:
            score += 8.0
            reasons.append("Recently posted")
        elif days <= 14:
            score += 4.0

        # Employer/company verification boost
        if job.company_id and job.company.is_verified:
            score += 6.0
            reasons.append("Verified company")

        if job.salary_visible and job.salary_min and job.salary_max:
            score += 2.0

        # Clamp
        score = max(0.0, min(100.0, score))
        return score, reasons


# =============================================================================
# UNIFIED FEED SERVICE (FIXED – NO DATABASE ANNOTATION)
# =============================================================================

class UnifiedFeedService:
    """Combine posts, recommended jobs, and network updates into a single scored feed."""

    @staticmethod
    def get_feed_items(user, limit=10, offset=0):
        from .models import Post, Job, Connection, Follow
        from django.db.models import Q
        from .services import MatchingService

        items = []

        if user.is_authenticated:
            # ---- 1. Posts from network (Python‑side scoring) ----
            connections = Connection.objects.filter(
                Q(from_user=user, status=Connection.Status.ACCEPTED) |
                Q(to_user=user, status=Connection.Status.ACCEPTED)
            ).values_list('from_user_id', 'to_user_id')
            connected_ids = set()
            for a, b in connections:
                connected_ids.add(a)
                connected_ids.add(b)
            connected_ids.discard(user.id)

            followed_ids = set(Follow.objects.filter(follower=user).values_list('following_id', flat=True))
            visible_authors = connected_ids | followed_ids | {user.id}

            posts = Post.objects.filter(
                author_id__in=visible_authors,
                is_deleted=False,
                moderation_status=Post.ModerationStatus.OK
            ).exclude(
                Q(visibility=Post.Visibility.PRIVATE) & ~Q(author=user)
            ).select_related('author')

            for post in posts:
                # recency score: newer posts get higher score (max 30 days)
                days_ago = (timezone.now() - post.created_at).days
                recency_score = max(0, 30 - days_ago)   # score from 0 to 30
                items.append({
                    'type': 'post',
                    'data': post,
                    'score': recency_score,
                    'timestamp': post.created_at
                })

            # ---- 2. Recommended jobs (from MatchingService) ----
            match_results = MatchingService.get_top_jobs_for_user(user, limit=50)
            for match in match_results:
                job = match.job
                items.append({
                    'type': 'job',
                    'data': job,
                    'score': float(match.score) * 1.0,   # keep as is (0‑100)
                    'timestamp': job.created_at,
                    'match_reasons': match.reasons
                })

        else:
            # Anonymous user: show featured jobs
            jobs = Job.objects.filter(
                is_active=True,
                moderation_status=Job.ModerationStatus.OK
            ).select_related('company')[:20]
            for job in jobs:
                items.append({
                    'type': 'job',
                    'data': job,
                    'score': 0,
                    'timestamp': job.created_at
                })

        # Sort by score (desc) then by timestamp (desc)
        items.sort(key=lambda x: (x['score'], x['timestamp']), reverse=True)

        # Apply pagination
        return items[offset:offset+limit]