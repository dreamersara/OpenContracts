"""
Management command to set up Qatari Commercial Law compliance checking system.

This command helps users quickly set up:
1. A dedicated corpus for legal compliance
2. Upload the Qatari Commercial Law reference document
3. Configure automatic compliance checking for new contracts
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.core.files import File
import os

from opencontractserver.corpuses.models import Corpus, CorpusAction
from opencontractserver.documents.models import Document
from opencontractserver.analyzer.models import Analyzer


class Command(BaseCommand):
    help = 'Set up Qatari Commercial Law compliance checking system'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--law-pdf-path',
            type=str,
            help='Path to the Qatari Commercial Law PDF file',
            default='pdf/Law-No--11-of-2015---Promulgating-the-Commercial-Companies-Law---English.pdf'
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='User ID to own the corpus (defaults to first superuser)',
        )
        parser.add_argument(
            '--corpus-name',
            type=str,
            default='Qatari Commercial Law Compliance',
            help='Name for the compliance corpus'
        )
    
    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Setting up Qatari Commercial Law compliance system...')
        )
        
        # Get user
        User = get_user_model()
        if options['user_id']:
            try:
                user = User.objects.get(id=options['user_id'])
            except User.DoesNotExist:
                raise CommandError(f"User with ID {options['user_id']} not found")
        else:
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                raise CommandError("No superuser found. Please create one first or specify --user-id")
        
        self.stdout.write(f"Using user: {user.username}")
        
        # Create or get corpus
        corpus, created = Corpus.objects.get_or_create(
            title=options['corpus_name'],
            defaults={
                'description': 'Corpus for checking contract compliance against Qatari Commercial Law No. 11 of 2015',
                'creator': user,
                'is_public': False,  # Keep private for legal documents
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'Created corpus: {corpus.title}')
            )
        else:
            self.stdout.write(f'Using existing corpus: {corpus.title}')
        
        # Upload Qatari Commercial Law document if provided
        law_pdf_path = options['law_pdf_path']
        if law_pdf_path and os.path.exists(law_pdf_path):
            # Check if law document already exists
            law_doc = Document.objects.filter(
                title__icontains='Qatari Commercial Law',
                creator=user
            ).first()
            
            if not law_doc:
                with open(law_pdf_path, 'rb') as pdf_file:
                    law_doc = Document.objects.create(
                        title='Qatari Commercial Law No. 11 of 2015',
                        description='Reference document: Commercial Companies Law of Qatar',
                        creator=user,
                        pdf_file=File(pdf_file, name=os.path.basename(law_pdf_path))
                    )
                
                # Add to corpus
                corpus.documents.add(law_doc)
                
                self.stdout.write(
                    self.style.SUCCESS(f'Uploaded law document: {law_doc.title}')
                )
            else:
                self.stdout.write(f'Law document already exists: {law_doc.title}')
        else:
            self.stdout.write(
                self.style.WARNING(f'Law PDF not found at: {law_pdf_path}')
            )
        
        # Get or create the analyzer
        try:
            analyzer = Analyzer.objects.get(id="qatari-commercial-law-compliance")
            self.stdout.write(f'Found analyzer: {analyzer.description}')
        except Analyzer.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(
                    'Qatari Commercial Law analyzer not found. '
                    'Please run migrations first: python manage.py migrate'
                )
            )
            return
        
        # Create corpus action for automatic analysis
        corpus_action, created = CorpusAction.objects.get_or_create(
            corpus=corpus,
            analyzer=analyzer,
            defaults={
                'trigger': CorpusAction.TriggerChoices.DOCUMENT_ADDED,
                'creator': user,
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS('Set up automatic compliance checking for new documents')
            )
        else:
            self.stdout.write('Automatic compliance checking already configured')
        
        # Print summary
        self.stdout.write('\n' + '='*50)
        self.stdout.write(self.style.SUCCESS('SETUP COMPLETE!'))
        self.stdout.write('='*50)
        self.stdout.write(f'Corpus: {corpus.title} (ID: {corpus.id})')
        self.stdout.write(f'Analyzer: {analyzer.description}')
        self.stdout.write(f'Documents in corpus: {corpus.documents.count()}')
        self.stdout.write('\nNext steps:')
        self.stdout.write('1. Upload contracts to the corpus')
        self.stdout.write('2. They will be automatically analyzed for Qatari law compliance')
        self.stdout.write('3. View results in the OpenContracts web interface')
        self.stdout.write('\nTo upload a contract:')
        self.stdout.write(f'   - Go to Corpus "{corpus.title}" in the web interface')
        self.stdout.write('   - Upload your contract PDF')
        self.stdout.write('   - Compliance analysis will run automatically')
