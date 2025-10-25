#!/bin/bash

# Qatari Commercial Law Compliance Setup Script
# This script sets up automated contract compliance checking against Qatari Commercial Law

echo "🏛️  Setting up Qatari Commercial Law Compliance Checker..."
echo "=================================================="

# Check if we're in the right directory
if [ ! -f "manage.py" ]; then
    echo "❌ Error: Please run this script from the OpenContracts root directory"
    exit 1
fi

# Check if the law PDF exists
LAW_PDF="pdf/Law-No--11-of-2015---Promulgating-the-Commercial-Companies-Law---English.pdf"
if [ ! -f "$LAW_PDF" ]; then
    echo "⚠️  Warning: Qatari Commercial Law PDF not found at $LAW_PDF"
    echo "   You can still set up the system and upload the PDF later"
fi

echo "📋 Step 1: Running database migrations..."
python manage.py migrate

if [ $? -ne 0 ]; then
    echo "❌ Migration failed. Please check your database connection."
    exit 1
fi

echo "✅ Migrations completed"

echo "🔧 Step 2: Setting up compliance system..."
python manage.py setup_qatari_law_compliance

if [ $? -ne 0 ]; then
    echo "❌ Setup failed. Please check the error messages above."
    exit 1
fi

echo "✅ Setup completed successfully!"

echo ""
echo "🎉 QATARI COMMERCIAL LAW COMPLIANCE CHECKER IS READY!"
echo "=================================================="
echo ""
echo "📖 What's been set up:"
echo "   ✓ Compliance analyzer registered"
echo "   ✓ Dedicated corpus created"
echo "   ✓ Automatic analysis configured"
echo "   ✓ Reference law document uploaded (if PDF was found)"
echo ""
echo "🚀 Next steps:"
echo "   1. Start OpenContracts: docker-compose up (or your preferred method)"
echo "   2. Open the web interface in your browser"
echo "   3. Navigate to 'Qatari Commercial Law Compliance' corpus"
echo "   4. Upload a contract PDF"
echo "   5. View automatic compliance analysis results!"
echo ""
echo "📚 For detailed usage instructions, see:"
echo "   docs/qatari_law_compliance_guide.md"
echo ""
echo "⚖️  Legal Note: This tool provides automated analysis for informational"
echo "   purposes only and does not constitute legal advice."
