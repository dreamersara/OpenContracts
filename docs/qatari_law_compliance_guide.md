# Qatari Commercial Law Compliance Checker

## Overview

This guide shows you how to use OpenContracts to automatically check contracts for compliance with **Qatari Commercial Law No. 11 of 2015**. The system provides:

- ✅ **Automated compliance scoring**
- 🔍 **Detailed analysis of legal requirements**
- 📋 **Specific recommendations for improvement**
- 🚨 **Highlighting of potential compliance issues**

## Quick Setup (5 minutes)

### 1. Run the Setup Command

```bash
# Navigate to your OpenContracts directory
cd /path/to/OpenContracts

# Run the setup command
python manage.py setup_qatari_law_compliance
```

This automatically:
- Creates a "Qatari Commercial Law Compliance" corpus
- Uploads the Qatari law PDF as reference
- Sets up automatic compliance checking
- Configures the analyzer

### 2. Start Using the System

1. **Open OpenContracts** in your web browser
2. **Navigate to the "Qatari Commercial Law Compliance" corpus**
3. **Upload any contract** (PDF format)
4. **Wait for automatic analysis** (usually 1-2 minutes)
5. **View compliance results** in the document viewer

## What Gets Checked

The analyzer examines contracts for compliance with these key areas:

### 🏢 Company Formation
- Minimum capital requirements
- Shareholder information
- Board composition
- Registered office address

### 📋 Commercial Registration
- Valid commercial registration
- Trade license compliance
- Business activity scope

### 🏛️ Corporate Governance
- Board meeting requirements
- Shareholder rights
- Decision-making procedures
- Audit requirements

### 💰 Financial Obligations
- Minimum capital maintenance
- Financial record keeping
- Annual audit requirements
- Financial reporting

### 🔚 Dissolution & Liquidation
- Dissolution procedures
- Liquidation process
- Creditor protection
- Asset distribution

## Understanding Results

### Compliance Score
- **80-100%**: ✅ Compliant - Contract meets most requirements
- **60-79%**: ⚠️ Partially Compliant - Some issues need attention
- **0-59%**: ❌ Non-Compliant - Significant compliance gaps

### Document Annotations
Look for these labels on your documents:
- `QATARI_LAW_COMPLIANT_[CATEGORY]` - Area is compliant
- `QATARI_LAW_ISSUE_[CATEGORY]` - Area has compliance issues
- `LEGAL_COMPLIANCE_REFERENCE` - Text mentioning legal requirements

### Detailed Results
Click on the analysis results to see:
- **Specific missing provisions**
- **Recommendations for improvement**
- **Category-by-category breakdown**
- **Overall compliance status**

## Example Workflow

### For Contract Review:
1. **Upload contract** to the compliance corpus
2. **Review compliance score** (appears in analysis results)
3. **Check highlighted issues** in the document viewer
4. **Follow recommendations** to improve compliance
5. **Re-upload revised contract** to verify improvements

### For Contract Lifecycle Management:
1. **Create separate folders** for different contract types
2. **Set up automated workflows** using CorpusActions
3. **Monitor compliance trends** across your contract portfolio
4. **Generate compliance reports** using the data extraction features

## Advanced Features

### Custom Compliance Rules
You can modify the analyzer to check for additional requirements:

```python
# Edit: opencontractserver/tasks/qatari_law_compliance_analyzer.py
# Add new compliance categories or modify existing ones
```

### Bulk Analysis
To analyze multiple contracts at once:

1. Upload all contracts to the corpus
2. Use the **Bulk Data Extract** feature
3. Create a custom fieldset asking: "What is the compliance score?"
4. Run extraction across all documents

### Integration with Contract Management
- **API Access**: Use OpenContracts' GraphQL API for integration
- **Webhooks**: Set up notifications for compliance issues
- **Reporting**: Export compliance data to spreadsheets

## Troubleshooting

### Analyzer Not Running
```bash
# Check if analyzer is registered
python manage.py shell
>>> from opencontractserver.analyzer.models import Analyzer
>>> Analyzer.objects.filter(id="qatari-commercial-law-compliance")
```

### Low Compliance Scores
- Ensure contract text is clear and readable
- Check if document was parsed correctly
- Verify contract contains relevant commercial law provisions

### Missing Analysis Results
- Wait for Celery workers to complete processing
- Check Django admin for analysis status
- Verify document was successfully uploaded

## Support

For questions or issues:
1. Check the OpenContracts documentation
2. Review the analyzer code in `opencontractserver/tasks/qatari_law_compliance_analyzer.py`
3. Create an issue on the OpenContracts GitHub repository

## Legal Disclaimer

This tool provides automated analysis for informational purposes only. It does not constitute legal advice. Always consult with qualified legal professionals for definitive compliance guidance.
