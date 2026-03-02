# admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from django.db.models import Count, Q

from . import models as m


# -----------------------------------------------------------------------------
# Admin site branding
# -----------------------------------------------------------------------------
admin.site.site_header = "Deriv.Ed Admin"
admin.site.site_title = "Deriv.Ed Admin"
admin.site.index_title = "Job Matching Platform Management"


# =============================================================================
# USER ADMIN (EMAIL-FIRST, NO USERNAME)
# =============================================================================

class UserProfileInline(admin.StackedInline):
    model = m.UserProfile
    extra = 0
    can_delete = False
    fields = (
        "bio", "avatar", "cover_image", "location", "website", "linkedin", "github", "twitter",
        "open_to_work", "open_to_relocation", "preferred_job_types", "preferred_locations", "resume"
    )


class EmployerProfileInline(admin.StackedInline):
    model = m.EmployerProfile
    extra = 0
    can_delete = False
    fields = ("company", "title", "is_company_admin", "verification_notes")


@admin.register(m.CustomUser)
class CustomUserAdmin(UserAdmin):
    model = m.CustomUser
    ordering = ("email",)
    list_display = (
        "email",
        "role",
        "email_verified",
        "phone_verified",
        "headline",
        "is_staff",
        "is_superuser",
        "is_active",
        "created_at",
    )
    list_filter = ("role", "email_verified", "phone_verified", "is_staff", "is_superuser", "is_active")
    search_fields = ("email", "phone", "first_name", "last_name", "headline")
    inlines = [UserProfileInline, EmployerProfileInline]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "phone")}),
        (_("Professional"), {"fields": ("role", "headline", "current_position")}),
        (_("Verification & Trust"), {"fields": ("email_verified", "phone_verified")}),
        (_("Privacy & Messaging"), {"fields": ("is_profile_public", "allow_messages_from")}),
        (_("Security"), {"fields": ("failed_login_count", "locked_until", "last_password_change_at")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Important dates"), {"fields": ("last_login", "created_at", "updated_at")}),
        (_("Preferences"), {"fields": ("preferences",)}),
    )

    readonly_fields = ("created_at", "updated_at", "last_login")

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2", "role", "is_staff", "is_superuser"),
        }),
    )

    def get_fieldsets(self, request, obj=None):
        return super().get_fieldsets(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        kwargs["fields"] = None
        return super().get_form(request, obj, **kwargs)


@admin.register(m.UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "location", "open_to_work", "open_to_relocation", "updated_at")
    search_fields = ("user__email", "location")
    list_filter = ("open_to_work", "open_to_relocation")
    readonly_fields = ("created_at", "updated_at")


@admin.register(m.Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "industry", "size", "is_verified", "moderation_status", "created_at")
    list_filter = ("is_verified", "moderation_status", "industry")
    search_fields = ("name", "website")
    prepopulated_fields = {"slug": ("name",)}
    actions = ["mark_verified", "mark_under_review", "remove"]

    @admin.action(description="Mark selected companies as verified")
    def mark_verified(self, request, queryset):
        updated = queryset.update(is_verified=True, moderation_status=m.Moderation.ModerationStatus.OK)
        self.message_user(request, f"{updated} company(s) marked verified.")

    @admin.action(description="Mark selected companies as UNDER REVIEW")
    def mark_under_review(self, request, queryset):
        updated = queryset.update(moderation_status=m.Moderation.ModerationStatus.UNDER_REVIEW)
        self.message_user(request, f"{updated} company(s) marked under review.")

    @admin.action(description="Remove selected companies (moderation removed)")
    def remove(self, request, queryset):
        updated = queryset.update(moderation_status=m.Moderation.ModerationStatus.REMOVED)
        self.message_user(request, f"{updated} company(s) removed.")


@admin.register(m.EmployerProfile)
class EmployerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "company", "title", "is_company_admin")
    list_filter = ("is_company_admin", "company")
    search_fields = ("user__email", "company__name")


@admin.register(m.CompanyVerification)
class CompanyVerificationAdmin(admin.ModelAdmin):
    list_display = ("company", "status", "submitted_by", "reviewed_by", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("company__name", "submitted_by__email")
    actions = ["approve_verifications", "reject_verifications"]

    @admin.action(description="Approve selected verifications")
    def approve_verifications(self, request, queryset):
        for v in queryset:
            if v.status != v.Status.VERIFIED:
                v.approve(request.user)
        self.message_user(request, f"Approved {queryset.count()} verification(s).")

    @admin.action(description="Reject selected verifications")
    def reject_verifications(self, request, queryset):
        for v in queryset:
            if v.status not in [v.Status.VERIFIED, v.Status.REJECTED]:
                v.reject(request.user, notes="Rejected via admin")
        self.message_user(request, f"Rejected {queryset.count()} verification(s).")


# =============================================================================
# SKILLS & ENDORSEMENTS
# =============================================================================

@admin.register(m.Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active", "created_at")
    list_filter = ("is_active", "category")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}


class EndorsementInline(admin.TabularInline):
    model = m.Endorsement
    extra = 0
    fields = ("endorser", "created_at")
    readonly_fields = ("created_at",)


@admin.register(m.UserSkill)
class UserSkillAdmin(admin.ModelAdmin):
    list_display = ("user", "skill", "level", "endorsement_count", "created_at")
    list_filter = ("skill__category", "level")
    search_fields = ("user__email", "skill__name")
    inlines = [EndorsementInline]


@admin.register(m.Endorsement)
class EndorsementAdmin(admin.ModelAdmin):
    list_display = ("endorser", "user_skill", "created_at")
    list_filter = ("created_at",)
    search_fields = ("endorser__email", "user_skill__user__email", "user_skill__skill__name")


# =============================================================================
# EXPERIENCE & EDUCATION
# =============================================================================

@admin.register(m.Experience)
class ExperienceAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "company", "is_current", "start_date", "end_date")
    list_filter = ("is_current", "company")
    search_fields = ("user__email", "title", "company")
    date_hierarchy = "start_date"


@admin.register(m.Education)
class EducationAdmin(admin.ModelAdmin):
    list_display = ("user", "degree", "school", "is_current", "start_date", "end_date")
    list_filter = ("is_current", "school")
    search_fields = ("user__email", "degree", "school")
    date_hierarchy = "start_date"


# =============================================================================
# NETWORKING
# =============================================================================

@admin.register(m.Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ("from_user", "to_user", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("from_user__email", "to_user__email")
    list_editable = ("status",)


@admin.register(m.Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ("follower", "following", "created_at")
    search_fields = ("follower__email", "following__email")


# =============================================================================
# TRUST & SAFETY
# =============================================================================

@admin.register(m.Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("blocker", "blocked", "created_at")
    search_fields = ("blocker__email", "blocked__email")


@admin.register(m.Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("reporter", "target", "reason", "is_resolved", "resolved_by", "created_at")
    list_filter = ("is_resolved", "created_at")
    search_fields = ("reporter__email", "reason", "details")
    actions = ["mark_resolved"]

    @admin.action(description="Mark selected reports as resolved")
    def mark_resolved(self, request, queryset):
        for r in queryset:
            if not r.is_resolved:
                r.resolve(request.user)
        self.message_user(request, f"Resolved {queryset.count()} report(s).")


# =============================================================================
# POSTS / COMMENTS / LIKES
# =============================================================================

class PostCommentInline(admin.TabularInline):
    model = m.PostComment
    extra = 0
    fields = ("author", "content", "moderation_status", "is_deleted", "created_at")
    readonly_fields = ("created_at",)


@admin.register(m.Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("author", "visibility", "moderation_status", "is_deleted", "like_count", "comment_count", "created_at")
    list_filter = ("visibility", "moderation_status", "is_deleted", "created_at")
    search_fields = ("author__email", "content")
    readonly_fields = ("like_count", "comment_count", "created_at", "updated_at", "deleted_at")
    inlines = [PostCommentInline]
    actions = ("mark_under_review", "remove_posts", "restore_posts")

    @admin.action(description="Mark selected posts as UNDER REVIEW")
    def mark_under_review(self, request, queryset):
        updated = queryset.update(moderation_status=m.Moderation.ModerationStatus.UNDER_REVIEW)
        self.message_user(request, f"{updated} post(s) marked under review.")

    @admin.action(description="Remove selected posts (moderation removed)")
    def remove_posts(self, request, queryset):
        updated = queryset.update(moderation_status=m.Moderation.ModerationStatus.REMOVED)
        self.message_user(request, f"{updated} post(s) removed.")

    @admin.action(description="Restore selected posts (moderation ok, undelete)")
    def restore_posts(self, request, queryset):
        updated = queryset.update(
            moderation_status=m.Moderation.ModerationStatus.OK,
            is_deleted=False,
            deleted_at=None
        )
        self.message_user(request, f"{updated} post(s) restored.")


@admin.register(m.PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display = ("post", "user", "created_at")
    search_fields = ("user__email", "post__author__email")


@admin.register(m.PostComment)
class PostCommentAdmin(admin.ModelAdmin):
    list_display = ("post", "author", "moderation_status", "is_deleted", "created_at")
    list_filter = ("moderation_status", "is_deleted", "created_at")
    search_fields = ("author__email", "content", "post__author__email")
    readonly_fields = ("created_at", "updated_at", "deleted_at")


# =============================================================================
# MESSAGING
# =============================================================================

class DirectMessageInline(admin.TabularInline):
    model = m.DirectMessage
    extra = 0
    fields = ("sender", "content", "moderation_status", "is_deleted", "spam_score", "created_at")
    readonly_fields = ("created_at",)


@admin.register(m.Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "is_group", "title", "last_message_at", "participant_count")
    list_filter = ("is_group",)
    search_fields = ("title",)
    inlines = [DirectMessageInline]

    def participant_count(self, obj):
        return obj.participants.count()
    participant_count.short_description = "Participants"


@admin.register(m.DirectMessage)
class DirectMessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender", "moderation_status", "is_deleted", "spam_score", "created_at")
    list_filter = ("moderation_status", "is_deleted", "created_at")
    search_fields = ("sender__email", "content")


@admin.register(m.MessageDelivery)
class MessageDeliveryAdmin(admin.ModelAdmin):
    list_display = ("message", "user", "delivered_at", "read_at", "created_at")
    list_filter = ("delivered_at", "read_at")
    search_fields = ("user__email", "message__sender__email")


# =============================================================================
# NOTIFICATIONS + EVENT LOGS
# =============================================================================

@admin.register(m.Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "notif_type", "title", "is_read", "priority", "created_at")
    list_filter = ("notif_type", "is_read", "priority", "created_at")
    search_fields = ("recipient__email", "title", "body")
    readonly_fields = ("created_at", "updated_at", "read_at")


@admin.register(m.EventLog)
class EventLogAdmin(admin.ModelAdmin):
    list_display = ("event", "user", "created_at")
    list_filter = ("event", "created_at")
    search_fields = ("user__email", "event")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"


# =============================================================================
# JOBS & APPLICATIONS
# =============================================================================

@admin.register(m.Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "title", "employer", "company", "employment_type", "experience_level",
        "location_country", "location_city", "is_active", "views", "applications_count", "created_at"
    )
    list_filter = (
        "employment_type", "experience_level", "remote_status", "is_active",
        "moderation_status", "is_deleted", "location_country"
    )
    search_fields = ("title", "description", "employer__email", "company__name")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("skills_required",)
    readonly_fields = ("views", "applications_count", "created_at", "updated_at", "deleted_at")
    fieldsets = (
        (None, {"fields": ("employer", "company", "title", "slug")}),
        ("Description", {"fields": ("description", "responsibilities", "requirements", "benefits")}),
        ("Employment Details", {
            "fields": (
                "employment_type", "experience_level", "remote_status",
                "location", "location_country", "location_city"
            )
        }),
        ("Salary", {"fields": ("salary_min", "salary_max", "salary_currency", "salary_visible")}),
        ("Skills", {"fields": ("skills_required",)}),
        ("Application", {"fields": ("application_deadline", "external_application_url", "is_active")}),
        ("Stats", {"fields": ("views", "applications_count")}),
        ("Moderation", {"fields": ("moderation_status", "moderation_reason", "is_deleted", "deleted_at")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
    actions = (
        "activate_jobs", "deactivate_jobs", "mark_under_review", "remove_jobs", "restore_jobs"
    )

    @admin.action(description="Activate selected jobs")
    def activate_jobs(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} job(s) activated.")

    @admin.action(description="Deactivate selected jobs")
    def deactivate_jobs(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} job(s) deactivated.")

    @admin.action(description="Mark selected jobs as UNDER REVIEW")
    def mark_under_review(self, request, queryset):
        updated = queryset.update(moderation_status=m.Moderation.ModerationStatus.UNDER_REVIEW)
        self.message_user(request, f"{updated} job(s) marked under review.")

    @admin.action(description="Remove selected jobs (moderation removed)")
    def remove_jobs(self, request, queryset):
        updated = queryset.update(moderation_status=m.Moderation.ModerationStatus.REMOVED)
        self.message_user(request, f"{updated} job(s) removed.")

    @admin.action(description="Restore selected jobs (moderation ok, undelete)")
    def restore_jobs(self, request, queryset):
        updated = queryset.update(
            moderation_status=m.Moderation.ModerationStatus.OK,
            is_deleted=False,
            deleted_at=None
        )
        self.message_user(request, f"{updated} job(s) restored.")


@admin.register(m.SavedJob)
class SavedJobAdmin(admin.ModelAdmin):
    list_display = ("user", "job", "created_at")
    search_fields = ("user__email", "job__title")


class JobApplicationStatusFilter(admin.SimpleListFilter):
    title = "status group"
    parameter_name = "status_group"

    def lookups(self, request, model_admin):
        return (
            ("active", "Active (Applied, Review, Interviewing)"),
            ("final", "Final (Offered, Hired, Rejected, Withdrawn)"),
        )

    def queryset(self, request, queryset):
        if self.value() == "active":
            return queryset.filter(status__in=[
                m.JobApplication.Status.APPLIED,
                m.JobApplication.Status.UNDER_REVIEW,
                m.JobApplication.Status.INTERVIEWING,
            ])
        if self.value() == "final":
            return queryset.filter(status__in=[
                m.JobApplication.Status.OFFERED,
                m.JobApplication.Status.HIRED,
                m.JobApplication.Status.REJECTED,
                m.JobApplication.Status.WITHDRAWN,
            ])
        return queryset


@admin.register(m.JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ("user", "job", "status", "applied_at", "reviewed_at", "offered_at", "hired_at")
    list_filter = ("status", JobApplicationStatusFilter, "job__employer", "applied_at")
    search_fields = ("user__email", "job__title", "job__employer__email")
    readonly_fields = ("applied_at", "reviewed_at", "interviewed_at", "offered_at", "hired_at", "rejected_at", "withdrawn_at", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("user", "job", "status")}),
        ("Application Materials", {"fields": ("cover_letter", "resume", "additional_docs")}),
        ("Employer Notes", {"fields": ("employer_notes",)}),
        ("Timestamps", {"fields": ("applied_at", "reviewed_at", "interviewed_at", "offered_at", "hired_at", "rejected_at", "withdrawn_at")}),
        ("System", {"fields": ("created_at", "updated_at")}),
    )
    actions = ("mark_as_reviewed", "mark_as_interviewing", "mark_as_offered", "mark_as_hired", "mark_as_rejected")

    @admin.action(description="Mark selected as UNDER REVIEW")
    def mark_as_reviewed(self, request, queryset):
        for app in queryset:
            if app.status not in [app.Status.REJECTED, app.Status.WITHDRAWN, app.Status.HIRED, app.Status.OFFERED]:
                app.update_status(m.JobApplication.Status.UNDER_REVIEW, request.user)
        self.message_user(request, f"Updated {queryset.count()} applications to Under Review.")

    @admin.action(description="Mark selected as INTERVIEWING")
    def mark_as_interviewing(self, request, queryset):
        for app in queryset:
            if app.status not in [app.Status.REJECTED, app.Status.WITHDRAWN, app.Status.HIRED, app.Status.OFFERED]:
                app.update_status(m.JobApplication.Status.INTERVIEWING, request.user)
        self.message_user(request, f"Updated {queryset.count()} applications to Interviewing.")

    @admin.action(description="Mark selected as OFFERED")
    def mark_as_offered(self, request, queryset):
        for app in queryset:
            if app.status not in [app.Status.REJECTED, app.Status.WITHDRAWN, app.Status.HIRED]:
                app.update_status(m.JobApplication.Status.OFFERED, request.user)
        self.message_user(request, f"Updated {queryset.count()} applications to Offered.")

    @admin.action(description="Mark selected as HIRED")
    def mark_as_hired(self, request, queryset):
        for app in queryset:
            if app.status not in [app.Status.REJECTED, app.Status.WITHDRAWN]:
                app.update_status(m.JobApplication.Status.HIRED, request.user)
        self.message_user(request, f"Updated {queryset.count()} applications to Hired.")

    @admin.action(description="Mark selected as REJECTED")
    def mark_as_rejected(self, request, queryset):
        for app in queryset:
            app.update_status(m.JobApplication.Status.REJECTED, request.user)
        self.message_user(request, f"Updated {queryset.count()} applications to Rejected.")


@admin.register(m.JobAlert)
class JobAlertAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "keywords", "location", "frequency", "is_active", "last_triggered_at")
    list_filter = ("frequency", "is_active")
    search_fields = ("user__email", "name", "keywords", "location")


# =============================================================================
# RECOMMENDATIONS
# =============================================================================

@admin.register(m.Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ("recommender", "recommendee", "relationship", "is_public", "created_at")
    list_filter = ("is_public", "created_at")
    search_fields = ("recommender__email", "recommendee__email", "relationship", "content")


# =============================================================================
# PAYMENTS
# =============================================================================

@admin.register(m.PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("payer", "amount", "currency", "status", "created_at")
    list_filter = ("status", "currency", "created_at")
    search_fields = ("payer__email", "provider_ref")
    readonly_fields = ("created_at", "updated_at")
    actions = ("mark_as_success",)

    @admin.action(description="Mark selected transactions as SUCCESS")
    def mark_as_success(self, request, queryset):
        for t in queryset:
            if t.status != t.Status.SUCCESS:
                t.mark_success()
        self.message_user(request, f"Marked {queryset.count()} transaction(s) as success.")


# =============================================================================
# VERIFICATION CODES
# =============================================================================

@admin.register(m.VerificationCode)
class VerificationCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "code_type", "code", "is_used", "expires_at", "created_at")
    list_filter = ("code_type", "is_used", "created_at")
    search_fields = ("user__email", "code")
    readonly_fields = ("created_at", "updated_at")


# =============================================================================
# SECURITY (LOGIN ATTEMPTS, DEVICE SESSIONS)
# =============================================================================

@admin.register(m.LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("email", "user", "success", "ip_hash", "created_at")
    list_filter = ("success", "created_at")
    search_fields = ("email", "user__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(m.DeviceSession)
class DeviceSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "ip_hash", "last_seen_at", "revoked_at", "created_at")
    list_filter = ("revoked_at", "created_at")
    search_fields = ("user__email",)
    actions = ("revoke_sessions",)

    @admin.action(description="Revoke selected sessions")
    def revoke_sessions(self, request, queryset):
        for s in queryset:
            if not s.revoked_at:
                s.revoke()
        self.message_user(request, f"Revoked {queryset.count()} session(s).")


# =============================================================================
# SEARCH INDEXES & WORK ITEMS (OPTIONAL)
# =============================================================================

@admin.register(m.ProfileIndex)
class ProfileIndexAdmin(admin.ModelAdmin):
    list_display = ("user", "completeness_score", "quality_score", "updated_by_agent_at")
    list_filter = ("completeness_score", "quality_score")
    search_fields = ("user__email",)


@admin.register(m.JobIndex)
class JobIndexAdmin(admin.ModelAdmin):
    list_display = ("job", "quality_score", "updated_by_agent_at")
    list_filter = ("quality_score",)
    search_fields = ("job__title",)


@admin.register(m.MatchResult)
class MatchResultAdmin(admin.ModelAdmin):
    list_display = ("user", "job", "target_type", "score", "created_at")
    list_filter = ("target_type", "created_at")
    search_fields = ("user__email", "job__title")


@admin.register(m.WorkItem)
class WorkItemAdmin(admin.ModelAdmin):
    list_display = ("type", "object_type", "object_id", "status", "priority", "attempts", "created_at")
    list_filter = ("type", "status", "priority")
    search_fields = ("object_id",)
    actions = ("retry_failed",)

    @admin.action(description="Retry selected failed work items")
    def retry_failed(self, request, queryset):
        updated = queryset.filter(status="failed").update(status="queued", attempts=0, last_error="")
        self.message_user(request, f"Retried {updated} work item(s).")


# =============================================================================
# ADS SYSTEM
# =============================================================================

@admin.register(m.AdCampaign)
class AdCampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "objective", "daily_budget", "spent", "is_active", "start_at", "end_at")
    list_filter = ("is_active", "objective")
    search_fields = ("name", "owner__email")
    actions = ("start_campaigns", "stop_campaigns")

    @admin.action(description="Start selected campaigns")
    def start_campaigns(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"Started {updated} campaign(s).")

    @admin.action(description="Stop selected campaigns")
    def stop_campaigns(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"Stopped {updated} campaign(s).")


@admin.register(m.AdCreative)
class AdCreativeAdmin(admin.ModelAdmin):
    list_display = ("title", "campaign", "is_active", "moderation_status", "created_at")
    list_filter = ("is_active", "moderation_status")
    search_fields = ("title", "body", "campaign__name")
    actions = ("mark_under_review", "remove_creatives")

    @admin.action(description="Mark selected creatives as UNDER REVIEW")
    def mark_under_review(self, request, queryset):
        updated = queryset.update(moderation_status=m.Moderation.ModerationStatus.UNDER_REVIEW)
        self.message_user(request, f"{updated} creative(s) marked under review.")

    @admin.action(description="Remove selected creatives")
    def remove_creatives(self, request, queryset):
        updated = queryset.update(moderation_status=m.Moderation.ModerationStatus.REMOVED)
        self.message_user(request, f"{updated} creative(s) removed.")


@admin.register(m.AdEvent)
class AdEventAdmin(admin.ModelAdmin):
    list_display = ("creative", "user", "event_type", "ip_hash", "placement", "created_at")
    list_filter = ("event_type", "placement", "created_at")
    search_fields = ("creative__title", "user__email")


@admin.register(m.JobPromotion)
class JobPromotionAdmin(admin.ModelAdmin):
    list_display = ("job", "campaign_name", "start_at", "end_at", "is_active")
    list_filter = ("is_active",)
    search_fields = ("job__title", "campaign_name")


@admin.register(m.ProfileView)
class ProfileViewAdmin(admin.ModelAdmin):
    list_display = ("viewer", "viewed", "ip_hash", "created_at")
    list_filter = ("created_at",)
    search_fields = ("viewer__email", "viewed__email")
    readonly_fields = ("created_at", "updated_at")