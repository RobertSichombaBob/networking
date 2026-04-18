from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
import os

User = get_user_model()

class Command(BaseCommand):
    help = 'Creates a superuser if none exists, using environment variables'

    def handle(self, *args, **options):
        email = os.environ.get('ADMIN_EMAIL')
        password = os.environ.get('ADMIN_PASSWORD')
        if not email or not password:
            self.stdout.write(self.style.WARNING('ADMIN_EMAIL or ADMIN_PASSWORD not set, skipping'))
            return
        if not User.objects.filter(email=email).exists():
            User.objects.create_superuser(email=email, password=password, role='admin')
            self.stdout.write(self.style.SUCCESS(f'✅ Superuser {email} created.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'ℹ️ Superuser {email} already exists.'))