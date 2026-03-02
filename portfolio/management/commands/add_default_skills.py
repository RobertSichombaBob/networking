from django.core.management.base import BaseCommand
from portfolio.models import Skill

DEFAULT_SKILLS = [
    "Python",
    "JavaScript",
    "Java",
    "SQL",
    "Excel",
    "Data Analysis",
    "Machine Learning",
    "Project Management",
    "Communication",
    "Leadership",
    "HTML",
    "CSS",
    "React",
    "Django",
    "Flask",
    "C++",
    "C#",
    "PHP",
    "Ruby",
    "Swift",
    "Kotlin",
    "Go",
    "Rust",
    "TypeScript",
    "Node.js",
    "Angular",
    "Vue.js",
    "MongoDB",
    "PostgreSQL",
    "MySQL",
    "AWS",
    "Azure",
    "Docker",
    "Kubernetes",
    "Git",
    "Agile",
    "Scrum",
    "Product Management",
    "UI/UX Design",
    "Graphic Design",
    "Content Writing",
    "Digital Marketing",
    "SEO",
    "Sales",
    "Customer Service",
]

class Command(BaseCommand):
    help = "Add default skills to the database"

    def handle(self, *args, **options):
        created_count = 0
        for skill_name in DEFAULT_SKILLS:
            skill, created = Skill.objects.get_or_create(
                name=skill_name,
                defaults={"is_active": True, "category": "General"}
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Added skill: {skill_name}"))
            else:
                self.stdout.write(f"Skill already exists: {skill_name}")
        self.stdout.write(self.style.SUCCESS(f"Done. {created_count} new skills added."))