
# portfolio/urls.py
from django.urls import path
from . import views

app_name = "portfolio"

urlpatterns = [
    # Home & static pages
    path("", views.HomeView.as_view(), name="home"),
    path("about/", views.AboutView.as_view(), name="about"),
    path("contact/", views.ContactView.as_view(), name="contact"),

    # Authentication (if you use custom views; otherwise use django.contrib.auth.urls)
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("signup/", views.SignUpView.as_view(), name="signup"),
    path("password-reset/", views.PasswordResetView.as_view(), name="password_reset"),
    # ... (add other auth paths as needed)

    # Profile
    path("profile/", views.ProfileView.as_view(), name="my_profile"),
    path("profile/edit/", views.EditProfileView.as_view(), name="edit_profile"),
    path("profile/<uuid:pk>/", views.PublicProfileView.as_view(), name="public_profile"),

    # Employer profile (if applicable)
    path("employer/profile/edit/", views.EditEmployerProfileView.as_view(), name="edit_employer_profile"),

    # Companies
    path("companies/", views.CompanyListView.as_view(), name="company_list"),
    path("companies/create/", views.CreateCompanyView.as_view(), name="create_company"),
    path("companies/<slug:slug>/", views.CompanyDetailView.as_view(), name="company_detail"),
    path("companies/<slug:slug>/edit/", views.EditCompanyView.as_view(), name="edit_company"),
    path("companies/<slug:slug>/verify/", views.CompanyVerificationView.as_view(), name="verify_company"),

    # Experience & Education
    path("profile/experience/add/", views.AddExperienceView.as_view(), name="add_experience"),
    path("profile/experience/<uuid:pk>/edit/", views.EditExperienceView.as_view(), name="edit_experience"),
    path("profile/experience/<uuid:pk>/delete/", views.DeleteExperienceView.as_view(), name="delete_experience"),
    path("profile/education/add/", views.AddEducationView.as_view(), name="add_education"),
    path("profile/education/<uuid:pk>/edit/", views.EditEducationView.as_view(), name="edit_education"),
    path("profile/education/<uuid:pk>/delete/", views.DeleteEducationView.as_view(), name="delete_education"),

    # Skills
    path("profile/skills/", views.ManageSkillsView.as_view(), name="manage_skills"),
    path("skills/<uuid:pk>/endorse/", views.EndorseSkillView.as_view(), name="endorse_skill"),
    path("skills/search/", views.SkillSearchAPIView.as_view(), name="skill_search_api"),

    # Jobs
    path("jobs/", views.JobListView.as_view(), name="job_list"),
    path("jobs/search/", views.JobSearchView.as_view(), name="job_search"),
    path("jobs/post/", views.PostJobView.as_view(), name="post_job"),
    path("jobs/<slug:slug>/", views.JobDetailView.as_view(), name="job_detail"),
    path("jobs/<slug:slug>/edit/", views.EditJobView.as_view(), name="edit_job"),
    path("jobs/<slug:slug>/delete/", views.DeleteJobView.as_view(), name="delete_job"),
    path("jobs/<slug:slug>/apply/", views.ApplyJobView.as_view(), name="apply_job"),
    path("jobs/<slug:slug>/save/", views.SaveJobView.as_view(), name="save_job"),
    path("jobs/<slug:slug>/unsave/", views.UnsaveJobView.as_view(), name="unsave_job"),

    # Saved Jobs
    path("saved-jobs/", views.SavedJobsView.as_view(), name="saved_jobs"),

    # Applications
    path("applications/", views.MyApplicationsView.as_view(), name="my_applications"),
    path("applications/<uuid:pk>/", views.ApplicationDetailView.as_view(), name="application_detail"),
    path("applications/<uuid:pk>/withdraw/", views.WithdrawApplicationView.as_view(), name="withdraw_application"),
    path("jobs/<slug:slug>/applications/", views.JobApplicationsView.as_view(), name="job_applications"),
    path("applications/<uuid:pk>/update-status/", views.UpdateApplicationStatusView.as_view(), name="update_application_status"),

    # Job Alerts
    path("alerts/", views.JobAlertListView.as_view(), name="job_alerts"),
    path("alerts/create/", views.CreateJobAlertView.as_view(), name="create_job_alert"),
    path("alerts/<uuid:pk>/edit/", views.EditJobAlertView.as_view(), name="edit_job_alert"),
    path("alerts/<uuid:pk>/delete/", views.DeleteJobAlertView.as_view(), name="delete_job_alert"),
    path("alerts/<uuid:pk>/toggle/", views.ToggleJobAlertView.as_view(), name="toggle_job_alert"),

    # Social Feed
    path("feed/", views.FeedView.as_view(), name="feed"),
    path("posts/create/", views.CreatePostView.as_view(), name="create_post"),
    path("posts/<uuid:pk>/", views.PostDetailView.as_view(), name="post_detail"),
    path("posts/<uuid:pk>/edit/", views.EditPostView.as_view(), name="edit_post"),
    path("posts/<uuid:pk>/delete/", views.DeletePostView.as_view(), name="delete_post"),
    path("posts/<uuid:pk>/like/", views.LikePostView.as_view(), name="like_post"),
    path("posts/<uuid:pk>/unlike/", views.UnlikePostView.as_view(), name="unlike_post"),
    path("posts/<uuid:pk>/comment/", views.AddCommentView.as_view(), name="add_comment"),
    path("comments/<uuid:pk>/delete/", views.DeleteCommentView.as_view(), name="delete_comment"),

    # Network
    path("network/", views.NetworkView.as_view(), name="network"),
    path("network/connections/", views.ConnectionListView.as_view(), name="connections"),
    path("network/followers/", views.FollowerListView.as_view(), name="followers"),
    path("network/following/", views.FollowingListView.as_view(), name="following"),
    path("network/connect/<uuid:user_id>/", views.SendConnectionRequestView.as_view(), name="send_connection_request"),
    path("network/requests/", views.ConnectionRequestsView.as_view(), name="connection_requests"),
    path("network/requests/<uuid:pk>/accept/", views.AcceptConnectionView.as_view(), name="accept_connection"),
    path("network/requests/<uuid:pk>/decline/", views.DeclineConnectionView.as_view(), name="decline_connection"),
    path("network/follow/<uuid:user_id>/", views.FollowUserView.as_view(), name="follow_user"),
    path("network/unfollow/<uuid:user_id>/", views.UnfollowUserView.as_view(), name="unfollow_user"),

    # Recommendations
    path("recommendations/write/<uuid:user_id>/", views.WriteRecommendationView.as_view(), name="write_recommendation"),

    # Messaging
    path("messages/", views.ConversationListView.as_view(), name="conversations"),
    path("messages/new/<uuid:user_id>/", views.NewConversationView.as_view(), name="new_conversation"),
    path("messages/<uuid:pk>/", views.ConversationDetailView.as_view(), name="conversation_detail"),
    path("messages/<uuid:pk>/send/", views.SendMessageView.as_view(), name="send_message"),

    # Notifications
    path("notifications/", views.NotificationListView.as_view(), name="notifications"),
    path("notifications/<uuid:pk>/read/", views.MarkNotificationReadView.as_view(), name="mark_notification_read"),
    path("notifications/read-all/", views.MarkAllNotificationsReadView.as_view(), name="mark_all_read"),

    # Search
    path("search/", views.GlobalSearchView.as_view(), name="global_search"),
    path("search/users/", views.UserSearchView.as_view(), name="user_search"),

    # Reports (moderation)
    path("reports/", views.ReportListView.as_view(), name="reports"),
    path("reports/create/<int:content_type_id>/<str:object_id>/", views.CreateReportView.as_view(), name="create_report"),
    path("reports/<uuid:pk>/resolve/", views.ResolveReportView.as_view(), name="resolve_report"),
    
    
    path('api/skill-id/', views.skill_id_by_name, name='skill_id_by_name'),
    
    
    path('autocomplete/skill/', views.SkillAutocomplete.as_view(), name='skill_autocomplete'),
    
    path('autocomplete/company/', views.CompanyAutocomplete.as_view(), name='company_autocomplete'),

    path('privacy/', views.PrivacyView.as_view(), name='privacy'),
    path('terms/', views.TermsView.as_view(), name='terms'),





path('api/like/<uuid:post_id>/', views.htmx_like_post, name='htmx_like_post'),
    path('api/save/<slug:job_slug>/', views.htmx_save_job, name='htmx_save_job'),
    path('api/apply/<slug:job_slug>/', views.htmx_apply_job, name='htmx_apply_job'),




path('admin/dashboard/', views.AdminDashboardView.as_view(), name='admin_dashboard'),




path('companies/<slug:slug>/delete/', views.DeleteCompanyView.as_view(), name='delete_company'),








]