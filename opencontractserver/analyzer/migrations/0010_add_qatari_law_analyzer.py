"""
Migration to add Qatari Commercial Law Compliance Analyzer
"""

from django.db import migrations
from django.contrib.auth import get_user_model

def create_qatari_law_analyzer(apps, schema_editor):
    """Create the Qatari Commercial Law compliance analyzer."""
    Analyzer = apps.get_model('analyzer', 'Analyzer')
    User = get_user_model()
    
    # Get or create a superuser to own the analyzer
    try:
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            user = User.objects.create_superuser(
                username='system',
                email='system@opencontracts.local',
                password='system'
            )
    except Exception:
        # If user creation fails, we'll skip this migration
        return
    
    # Create the analyzer
    analyzer, created = Analyzer.objects.get_or_create(
        id="qatari-commercial-law-compliance",
        defaults={
            'description': 'Analyzes contracts for compliance with Qatari Commercial Law No. 11 of 2015. '
                          'Checks for required provisions, corporate governance requirements, '
                          'financial obligations, and other legal compliance matters.',
            'task_name': 'opencontractserver.tasks.qatari_law_compliance_analyzer.qatari_commercial_law_compliance_check',
            'creator': user,
            'manifest': {
                'name': 'Qatari Commercial Law Compliance Checker',
                'version': '1.0.0',
                'description': 'Automated compliance checking against Qatari Commercial Law',
                'categories': ['Legal', 'Compliance', 'Commercial Law'],
                'supported_formats': ['PDF', 'TXT'],
                'output_types': ['compliance_score', 'recommendations', 'issues']
            },
            'is_public': True,
            'disabled': False
        }
    )
    
    if created:
        print(f"Created Qatari Commercial Law Compliance Analyzer: {analyzer.id}")
    else:
        print(f"Qatari Commercial Law Compliance Analyzer already exists: {analyzer.id}")


def remove_qatari_law_analyzer(apps, schema_editor):
    """Remove the Qatari Commercial Law compliance analyzer."""
    Analyzer = apps.get_model('analyzer', 'Analyzer')
    
    try:
        analyzer = Analyzer.objects.get(id="qatari-commercial-law-compliance")
        analyzer.delete()
        print("Removed Qatari Commercial Law Compliance Analyzer")
    except Analyzer.DoesNotExist:
        print("Qatari Commercial Law Compliance Analyzer not found")


class Migration(migrations.Migration):
    
    dependencies = [
        ('analyzer', '0009_auto_load_doc_analyzers'),
    ]
    
    operations = [
        migrations.RunPython(
            create_qatari_law_analyzer,
            remove_qatari_law_analyzer
        ),
    ]
