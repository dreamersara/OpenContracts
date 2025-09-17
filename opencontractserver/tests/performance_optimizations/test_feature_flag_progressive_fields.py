"""
Feature flag toggle test for progressive GraphQL fields availability.
"""

from __future__ import annotations

from django.test import override_settings

from config.graphql.schema import schema


@override_settings(FEATURES={"PROGRESSIVE_ANNOTATION_LOADING": True})
def test_progressive_fields_present_when_enabled():
    sdl = str(schema)
    assert "annotationSummary(" in sdl
    assert "annotationNavigation(" in sdl
    assert "pageAnnotations(" in sdl


@override_settings(FEATURES={"PROGRESSIVE_ANNOTATION_LOADING": False})
def test_progressive_fields_absent_when_disabled():
    sdl = str(schema)
    # If toggled off, these should be absent (or the resolvers should be no-ops)
    # Adjust based on actual conditional wiring; here we assert absence
    assert "annotationSummary(" not in sdl
    assert "annotationNavigation(" not in sdl
    assert "pageAnnotations(" not in sdl
