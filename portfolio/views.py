# portfolio/views.py
import json
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView as AuthLoginView, LogoutView as AuthLogoutView
from django.contrib.auth.views import PasswordResetView as AuthPasswordResetView
from django.contrib.auth.views import PasswordResetDoneView, PasswordResetConfirmView, PasswordResetCompleteView
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Count, Prefetch
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, FormView, TemplateView

from . import models as m
from . import forms as f

from .models import Skill, Company
# =============================================================================
# MIXINS
# =============================================================================

class EmployerRequiredMixin(UserPassesTestMixin):
    """Require user to be an employer or admin."""
    def test_func(self):
        return self.request.user.is_authenticated and (
            self.request.user.role in [m.CustomUser.Role.EMPLOYER, m.CustomUser.Role.ADMIN]
        )


class JobSeekerRequiredMixin(UserPassesTestMixin):
    """Require user to be a job seeker or admin."""
    def test_func(self):
        return self.request.user.is_authenticated and (
            self.request.user.role in [m.CustomUser.Role.JOB_SEEKER, m.CustomUser.Role.ADMIN]
        )


class ProfileOwnerMixin(UserPassesTestMixin):
    """Ensure the user is the profile owner."""
    def test_func(self):
        profile = self.get_object()
        return self.request.user == profile.user


class ExperienceOwnerMixin(UserPassesTestMixin):
    def test_func(self):
        exp = self.get_object()
        return self.request.user == exp.user


class EducationOwnerMixin(UserPassesTestMixin):
    def test_func(self):
        edu = self.get_object()
        return self.request.user == edu.user


class PostAuthorMixin(UserPassesTestMixin):
    def test_func(self):
        post = self.get_object()
        return self.request.user == post.author


class CommentAuthorMixin(UserPassesTestMixin):
    def test_func(self):
        comment = self.get_object()
        return self.request.user == comment.author


class JobOwnerMixin(UserPassesTestMixin):
    def test_func(self):
        job = self.get_object()
        return self.request.user == job.employer


class ApplicationOwnerMixin(UserPassesTestMixin):
    """Job seeker viewing their own application."""
    def test_func(self):
        app = self.get_object()
        return self.request.user == app.user


class ApplicationEmployerMixin(UserPassesTestMixin):
    """Employer viewing an application to their job."""
    def test_func(self):
        app = self.get_object()
        return self.request.user == app.job.employer


class CompanyAdminMixin(UserPassesTestMixin):
    """User is a company admin or staff."""
    def test_func(self):
        company = self.get_object()
        if self.request.user.is_staff:
            return True
        if not hasattr(self.request.user, "employer_profile"):
            return False
        return self.request.user.employer_profile.company == company and self.request.user.employer_profile.is_company_admin


# =============================================================================
# STATIC PAGES
# =============================================================================

class HomeView(TemplateView):
    template_name = "portfolio/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["featured_jobs"] = m.Job.objects.filter(
            is_active=True, moderation_status=m.Moderation.ModerationStatus.OK
        ).select_related("company", "employer")[:6]
        context["job_count"] = m.Job.objects.filter(is_active=True).count()
        context["user_count"] = m.CustomUser.objects.filter(is_active=True).count()
        context["company_count"] = m.Company.objects.filter(is_verified=True).count()
        return context


class AboutView(TemplateView):
    template_name = "portfolio/about.html"


class ContactView(FormView):
    template_name = "portfolio/contact.html"
    form_class = f.ReportForm  # simplified, could be a dedicated ContactForm
    success_url = reverse_lazy("portfolio:home")

    def form_valid(self, form):
        messages.success(self.request, "Thank you for contacting us!")
        return super().form_valid(form)


# =============================================================================
# AUTHENTICATION
# =============================================================================

class LoginView(AuthLoginView):
    template_name = "portfolio/auth/login.html"


class LogoutView(AuthLogoutView):
    next_page = reverse_lazy("portfolio:home")


class SignUpView(CreateView):
    model = m.CustomUser
    form_class = f.CustomUserCreationForm
    template_name = "portfolio/auth/signup.html"
    success_url = reverse_lazy("portfolio:edit_profile")

    def form_valid(self, form):
        response = super().form_valid(form)
        m.UserProfile.objects.create(user=self.object)
        if self.object.role == m.CustomUser.Role.EMPLOYER:
            m.EmployerProfile.objects.create(user=self.object)
        login(self.request, self.object)
        messages.success(self.request, "Account created! Please complete your profile.")
        return response


class PasswordResetView(AuthPasswordResetView):
    template_name = "portfolio/auth/password_reset.html"
    email_template_name = "portfolio/auth/password_reset_email.html"
    subject_template_name = "portfolio/auth/password_reset_subject.txt"
    success_url = reverse_lazy("portfolio:password_reset_done")


class PasswordResetDoneView(PasswordResetDoneView):
    template_name = "portfolio/auth/password_reset_done.html"


class PasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "portfolio/auth/password_reset_confirm.html"
    success_url = reverse_lazy("portfolio:password_reset_complete")


class PasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "portfolio/auth/password_reset_complete.html"


# =============================================================================
# PROFILE VIEWS
# =============================================================================

class ProfileView(LoginRequiredMixin, DetailView):
    model = m.CustomUser
    template_name = "portfolio/profile/my_profile.html"
    context_object_name = "profile_user"

    def get_object(self):
        return self.request.user


class PublicProfileView(DetailView):
    model = m.CustomUser
    template_name = "portfolio/profile/public_profile.html"
    context_object_name = "profile_user"

    def get_object(self):
        obj = super().get_object()
        if not obj.is_profile_public and self.request.user != obj:
            raise PermissionDenied("This profile is private.")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.object
        context["experiences"] = user.experiences.all()
        context["education"] = user.education.all()
        context["skills"] = user.skills.select_related("skill").all()
        context["posts"] = user.posts.filter(
            is_deleted=False, moderation_status=m.Moderation.ModerationStatus.OK
        )[:5]

        if self.request.user.is_authenticated and self.request.user != user:
            context["is_connected"] = m.Connection.objects.filter(
                Q(from_user=self.request.user, to_user=user, status=m.Connection.Status.ACCEPTED) |
                Q(from_user=user, to_user=self.request.user, status=m.Connection.Status.ACCEPTED)
            ).exists()
            context["has_pending_request"] = m.Connection.objects.filter(
                from_user=self.request.user, to_user=user, status=m.Connection.Status.PENDING
            ).exists()
            context["is_following"] = m.Follow.objects.filter(
                follower=self.request.user, following=user
            ).exists()
        return context


class EditProfileView(LoginRequiredMixin, UpdateView):
    model = m.UserProfile
    form_class = f.UserProfileForm
    template_name = "portfolio/profile/edit_profile.html"
    success_url = reverse_lazy("portfolio:my_profile")

    def get_object(self):
        return self.request.user.profile

    def form_valid(self, form):
        messages.success(self.request, "Profile updated.")
        return super().form_valid(form)


class EditEmployerProfileView(LoginRequiredMixin, EmployerRequiredMixin, UpdateView):
    model = m.EmployerProfile
    form_class = f.EmployerProfileForm
    template_name = "portfolio/profile/edit_employer_profile.html"
    success_url = reverse_lazy("portfolio:my_profile")

    def get_object(self):
        return self.request.user.employer_profile

    def form_valid(self, form):
        messages.success(self.request, "Employer profile updated.")
        return super().form_valid(form)


# =============================================================================
# COMPANIES
# =============================================================================

class CompanyListView(ListView):
    model = m.Company
    template_name = "portfolio/companies/company_list.html"
    context_object_name = "companies"
    paginate_by = 20

    def get_queryset(self):
        return m.Company.objects.filter(
            moderation_status=m.Moderation.ModerationStatus.OK
        ).order_by("name")


class CompanyDetailView(DetailView):
    model = m.Company
    template_name = "portfolio/companies/company_detail.html"
    context_object_name = "company"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["jobs"] = self.object.jobs.filter(is_active=True)[:10]
        context["team"] = m.EmployerProfile.objects.filter(company=self.object).select_related("user")
        return context


class CreateCompanyView(LoginRequiredMixin, EmployerRequiredMixin, CreateView):
    model = m.Company
    form_class = f.CompanyForm
    template_name = "portfolio/companies/company_form.html"
    success_url = reverse_lazy("portfolio:company_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Company created. It may be moderated before appearing.")
        return response


class EditCompanyView(LoginRequiredMixin, CompanyAdminMixin, UpdateView):
    model = m.Company
    form_class = f.CompanyForm
    template_name = "portfolio/companies/company_form.html"
    success_url = reverse_lazy("portfolio:company_list")

    def form_valid(self, form):
        messages.success(self.request, "Company updated.")
        return super().form_valid(form)


class CompanyVerificationView(LoginRequiredMixin, CompanyAdminMixin, CreateView):
    model = m.CompanyVerification
    form_class = f.CompanyVerificationForm
    template_name = "portfolio/companies/verification_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.company = get_object_or_404(m.Company, slug=kwargs["slug"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.company = self.company
        form.instance.submitted_by = self.request.user
        messages.success(self.request, "Verification documents submitted.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("portfolio:company_detail", kwargs={"slug": self.company.slug})


# =============================================================================
# EXPERIENCE & EDUCATION
# =============================================================================

class AddExperienceView(LoginRequiredMixin, CreateView):
    model = m.Experience
    form_class = f.ExperienceForm
    template_name = "portfolio/profile/experience_form.html"
    success_url = reverse_lazy("portfolio:my_profile")

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, "Experience added.")
        return super().form_valid(form)


class EditExperienceView(LoginRequiredMixin, ExperienceOwnerMixin, UpdateView):
    model = m.Experience
    form_class = f.ExperienceForm
    template_name = "portfolio/profile/experience_form.html"
    success_url = reverse_lazy("portfolio:my_profile")

    def form_valid(self, form):
        messages.success(self.request, "Experience updated.")
        return super().form_valid(form)


class DeleteExperienceView(LoginRequiredMixin, ExperienceOwnerMixin, DeleteView):
    model = m.Experience
    template_name = "portfolio/profile/confirm_delete.html"
    success_url = reverse_lazy("portfolio:my_profile")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Experience deleted.")
        return super().delete(request, *args, **kwargs)


class AddEducationView(LoginRequiredMixin, CreateView):
    model = m.Education
    form_class = f.EducationForm
    template_name = "portfolio/profile/education_form.html"
    success_url = reverse_lazy("portfolio:my_profile")

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, "Education added.")
        return super().form_valid(form)


class EditEducationView(LoginRequiredMixin, EducationOwnerMixin, UpdateView):
    model = m.Education
    form_class = f.EducationForm
    template_name = "portfolio/profile/education_form.html"
    success_url = reverse_lazy("portfolio:my_profile")

    def form_valid(self, form):
        messages.success(self.request, "Education updated.")
        return super().form_valid(form)


class DeleteEducationView(LoginRequiredMixin, EducationOwnerMixin, DeleteView):
    model = m.Education
    template_name = "portfolio/profile/confirm_delete.html"
    success_url = reverse_lazy("portfolio:my_profile")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Education deleted.")
        return super().delete(request, *args, **kwargs)


# =============================================================================
# SKILLS
# =============================================================================

class ManageSkillsView(LoginRequiredMixin, TemplateView):
    template_name = "portfolio/profile/skills.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["user_skills"] = self.request.user.skills.select_related("skill").all()
        # If a bound form exists in kwargs (from POST error), use it; otherwise empty form
        context["form"] = kwargs.get("form", f.UserSkillForm())
        return context

    def post(self, request, *args, **kwargs):
        form = f.UserSkillForm(request.POST)
        if form.is_valid():
            skill = form.cleaned_data["skill"]
            level = form.cleaned_data.get("level", 3)  # default level
            # Check if the skill already exists for this user
            existing, created = m.UserSkill.objects.get_or_create(
                user=request.user,
                skill=skill,
                defaults={"level": level}
            )
            if created:
                messages.success(request, f"Skill '{skill.name}' added.")
            else:
                messages.info(request, f"You already have the skill '{skill.name}'.")
            return redirect("portfolio:manage_skills")
        else:
            # Form is invalid – re-render with errors
            context = self.get_context_data(form=form)
            return render(request, self.template_name, context)
class EndorseSkillView(LoginRequiredMixin, View):
    def post(self, request, pk):
        user_skill = get_object_or_404(m.UserSkill, pk=pk)
        if request.user == user_skill.user:
            return JsonResponse({"error": "Cannot endorse yourself"}, status=400)
        if m.Endorsement.objects.filter(endorser=request.user, user_skill=user_skill).exists():
            return JsonResponse({"error": "Already endorsed"}, status=400)
        m.Endorsement.objects.create(endorser=request.user, user_skill=user_skill)
        return JsonResponse({"success": True, "new_count": user_skill.endorsement_count})


class SkillSearchAPIView(View):
    def get(self, request):
        query = request.GET.get("q", "")
        if len(query) < 2:
            return JsonResponse({"results": []})
        skills = m.Skill.objects.filter(name__icontains=query, is_active=True)[:10]
        results = [{"id": str(s.id), "name": s.name} for s in skills]
        return JsonResponse({"results": results})


# =============================================================================
# JOBS
# =============================================================================

class JobListView(ListView):
    model = m.Job
    template_name = "portfolio/jobs/job_list.html"
    context_object_name = "jobs"
    paginate_by = 20

    def get_queryset(self):
        return m.Job.objects.filter(
            is_active=True,
            moderation_status=m.Moderation.ModerationStatus.OK,
        ).filter(
            Q(application_deadline__gte=timezone.now()) | Q(application_deadline__isnull=True)
        ).select_related("company", "employer").prefetch_related("skills_required").order_by("-created_at")


class JobSearchView(ListView):
    model = m.Job
    template_name = "portfolio/jobs/job_search.html"
    context_object_name = "jobs"
    paginate_by = 20

    def get_queryset(self):
        form = f.JobSearchForm(self.request.GET)
        if not form.is_valid():
            return m.Job.objects.none()
        cd = form.cleaned_data
        qs = m.Job.objects.filter(
            is_active=True,
            moderation_status=m.Moderation.ModerationStatus.OK,
        ).filter(
            Q(application_deadline__gte=timezone.now()) | Q(application_deadline__isnull=True)
        )

        if cd.get("q"):
            qs = qs.filter(
                Q(title__icontains=cd["q"]) |
                Q(description__icontains=cd["q"]) |
                Q(company__name__icontains=cd["q"]) |
                Q(employer__company_name__icontains=cd["q"])
            )

        if cd.get("location"):
            qs = qs.filter(
                Q(location__icontains=cd["location"]) |
                Q(location_city__icontains=cd["location"]) |
                Q(location_country__icontains=cd["location"])
            )

        if cd.get("employment_type"):
            qs = qs.filter(employment_type__in=cd["employment_type"])

        if cd.get("experience_level"):
            qs = qs.filter(experience_level__in=cd["experience_level"])

        if cd.get("remote_status"):
            qs = qs.filter(remote_status__in=cd["remote_status"])

        if cd.get("salary_min"):
            qs = qs.filter(salary_max__gte=cd["salary_min"])

        if cd.get("salary_max"):
            qs = qs.filter(salary_min__lte=cd["salary_max"])

        sort = cd.get("sort_by")
        if sort == "newest":
            qs = qs.order_by("-created_at")
        elif sort == "oldest":
            qs = qs.order_by("created_at")
        elif sort == "salary_high":
            qs = qs.order_by("-salary_max")
        elif sort == "salary_low":
            qs = qs.order_by("salary_min")
        else:
            qs = qs.order_by("-created_at")

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = f.JobSearchForm(self.request.GET or None)
        return context


class JobDetailView(DetailView):
    model = m.Job
    template_name = "portfolio/jobs/job_detail.html"
    context_object_name = "job"

    def get_object(self):
        obj = super().get_object()
        obj.bump_views()
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            context["has_applied"] = m.JobApplication.objects.filter(
                user=self.request.user, job=self.object
            ).exists()
            context["is_saved"] = m.SavedJob.objects.filter(
                user=self.request.user, job=self.object
            ).exists()
        return context


class PostJobView(LoginRequiredMixin, EmployerRequiredMixin, CreateView):
    model = m.Job
    form_class = f.JobPostForm
    template_name = "portfolio/jobs/post_job.html"
    success_url = reverse_lazy("portfolio:job_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Job posted! It will be reviewed.")
        return super().form_valid(form)


class EditJobView(LoginRequiredMixin, JobOwnerMixin, UpdateView):
    model = m.Job
    form_class = f.JobPostForm
    template_name = "portfolio/jobs/edit_job.html"
    success_url = reverse_lazy("portfolio:job_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Job updated.")
        return super().form_valid(form)


class DeleteJobView(LoginRequiredMixin, JobOwnerMixin, DeleteView):
    model = m.Job
    template_name = "portfolio/jobs/confirm_delete.html"
    success_url = reverse_lazy("portfolio:job_list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Job deleted.")
        return super().delete(request, *args, **kwargs)


class ApplyJobView(LoginRequiredMixin, JobSeekerRequiredMixin, FormView):
    form_class = f.JobApplicationForm
    template_name = "portfolio/jobs/apply_job.html"

    def dispatch(self, request, *args, **kwargs):
        self.job = get_object_or_404(m.Job, slug=kwargs["slug"])
        if not self.job.is_active or (self.job.application_deadline and self.job.application_deadline < timezone.now()):
            messages.error(request, "This job is no longer accepting applications.")
            return redirect("portfolio:job_detail", slug=self.job.slug)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        kwargs["job"] = self.job
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Application submitted!")
        return redirect("portfolio:job_detail", slug=self.job.slug)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["job"] = self.job
        return context


class SaveJobView(LoginRequiredMixin, View):
    def post(self, request, slug):
        job = get_object_or_404(m.Job, slug=slug)
        m.SavedJob.objects.get_or_create(user=request.user, job=job)
        return JsonResponse({"success": True})


class UnsaveJobView(LoginRequiredMixin, View):
    def post(self, request, slug):
        job = get_object_or_404(m.Job, slug=slug)
        m.SavedJob.objects.filter(user=request.user, job=job).delete()
        return JsonResponse({"success": True})


class SavedJobsView(LoginRequiredMixin, ListView):
    model = m.SavedJob
    template_name = "portfolio/jobs/saved_jobs.html"
    context_object_name = "saved_jobs"
    paginate_by = 20

    def get_queryset(self):
        return m.SavedJob.objects.filter(user=self.request.user).select_related("job", "job__company").order_by("-created_at")


# =============================================================================
# APPLICATIONS
# =============================================================================

class MyApplicationsView(LoginRequiredMixin, JobSeekerRequiredMixin, ListView):
    model = m.JobApplication
    template_name = "portfolio/applications/my_applications.html"
    context_object_name = "applications"
    paginate_by = 20

    def get_queryset(self):
        return m.JobApplication.objects.filter(user=self.request.user).select_related("job", "job__company").order_by("-applied_at")


class ApplicationDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = m.JobApplication
    template_name = "portfolio/applications/application_detail.html"
    context_object_name = "application"

    def test_func(self):
        app = self.get_object()
        return self.request.user == app.user or self.request.user == app.job.employer


class WithdrawApplicationView(LoginRequiredMixin, ApplicationOwnerMixin, View):
    def post(self, request, pk):
        app = get_object_or_404(m.JobApplication, pk=pk)
        if app.status not in [app.Status.HIRED, app.Status.REJECTED]:
            app.update_status(m.JobApplication.Status.WITHDRAWN, request.user)
            messages.success(request, "Application withdrawn.")
        else:
            messages.error(request, "Cannot withdraw application in current status.")
        return redirect("portfolio:my_applications")


class JobApplicationsView(LoginRequiredMixin, EmployerRequiredMixin, ListView):
    model = m.JobApplication
    template_name = "portfolio/applications/job_applications.html"
    context_object_name = "applications"
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        self.job = get_object_or_404(m.Job, slug=kwargs["slug"])
        if self.job.employer != request.user and not request.user.is_staff:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return m.JobApplication.objects.filter(job=self.job).select_related("user").order_by("-applied_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["job"] = self.job
        return context


class UpdateApplicationStatusView(LoginRequiredMixin, ApplicationEmployerMixin, View):
    def post(self, request, pk):
        app = get_object_or_404(m.JobApplication, pk=pk)
        new_status = request.POST.get("status")
        if new_status not in [choice[0] for choice in m.JobApplication.Status.choices]:
            return JsonResponse({"error": "Invalid status"}, status=400)
        app.update_status(new_status, request.user)
        return JsonResponse({"success": True})


# =============================================================================
# JOB ALERTS
# =============================================================================

class JobAlertListView(LoginRequiredMixin, ListView):
    model = m.JobAlert
    template_name = "portfolio/alerts/job_alerts.html"
    context_object_name = "alerts"

    def get_queryset(self):
        return m.JobAlert.objects.filter(user=self.request.user).order_by("-created_at")


class CreateJobAlertView(LoginRequiredMixin, CreateView):
    model = m.JobAlert
    form_class = f.JobAlertForm
    template_name = "portfolio/alerts/job_alert_form.html"
    success_url = reverse_lazy("portfolio:job_alerts")

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, "Job alert created.")
        return super().form_valid(form)


class EditJobAlertView(LoginRequiredMixin, UpdateView):
    model = m.JobAlert
    form_class = f.JobAlertForm
    template_name = "portfolio/alerts/job_alert_form.html"
    success_url = reverse_lazy("portfolio:job_alerts")

    def get_queryset(self):
        return m.JobAlert.objects.filter(user=self.request.user)


class DeleteJobAlertView(LoginRequiredMixin, DeleteView):
    model = m.JobAlert
    template_name = "portfolio/alerts/confirm_delete.html"
    success_url = reverse_lazy("portfolio:job_alerts")

    def get_queryset(self):
        return m.JobAlert.objects.filter(user=self.request.user)


class ToggleJobAlertView(LoginRequiredMixin, View):
    def post(self, request, pk):
        alert = get_object_or_404(m.JobAlert, pk=pk, user=request.user)
        alert.is_active = not alert.is_active
        alert.save()
        return JsonResponse({"is_active": alert.is_active})


# =============================================================================
# SOCIAL FEED
# =============================================================================

class FeedView(LoginRequiredMixin, ListView):
    model = m.Post
    template_name = "portfolio/social/feed.html"
    context_object_name = "posts"
    paginate_by = 10

    def get_queryset(self):
        user = self.request.user
        connections = m.Connection.objects.filter(
            Q(from_user=user, status=m.Connection.Status.ACCEPTED) |
            Q(to_user=user, status=m.Connection.Status.ACCEPTED)
        )
        connected_ids = set()
        for c in connections:
            if c.from_user_id == user.id:
                connected_ids.add(c.to_user_id)
            else:
                connected_ids.add(c.from_user_id)

        following_ids = set(m.Follow.objects.filter(follower=user).values_list("following_id", flat=True))
        visible_ids = connected_ids | following_ids | {user.id}

        return m.Post.objects.filter(
            author_id__in=visible_ids,
            is_deleted=False,
            moderation_status=m.Moderation.ModerationStatus.OK
        ).select_related("author").prefetch_related(
            Prefetch("likes", queryset=m.PostLike.objects.filter(user=user), to_attr="liked_by_user")
        ).order_by("-created_at")


class PostDetailView(LoginRequiredMixin, DetailView):
    model = m.Post
    template_name = "portfolio/social/post_detail.html"
    context_object_name = "post"

    def get_object(self):
        obj = super().get_object()
        if not obj.can_view(self.request.user):
            raise PermissionDenied("You cannot view this post.")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["comment_form"] = f.CommentForm()
        context["liked"] = self.object.likes.filter(user=self.request.user).exists()
        return context


class CreatePostView(LoginRequiredMixin, CreateView):
    model = m.Post
    form_class = f.PostForm
    template_name = "portfolio/social/post_form.html"
    success_url = reverse_lazy("portfolio:feed")

    def form_valid(self, form):
        form.instance.author = self.request.user
        messages.success(self.request, "Post created.")
        return super().form_valid(form)


class EditPostView(LoginRequiredMixin, PostAuthorMixin, UpdateView):
    model = m.Post
    form_class = f.PostForm
    template_name = "portfolio/social/post_form.html"
    success_url = reverse_lazy("portfolio:feed")

    def form_valid(self, form):
        messages.success(self.request, "Post updated.")
        return super().form_valid(form)


class DeletePostView(LoginRequiredMixin, PostAuthorMixin, DeleteView):
    model = m.Post
    template_name = "portfolio/social/confirm_delete.html"
    success_url = reverse_lazy("portfolio:feed")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Post deleted.")
        return super().delete(request, *args, **kwargs)


class LikePostView(LoginRequiredMixin, View):
    def post(self, request, pk):
        post = get_object_or_404(m.Post, pk=pk)
        try:
            m.PostLike.like(post, request.user)
            return JsonResponse({"success": True, "like_count": post.like_count + 1})
        except ValidationError as e:
            return JsonResponse({"error": str(e)}, status=400)


class UnlikePostView(LoginRequiredMixin, View):
    def post(self, request, pk):
        post = get_object_or_404(m.Post, pk=pk)
        m.PostLike.unlike(post, request.user)
        return JsonResponse({"success": True, "like_count": max(0, post.like_count - 1)})


class AddCommentView(LoginRequiredMixin, View):
    def post(self, request, pk):
        post = get_object_or_404(m.Post, pk=pk)
        if not post.can_view(request.user):
            return JsonResponse({"error": "Cannot comment"}, status=403)
        form = f.CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.post = post
            comment.author = request.user
            comment.save()
            return JsonResponse({
                "success": True,
                "comment": {
                    "id": str(comment.id),
                    "author": comment.author.display_name(),
                    "content": comment.content,
                    "created_at": comment.created_at.isoformat(),
                }
            })
        return JsonResponse({"errors": form.errors}, status=400)


class DeleteCommentView(LoginRequiredMixin, CommentAuthorMixin, DeleteView):
    model = m.PostComment
    template_name = "portfolio/social/confirm_delete.html"
    success_url = reverse_lazy("portfolio:feed")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Comment deleted.")
        return super().delete(request, *args, **kwargs)


# =============================================================================
# NETWORK
# =============================================================================

class NetworkView(LoginRequiredMixin, TemplateView):
    template_name = "portfolio/network/network.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["pending_requests"] = m.Connection.objects.filter(
            to_user=user, status=m.Connection.Status.PENDING
        ).select_related("from_user").order_by("-created_at")[:5]

        context["suggestions"] = m.CustomUser.objects.filter(
            is_profile_public=True,
            role=m.CustomUser.Role.JOB_SEEKER
        ).exclude(id=user.id)[:5]

        context["connection_count"] = m.Connection.objects.filter(
            Q(from_user=user) | Q(to_user=user),
            status=m.Connection.Status.ACCEPTED
        ).count()
        return context


class ConnectionListView(LoginRequiredMixin, ListView):
    model = m.Connection
    template_name = "portfolio/network/connections.html"
    context_object_name = "connections"
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        return m.Connection.objects.filter(
            Q(from_user=user) | Q(to_user=user),
            status=m.Connection.Status.ACCEPTED
        ).select_related("from_user", "to_user").order_by("-created_at")


class FollowerListView(LoginRequiredMixin, ListView):
    model = m.Follow
    template_name = "portfolio/network/followers.html"
    context_object_name = "followers"
    paginate_by = 20

    def get_queryset(self):
        return m.Follow.objects.filter(following=self.request.user).select_related("follower").order_by("-created_at")


class FollowingListView(LoginRequiredMixin, ListView):
    model = m.Follow
    template_name = "portfolio/network/following.html"
    context_object_name = "following"
    paginate_by = 20

    def get_queryset(self):
        return m.Follow.objects.filter(follower=self.request.user).select_related("following").order_by("-created_at")


class SendConnectionRequestView(LoginRequiredMixin, View):
    def post(self, request, user_id):
        to_user = get_object_or_404(m.CustomUser, id=user_id)
        if request.user == to_user:
            return JsonResponse({"error": "Cannot connect with yourself"}, status=400)

        existing = m.Connection.objects.filter(
            Q(from_user=request.user, to_user=to_user) | Q(from_user=to_user, to_user=request.user)
        ).first()
        if existing:
            return JsonResponse({"error": f"Connection already {existing.status}"}, status=400)

        if m.Block.objects.filter(
            Q(blocker=request.user, blocked=to_user) | Q(blocker=to_user, blocked=request.user)
        ).exists():
            return JsonResponse({"error": "Cannot send request due to block"}, status=400)

        m.Connection.objects.create(from_user=request.user, to_user=to_user)
        return JsonResponse({"success": True})


class ConnectionRequestsView(LoginRequiredMixin, ListView):
    model = m.Connection
    template_name = "portfolio/network/connection_requests.html"
    context_object_name = "requests"
    paginate_by = 20

    def get_queryset(self):
        return m.Connection.objects.filter(
            to_user=self.request.user, status=m.Connection.Status.PENDING
        ).select_related("from_user").order_by("-created_at")


class AcceptConnectionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        connection = get_object_or_404(m.Connection, pk=pk, to_user=request.user, status=m.Connection.Status.PENDING)
        connection.accept()
        return JsonResponse({"success": True})


class DeclineConnectionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        connection = get_object_or_404(m.Connection, pk=pk, to_user=request.user, status=m.Connection.Status.PENDING)
        connection.decline()
        return JsonResponse({"success": True})


class FollowUserView(LoginRequiredMixin, View):
    def post(self, request, user_id):
        to_user = get_object_or_404(m.CustomUser, id=user_id)
        if request.user == to_user:
            return JsonResponse({"error": "Cannot follow yourself"}, status=400)
        m.Follow.objects.get_or_create(follower=request.user, following=to_user)
        return JsonResponse({"success": True})


class UnfollowUserView(LoginRequiredMixin, View):
    def post(self, request, user_id):
        to_user = get_object_or_404(m.CustomUser, id=user_id)
        m.Follow.objects.filter(follower=request.user, following=to_user).delete()
        return JsonResponse({"success": True})


# =============================================================================
# RECOMMENDATIONS
# =============================================================================

class WriteRecommendationView(LoginRequiredMixin, FormView):
    template_name = "portfolio/network/write_recommendation.html"
    form_class = f.RecommendationForm

    def dispatch(self, request, *args, **kwargs):
        self.recommendee = get_object_or_404(m.CustomUser, id=kwargs["user_id"])
        if not m.Connection.objects.filter(
            Q(from_user=request.user, to_user=self.recommendee, status=m.Connection.Status.ACCEPTED) |
            Q(from_user=self.recommendee, to_user=request.user, status=m.Connection.Status.ACCEPTED)
        ).exists():
            messages.error(request, "You can only recommend connected users.")
            return redirect("portfolio:public_profile", pk=self.recommendee.id)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.recommender = self.request.user
        form.instance.recommendee = self.recommendee
        form.save()
        messages.success(self.request, "Recommendation sent.")
        return redirect("portfolio:public_profile", pk=self.recommendee.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["recommendee"] = self.recommendee
        return context


# =============================================================================
# MESSAGING
# =============================================================================

class ConversationListView(LoginRequiredMixin, ListView):
    model = m.Conversation
    template_name = "portfolio/messages/conversations.html"
    context_object_name = "conversations"
    paginate_by = 20

    def get_queryset(self):
        return self.request.user.conversations.all().order_by("-last_message_at")


class NewConversationView(LoginRequiredMixin, View):
    def get(self, request, user_id):
        other_user = get_object_or_404(m.CustomUser, id=user_id)
        conv = m.Conversation.get_or_create_direct(request.user, other_user)
        return redirect("portfolio:conversation_detail", pk=conv.id)


class ConversationDetailView(LoginRequiredMixin, DetailView):
    model = m.Conversation
    template_name = "portfolio/messages/conversation_detail.html"
    context_object_name = "conversation"

    def get_object(self):
        obj = super().get_object()
        if not obj.can_participate(self.request.user):
            raise PermissionDenied
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        messages_qs = self.object.messages.filter(
            is_deleted=False,
            moderation_status=m.Moderation.ModerationStatus.OK
        ).select_related("sender").order_by("created_at")

        for msg in messages_qs:
            if msg.sender != self.request.user:
                delivery = msg.deliveries.filter(user=self.request.user).first()
                if delivery and not delivery.read_at:
                    delivery.mark_read()

        context["messages"] = messages_qs
        context["form"] = f.DirectMessageForm()
        return context


class SendMessageView(LoginRequiredMixin, View):
    def post(self, request, pk):
        conversation = get_object_or_404(m.Conversation, pk=pk)
        if not conversation.can_participate(request.user):
            return JsonResponse({"error": "Cannot send message"}, status=403)

        form = f.DirectMessageForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                msg = m.DirectMessage.send(
                    conversation=conversation,
                    sender=request.user,
                    content=form.cleaned_data["content"],
                    attachment=request.FILES.get("attachment")
                )
                return JsonResponse({
                    "success": True,
                    "message": {
                        "id": str(msg.id),
                        "content": msg.content,
                        "sender": msg.sender.display_name(),
                        "created_at": msg.created_at.isoformat(),
                    }
                })
            except ValidationError as e:
                return JsonResponse({"error": str(e)}, status=400)
        return JsonResponse({"errors": form.errors}, status=400)


# =============================================================================
# NOTIFICATIONS
# =============================================================================

class NotificationListView(LoginRequiredMixin, ListView):
    model = m.Notification
    template_name = "portfolio/notifications/notifications.html"
    context_object_name = "notifications"
    paginate_by = 20

    def get_queryset(self):
        return self.request.user.notifications.all().order_by("-created_at")


class MarkNotificationReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        notif = get_object_or_404(m.Notification, pk=pk, recipient=request.user)
        notif.mark_read()
        return JsonResponse({"success": True})


class MarkAllNotificationsReadView(LoginRequiredMixin, View):
    def post(self, request):
        request.user.notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
        return JsonResponse({"success": True})


# =============================================================================
# SEARCH
# =============================================================================

class GlobalSearchView(TemplateView):
    template_name = "portfolio/search/global_search.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "").strip()
        context["query"] = query
        if query:
            context["jobs"] = m.Job.objects.filter(
                Q(title__icontains=query) | Q(description__icontains=query),
                is_active=True,
                moderation_status=m.Moderation.ModerationStatus.OK
            )[:5]

            context["users"] = m.CustomUser.objects.filter(
                Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(headline__icontains=query),
                is_profile_public=True,
                is_active=True
            )[:5]

            context["companies"] = m.Company.objects.filter(
                name__icontains=query,
                moderation_status=m.Moderation.ModerationStatus.OK
            )[:5]

            context["skills"] = m.Skill.objects.filter(name__icontains=query, is_active=True)[:5]
        return context


class UserSearchView(ListView):
    model = m.CustomUser
    template_name = "portfolio/search/user_search.html"
    context_object_name = "users"
    paginate_by = 20

    def get_queryset(self):
        form = f.UserSearchForm(self.request.GET)
        if not form.is_valid():
            return m.CustomUser.objects.none()
        cd = form.cleaned_data
        qs = m.CustomUser.objects.filter(is_active=True, is_profile_public=True)

        if cd.get("q"):
            qs = qs.filter(
                Q(first_name__icontains=cd["q"]) |
                Q(last_name__icontains=cd["q"]) |
                Q(headline__icontains=cd["q"]) |
                Q(profile__bio__icontains=cd["q"])
            )

        if cd.get("location"):
            qs = qs.filter(profile__location__icontains=cd["location"])

        if cd.get("role"):
            qs = qs.filter(role=cd["role"])

        if cd.get("skills"):
            skill_names = [s.strip() for s in cd["skills"].split(",") if s.strip()]
            if skill_names:
                qs = qs.filter(skills__skill__name__in=skill_names).distinct()

        if cd.get("open_to_work"):
            qs = qs.filter(profile__open_to_work=True)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = f.UserSearchForm(self.request.GET or None)
        return context


# =============================================================================
# REPORTS / MODERATION
# =============================================================================

class ReportListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    model = m.Report
    template_name = "portfolio/moderation/reports.html"
    context_object_name = "reports"
    paginate_by = 20

    def test_func(self):
        return self.request.user.is_staff or self.request.user.role == m.CustomUser.Role.ADMIN

    def get_queryset(self):
        return m.Report.objects.filter(is_resolved=False).order_by("-created_at")


class CreateReportView(LoginRequiredMixin, CreateView):
    model = m.Report
    form_class = f.ReportForm
    template_name = "portfolio/moderation/create_report.html"

    def dispatch(self, request, *args, **kwargs):
        self.content_type = get_object_or_404(ContentType, id=kwargs["content_type_id"])
        self.object_id = kwargs["object_id"]
        self.target = self.content_type.get_object_for_this_type(id=self.object_id)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.reporter = self.request.user
        form.instance.content_type = self.content_type
        form.instance.object_id = self.object_id
        form.instance.target = self.target
        messages.success(self.request, "Report submitted. Thank you for helping keep our community safe.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("portfolio:home")


class ResolveReportView(LoginRequiredMixin, UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_staff or self.request.user.role == m.CustomUser.Role.ADMIN

    def post(self, request, pk):
        report = get_object_or_404(m.Report, pk=pk)
        report.resolve(request.user)
        return JsonResponse({"success": True})


# =============================================================================
# ERROR HANDLERS
# =============================================================================

def custom_404(request, exception):
    return render(request, "portfolio/404.html", status=404)


def custom_500(request):
    return render(request, "portfolio/500.html", status=500)










from dal import autocomplete


class SkillAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Skill.objects.none()
        qs = Skill.objects.filter(is_active=True)
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs

class CompanyAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Company.objects.none()
        qs = Company.objects.filter(moderation_status=Company.ModerationStatus.OK)
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs






def skill_id_by_name(request):
    """Return the ID of a skill given its name (case‑insensitive)."""
    name = request.GET.get('name', '')
    try:
        skill = Skill.objects.get(name__iexact=name, is_active=True)
        return JsonResponse({'id': skill.id})
    except Skill.DoesNotExist:
        return JsonResponse({'error': 'Skill not found'}, status=404)






# =============================================================================
# STATIC PAGES (About, Contact, Privacy, Terms)
# =============================================================================

class AboutView(TemplateView):
    template_name = "portfolio/about.html"

class ContactView(FormView):
    template_name = "portfolio/contact.html"
    form_class = f.ReportForm  # You can create a dedicated ContactForm later
    success_url = reverse_lazy("portfolio:home")

    def form_valid(self, form):
        # You would typically send an email here
        messages.success(self.request, "Thank you for contacting us!")
        return super().form_valid(form)

class PrivacyView(TemplateView):
    template_name = "portfolio/privacy.html"

class TermsView(TemplateView):
    template_name = "portfolio/terms.html"