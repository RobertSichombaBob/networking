# myportfolio/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Django admin
    path('admin/', admin.site.urls),

    # All portfolio app URLs (home, jobs, profiles, messaging, etc.)
    path('', include('portfolio.urls')),  # app name is 'portfolio'
]

# Serve media and static files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Custom error pages (optional – define views in portfolio/views.py)
handler404 = 'portfolio.views.custom_404'
handler500 = 'portfolio.views.custom_500'