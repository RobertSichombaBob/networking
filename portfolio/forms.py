# forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.core.exceptions import ValidationError
from django.db.models import Q
from dal import autocomplete  # must be installed

from . import models as m


# =============================================================================
# USER / AUTHENTICATION FORMS
# =============================================================================

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "your.email@example.com"})
    )

    class Meta:
        model = m.CustomUser
        fields = ("email", "first_name", "last_name", "role")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if m.CustomUser.objects.filter(email=email).exists():
            raise ValidationError("A user with that email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"].lower()
        if commit:
            user.save()
        return user


class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = m.CustomUser
        fields = (
            "email", "first_name", "last_name", "phone", "role",
            "headline", "current_position", "is_profile_public",
            "allow_messages_from", "preferences"
        )


# =============================================================================
# PROFILE FORMS
# =============================================================================

class UserProfileForm(forms.ModelForm):
    preferred_job_types = forms.MultipleChoiceField(
        choices=m.Job.EmploymentType.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Preferred job types"
    )

    preferred_locations = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "One location per line", "list": "location-suggestions"}),
        label="Preferred locations",
        help_text="Enter each location on a new line. Suggestions will appear as you type."
    )

    class Meta:
        model = m.UserProfile
        fields = (
            "bio", "avatar", "cover_image", "location",
            "website", "linkedin", "github", "twitter",
            "open_to_work", "open_to_relocation",
            "preferred_job_types", "preferred_locations", "resume"
        )
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4, "placeholder": "Tell us about yourself..."}),
            "location": forms.TextInput(attrs={"placeholder": "e.g., Lusaka, Zambia", "list": "location-suggestions"}),
            "website": forms.URLInput(attrs={"placeholder": "https://example.com"}),
            "linkedin": forms.URLInput(attrs={"placeholder": "https://linkedin.com/in/username"}),
            "github": forms.URLInput(attrs={"placeholder": "https://github.com/username"}),
            "twitter": forms.URLInput(attrs={"placeholder": "https://twitter.com/username"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.preferred_locations:
            locs = self.instance.preferred_locations
            if isinstance(locs, list):
                self.initial['preferred_locations'] = '\n'.join(locs)

    def clean_preferred_job_types(self):
        value = self.cleaned_data.get('preferred_job_types')
        return value if value is not None else []

    def clean_preferred_locations(self):
        value = self.cleaned_data.get('preferred_locations', '')
        if isinstance(value, str):
            lines = [line.strip() for line in value.splitlines() if line.strip()]
            return lines
        return value


class EmployerProfileForm(forms.ModelForm):
    class Meta:
        model = m.EmployerProfile
        fields = ("company", "title", "is_company_admin")
        # company is a foreign key – in the view we'll limit choices to companies the user can manage


# =============================================================================
# COMPANY FORMS
# =============================================================================

class CompanyForm(forms.ModelForm):
    class Meta:
        model = m.Company
        fields = ("name", "website", "industry", "size", "logo", "moderation_status", "moderation_reason")
        widgets = {
            "moderation_reason": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_name(self):
        name = self.cleaned_data["name"]
        if m.Company.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError("A company with this name already exists.")
        return name


class CompanyVerificationForm(forms.ModelForm):
    class Meta:
        model = m.CompanyVerification
        fields = ("document", "notes")
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Additional information (optional)"}),
        }


# =============================================================================
# EXPERIENCE & EDUCATION FORMS (with datalist support)
# =============================================================================

DEGREE_CHOICES = [
    "High School Diploma", "Associate Degree", "Bachelor's Degree",
    "Master's Degree", "PhD / Doctorate", "MBA", "Certificate", "Diploma", "Other"
]

FIELD_OF_STUDY_CHOICES = [
    "Computer Science", "Engineering", "Business Administration", "Finance",
    "Marketing", "Data Science", "Information Technology", "Economics",
    "Mathematics", "Physics", "Chemistry", "Biology", "Medicine", "Law",
    "Education", "Arts", "Other"
]


class EducationForm(forms.ModelForm):
    degree = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={"list": "degree-suggestions", "placeholder": "e.g., Bachelor's Degree"}),
        label="Degree"
    )
    field_of_study = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"list": "field-suggestions", "placeholder": "e.g., Computer Science"}),
        label="Field of study"
    )

    class Meta:
        model = m.Education
        fields = ("school", "degree", "field_of_study", "grade", "is_current", "start_date", "end_date",
                  "description", "activities")
        widgets = {
            "school": forms.TextInput(attrs={"placeholder": "e.g., University of Zambia", "list": "school-suggestions"}),
            "grade": forms.TextInput(attrs={"placeholder": "e.g., Distinction, 3.8 GPA"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3, "placeholder": "Describe your studies..."}),
            "activities": forms.Textarea(attrs={"rows": 2, "placeholder": "Societies, sports, etc."}),
        }
        labels = {
            "school": "School / University",
            "grade": "Grade / GPA (optional)",
        }

    def clean(self):
        cleaned_data = super().clean()
        is_current = cleaned_data.get("is_current")
        end_date = cleaned_data.get("end_date")
        start_date = cleaned_data.get("start_date")
        if is_current and end_date:
            raise ValidationError("End date should be empty for current education.")
        if not is_current and not end_date:
            raise ValidationError("End date is required for completed education.")
        if end_date and start_date and end_date <= start_date:
            raise ValidationError("End date must be after start date.")
        return cleaned_data


class ExperienceForm(forms.ModelForm):
    location = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "e.g., Lusaka, Zambia", "list": "location-suggestions"}),
        label="Location"
    )

    class Meta:
        model = m.Experience
        fields = ("title", "company", "location", "is_current", "start_date", "end_date", "description", "media")
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g., Senior Software Engineer"}),
            "company": forms.TextInput(attrs={"placeholder": "e.g., Google"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 4, "placeholder": "Describe your responsibilities and achievements..."}),
        }

    def clean(self):
        cleaned_data = super().clean()
        is_current = cleaned_data.get("is_current")
        end_date = cleaned_data.get("end_date")
        start_date = cleaned_data.get("start_date")
        if is_current and end_date:
            raise ValidationError("End date should be empty for current position.")
        if not is_current and not end_date:
            raise ValidationError("End date is required for past positions.")
        if end_date and start_date and end_date <= start_date:
            raise ValidationError("End date must be after start date.")
        return cleaned_data


# =============================================================================
# SKILLS & ENDORSEMENTS (with autocomplete)
# =============================================================================

class UserSkillForm(forms.ModelForm):
    skill = forms.ModelChoiceField(
        queryset=m.Skill.objects.filter(is_active=True).order_by('name'),
        empty_label="Select a skill",
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Skill"
    )

    class Meta:
        model = m.UserSkill
        fields = ("skill", "level")
        widgets = {
            "level": forms.NumberInput(attrs={"type": "range", "min": 1, "max": 5, "class": "form-range"}),
        }
        help_texts = {
            "level": "Rate your proficiency (1 = beginner, 5 = expert)",
        }


class SkillForm(forms.ModelForm):
    class Meta:
        model = m.Skill
        fields = ("name", "category", "description", "is_active")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }


class EndorsementForm(forms.ModelForm):
    class Meta:
        model = m.Endorsement
        fields = ()  # handled by view


# =============================================================================
# JOB FORMS
# =============================================================================

class JobPostForm(forms.ModelForm):
    company = forms.ModelChoiceField(
        queryset=m.Company.objects.filter(moderation_status=m.Company.ModerationStatus.OK),
        widget=autocomplete.ModelSelect2(url='portfolio:company_autocomplete'),
        required=False,
        label="Company"
    )

    class Meta:
        model = m.Job
        fields = (
            "title", "company", "description", "responsibilities", "requirements", "benefits",
            "employment_type", "experience_level", "remote_status",
            "location", "location_country", "location_city",
            "salary_min", "salary_max", "salary_currency", "salary_visible",
            "skills_required", "application_deadline", "external_application_url", "apply_email",  # <-- added
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "responsibilities": forms.Textarea(attrs={"rows": 4}),
            "requirements": forms.Textarea(attrs={"rows": 4}),
            "benefits": forms.Textarea(attrs={"rows": 4}),
            "application_deadline": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "skills_required": forms.SelectMultiple(attrs={"size": 10}),
            "location": forms.TextInput(attrs={"list": "location-suggestions", "placeholder": "e.g., Lusaka, Zambia"}),
            "external_application_url": forms.URLInput(attrs={"placeholder": "https://..."}),
            "apply_email": forms.EmailInput(attrs={"placeholder": "hr@company.com"}),
        }
        help_texts = {
            "salary_currency": "e.g., ZMW, USD",
            "external_application_url": "Leave blank to accept applications on our platform",
            "apply_email": "Candidates will send their CV to this email address (external).",
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.user and hasattr(self.user, "employer_profile") and self.user.employer_profile:
            self.fields["company"].queryset = m.Company.objects.filter(
                Q(team=self.user.employer_profile) | Q(is_verified=True)
            ).distinct()
        self.fields["skills_required"].queryset = m.Skill.objects.filter(is_active=True)

    def clean(self):
        cleaned_data = super().clean()
        salary_min = cleaned_data.get("salary_min")
        salary_max = cleaned_data.get("salary_max")
        if salary_min and salary_max and salary_min > salary_max:
            raise ValidationError("Minimum salary cannot be greater than maximum salary.")
        return cleaned_data

    def save(self, commit=True):
        job = super().save(commit=False)
        if self.user:
            job.employer = self.user
        if commit:
            job.save()
            self.save_m2m()
        return job


class JobApplicationForm(forms.ModelForm):
    class Meta:
        model = m.JobApplication
        fields = ("cover_letter", "resume", "additional_docs")
        widgets = {
            "cover_letter": forms.Textarea(attrs={"rows": 6, "placeholder": "Write your cover letter here..."}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.job = kwargs.pop("job", None)
        super().__init__(*args, **kwargs)
        if self.user and hasattr(self.user, "profile") and self.user.profile.resume:
            self.fields["resume"].initial = self.user.profile.resume

    def clean(self):
        cleaned_data = super().clean()
        if self.user and self.job:
            if m.JobApplication.objects.filter(user=self.user, job=self.job).exists():
                raise ValidationError("You have already applied for this job.")
            if self.user == self.job.employer:
                raise ValidationError("You cannot apply to your own job posting.")
        return cleaned_data

    def save(self, commit=True):
        app = super().save(commit=False)
        app.user = self.user
        app.job = self.job
        if commit:
            app.save()
            # Increment job's application counter
            from django.db import models
            m.Job.objects.filter(pk=self.job.pk).update(applications_count=models.F("applications_count") + 1)
            # Notify employer
            m.Notification.create_application(
                self.job.employer,
                "New application",
                f"{self.user.display_name()} applied for {self.job.title}.",
                target=app
            )
        return app


class JobAlertForm(forms.ModelForm):
    class Meta:
        model = m.JobAlert
        fields = ("name", "keywords", "location", "employment_type", "experience_level", "remote_status", "frequency")
        widgets = {
            "keywords": forms.TextInput(attrs={"placeholder": "e.g., python, django, remote"}),
            "location": forms.TextInput(attrs={"list": "location-suggestions"}),
        }


# =============================================================================
# SOCIAL / POST FORMS
# =============================================================================

from django import forms
from . import models as m

class PostForm(forms.ModelForm):
    # Override the tags field to be a CharField with a clean method
    tags = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'e.g., python, django, job',
            'class': 'form-control'
        }),
        help_text="Comma‑separated tags (optional)"
    )

    class Meta:
        model = m.Post
        fields = ("content", "media", "visibility", "tags")
        widgets = {
            "content": forms.Textarea(attrs={
                "rows": 4,
                "placeholder": "What do you want to share?"
            }),
            "media": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "visibility": forms.Select(attrs={"class": "form-select"}),
        }

    def clean_tags(self):
        """Convert comma‑separated string into a list of stripped tags."""
        tags_string = self.cleaned_data.get('tags', '')
        if not tags_string:
            return []
        tags = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        return tags

    def save(self, commit=True):
        instance = super().save(commit=False)
        # The tags field is already a list after clean_tags, assign directly
        instance.tags = self.cleaned_data['tags']
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class CommentForm(forms.ModelForm):
    class Meta:
        model = m.PostComment
        fields = ("content",)
        widgets = {
            "content": forms.Textarea(attrs={"rows": 2, "placeholder": "Write a comment..."}),
        }


# =============================================================================
# MESSAGING FORMS
# =============================================================================

class DirectMessageForm(forms.ModelForm):
    class Meta:
        model = m.DirectMessage
        fields = ("content", "attachment")
        widgets = {
            "content": forms.Textarea(attrs={"rows": 3, "placeholder": "Type your message..."}),
        }


# =============================================================================
# RECOMMENDATION FORMS
# =============================================================================

class RecommendationForm(forms.ModelForm):
    class Meta:
        model = m.Recommendation
        fields = ("relationship", "content", "is_public")
        widgets = {
            "relationship": forms.TextInput(attrs={"placeholder": "e.g., 'was my manager at Company X'"}),
            "content": forms.Textarea(attrs={"rows": 4, "placeholder": "Write your recommendation..."}),
        }


# =============================================================================
# REPORTING FORMS
# =============================================================================

class ReportForm(forms.ModelForm):
    class Meta:
        model = m.Report
        fields = ("reason", "details")
        widgets = {
            "reason": forms.TextInput(attrs={"placeholder": "Brief reason"}),
            "details": forms.Textarea(attrs={"rows": 3, "placeholder": "Additional details (optional)"}),
        }


# =============================================================================
# SEARCH / FILTER FORMS
# =============================================================================

class JobSearchForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(attrs={"placeholder": "Job title, keywords, company"})
    )
    location = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "City, country"})
    )
    employment_type = forms.MultipleChoiceField(
        required=False,
        choices=m.Job.EmploymentType.choices,
        widget=forms.CheckboxSelectMultiple
    )
    experience_level = forms.MultipleChoiceField(
        required=False,
        choices=m.Job.ExperienceLevel.choices,
        widget=forms.CheckboxSelectMultiple
    )
    remote_status = forms.MultipleChoiceField(
        required=False,
        choices=m.Job.RemoteStatus.choices,
        widget=forms.CheckboxSelectMultiple
    )
    salary_min = forms.IntegerField(required=False, min_value=0, label="Minimum salary")
    salary_max = forms.IntegerField(required=False, min_value=0, label="Maximum salary")
    sort_by = forms.ChoiceField(
        required=False,
        choices=[
            ("newest", "Newest"),
            ("oldest", "Oldest"),
            ("salary_high", "Highest Salary"),
            ("salary_low", "Lowest Salary"),
        ],
        widget=forms.Select
    )


class UserSearchForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(attrs={"placeholder": "Name, headline, skills"})
    )
    location = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "City, country"})
    )
    role = forms.ChoiceField(
        required=False,
        choices=[("", "All")] + list(m.CustomUser.Role.choices)
    )
    skills = forms.CharField(
        required=False,
        help_text="Comma‑separated skill names"
    )
    open_to_work = forms.BooleanField(required=False)


# =============================================================================
# ADMIN FORMS
# =============================================================================

class AdminCompanyVerificationReviewForm(forms.ModelForm):
    class Meta:
        model = m.CompanyVerification
        fields = ("status", "notes", "reviewed_by", "reviewed_at")
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        readonly_fields = ("reviewed_by", "reviewed_at")

    def clean_status(self):
        status = self.cleaned_data["status"]
        if status == m.CompanyVerification.Status.VERIFIED:
            # Additional checks could be added
            pass
        return status