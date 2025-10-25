"""
Qatari Commercial Law Compliance Analyzer

This analyzer checks contracts against the Qatari Commercial Law requirements
and identifies potential compliance issues or missing provisions.
"""

import logging
from typing import Any, Dict, List, Tuple

from opencontractserver.analyzer.decorators import doc_analyzer_task
from opencontractserver.types.dicts import TextSpan
from opencontractserver.documents.models import Document
from opencontractserver.llms.tools.core_tools import load_document_txt_extract

logger = logging.getLogger(__name__)


@doc_analyzer_task()
def qatari_commercial_law_compliance_check(
    doc_id: str,
    analysis_id: str,
    corpus_id: str = None,
    pdf_text_extract: str | None = None,
    pdf_pawls_extract: dict | None = None,
    **kwargs: Any,
) -> Tuple[List[str], List[Tuple[TextSpan, str]], List[Dict], bool]:
    """
    Analyze a contract for compliance with Qatari Commercial Law.
    
    This analyzer:
    1. Extracts key contract provisions
    2. Checks against Qatari Commercial Law requirements
    3. Identifies missing or non-compliant clauses
    4. Highlights areas of concern
    
    Returns:
        - doc_annotations: Document-level compliance labels
        - span_annotations: Specific text spans with compliance notes
        - metadata: Detailed compliance analysis results
        - success: Whether analysis completed successfully
    """
    
    try:
        logger.info(f"Starting Qatari Commercial Law compliance analysis for document {doc_id}")
        
        # Get document text
        if pdf_text_extract:
            document_text = pdf_text_extract
        else:
            document_text = load_document_txt_extract(int(doc_id))
        
        if not document_text:
            logger.error(f"No text content found for document {doc_id}")
            return [], [], [{"data": {"error": "No document text available"}}], False
        
        # Key Qatari Commercial Law requirements to check
        compliance_checks = {
            "company_formation": {
                "keywords": ["incorporation", "formation", "establishment", "company", "LLC", "WLL"],
                "requirements": [
                    "Minimum capital requirements",
                    "Shareholder information",
                    "Board composition",
                    "Registered office address"
                ]
            },
            "commercial_registration": {
                "keywords": ["commercial registration", "trade license", "business license"],
                "requirements": [
                    "Valid commercial registration",
                    "Trade license compliance",
                    "Business activity scope"
                ]
            },
            "corporate_governance": {
                "keywords": ["board", "directors", "shareholders", "governance", "meetings"],
                "requirements": [
                    "Board meeting requirements",
                    "Shareholder rights",
                    "Decision-making procedures",
                    "Audit requirements"
                ]
            },
            "financial_obligations": {
                "keywords": ["capital", "financial", "accounting", "audit", "records"],
                "requirements": [
                    "Minimum capital maintenance",
                    "Financial record keeping",
                    "Annual audit requirements",
                    "Financial reporting"
                ]
            },
            "dissolution_liquidation": {
                "keywords": ["dissolution", "liquidation", "winding up", "termination"],
                "requirements": [
                    "Dissolution procedures",
                    "Liquidation process",
                    "Creditor protection",
                    "Asset distribution"
                ]
            }
        }
        
        # Analyze document for compliance
        doc_annotations = []
        span_annotations = []
        compliance_results = {}
        
        document_lower = document_text.lower()
        
        for category, check_data in compliance_checks.items():
            category_found = False
            category_issues = []
            
            # Check if category is relevant to this document
            for keyword in check_data["keywords"]:
                if keyword.lower() in document_lower:
                    category_found = True
                    break
            
            if category_found:
                # Find specific mentions and analyze compliance
                for requirement in check_data["requirements"]:
                    requirement_keywords = requirement.lower().split()
                    requirement_found = any(
                        keyword in document_lower for keyword in requirement_keywords
                    )
                    
                    if not requirement_found:
                        category_issues.append(f"Missing: {requirement}")
                
                # Add document-level annotation if issues found
                if category_issues:
                    doc_annotations.append(f"QATARI_LAW_ISSUE_{category.upper()}")
                else:
                    doc_annotations.append(f"QATARI_LAW_COMPLIANT_{category.upper()}")
                
                compliance_results[category] = {
                    "relevant": True,
                    "issues": category_issues,
                    "compliant": len(category_issues) == 0
                }
            else:
                compliance_results[category] = {
                    "relevant": False,
                    "issues": [],
                    "compliant": True  # Not applicable
                }
        
        # Find specific text spans that need attention
        issue_keywords = [
            "shall comply", "must comply", "required by law", "legal requirement",
            "commercial law", "qatar", "qatari law", "regulation", "compliance"
        ]
        
        for keyword in issue_keywords:
            start_pos = 0
            while True:
                pos = document_text.lower().find(keyword, start_pos)
                if pos == -1:
                    break
                
                # Create text span for this keyword
                span = TextSpan(
                    start=pos,
                    end=pos + len(keyword),
                    text=document_text[pos:pos + len(keyword)]
                )
                span_annotations.append((span, "LEGAL_COMPLIANCE_REFERENCE"))
                start_pos = pos + 1
        
        # Calculate overall compliance score
        total_categories = len([c for c in compliance_results.values() if c["relevant"]])
        compliant_categories = len([c for c in compliance_results.values() if c["compliant"] and c["relevant"]])
        
        compliance_score = (compliant_categories / total_categories * 100) if total_categories > 0 else 100
        
        # Prepare metadata
        metadata = [{
            "data": {
                "compliance_score": compliance_score,
                "total_categories_checked": total_categories,
                "compliant_categories": compliant_categories,
                "detailed_results": compliance_results,
                "overall_status": "COMPLIANT" if compliance_score >= 80 else "NON_COMPLIANT",
                "recommendations": generate_recommendations(compliance_results)
            }
        }]
        
        logger.info(f"Completed compliance analysis for document {doc_id}. Score: {compliance_score}%")
        
        return doc_annotations, span_annotations, metadata, True
        
    except Exception as e:
        logger.error(f"Error in Qatari Commercial Law compliance analysis: {str(e)}")
        return [], [], [{"data": {"error": str(e)}}], False


def generate_recommendations(compliance_results: Dict) -> List[str]:
    """Generate specific recommendations based on compliance analysis."""
    recommendations = []
    
    for category, results in compliance_results.items():
        if results["relevant"] and not results["compliant"]:
            category_name = category.replace("_", " ").title()
            recommendations.append(
                f"Review {category_name} provisions and ensure compliance with Qatari Commercial Law requirements"
            )
            
            for issue in results["issues"]:
                recommendations.append(f"- Address: {issue}")
    
    if not recommendations:
        recommendations.append("Document appears to be compliant with checked Qatari Commercial Law requirements")
    
    return recommendations
