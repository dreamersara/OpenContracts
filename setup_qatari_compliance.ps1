# Qatari Commercial Law Compliance Setup Script for Windows
# This script sets up automated contract compliance checking against Qatari Commercial Law

Write-Host "🏛️  Setting up Qatari Commercial Law Compliance Checker..." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green

# Check if we're in the right directory
if (-not (Test-Path "manage.py")) {
    Write-Host "❌ Error: Please run this script from the OpenContracts root directory" -ForegroundColor Red
    Write-Host "Current directory: $(Get-Location)" -ForegroundColor Yellow
    Write-Host "Please navigate to your OpenContracts folder first" -ForegroundColor Yellow
    exit 1
}

# Check if the law PDF exists
$LAW_PDF = "pdf\Law-No--11-of-2015---Promulgating-the-Commercial-Companies-Law---English.pdf"
if (-not (Test-Path $LAW_PDF)) {
    Write-Host "⚠️  Warning: Qatari Commercial Law PDF not found at $LAW_PDF" -ForegroundColor Yellow
    Write-Host "   You can still set up the system and upload the PDF later" -ForegroundColor Yellow
}

Write-Host "📋 Step 1: Running database migrations..." -ForegroundColor Cyan
python manage.py migrate

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Migration failed. Please check your database connection." -ForegroundColor Red
    Write-Host "Make sure OpenContracts is properly set up and database is running" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Migrations completed" -ForegroundColor Green

Write-Host "🔧 Step 2: Setting up compliance system..." -ForegroundColor Cyan
python manage.py setup_qatari_law_compliance

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Setup failed. Please check the error messages above." -ForegroundColor Red
    exit 1
}

Write-Host "✅ Setup completed successfully!" -ForegroundColor Green

Write-Host ""
Write-Host "🎉 QATARI COMMERCIAL LAW COMPLIANCE CHECKER IS READY!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""
Write-Host "📖 What's been set up:" -ForegroundColor Cyan
Write-Host "   ✓ Compliance analyzer registered" -ForegroundColor Green
Write-Host "   ✓ Dedicated corpus created" -ForegroundColor Green
Write-Host "   ✓ Automatic analysis configured" -ForegroundColor Green
Write-Host "   ✓ Reference law document uploaded (if PDF was found)" -ForegroundColor Green
Write-Host ""
Write-Host "🚀 Next steps:" -ForegroundColor Cyan
Write-Host "   1. Start OpenContracts: docker-compose up (or your preferred method)" -ForegroundColor White
Write-Host "   2. Open the web interface in your browser" -ForegroundColor White
Write-Host "   3. Navigate to 'Qatari Commercial Law Compliance' corpus" -ForegroundColor White
Write-Host "   4. Upload a contract PDF" -ForegroundColor White
Write-Host "   5. View automatic compliance analysis results!" -ForegroundColor White
Write-Host ""
Write-Host "📚 For detailed usage instructions, see:" -ForegroundColor Cyan
Write-Host "   docs\qatari_law_compliance_guide.md" -ForegroundColor White
Write-Host ""
Write-Host "⚖️  Legal Note: This tool provides automated analysis for informational" -ForegroundColor Yellow
Write-Host "   purposes only and does not constitute legal advice." -ForegroundColor Yellow

Write-Host ""
Write-Host "Press any key to continue..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
