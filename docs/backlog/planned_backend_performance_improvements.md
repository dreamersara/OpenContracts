# Planned Backend Performance Improvements

**Purpose**: Track performance optimizations needed, focusing on the critical path to enable progressive annotation loading.

## Current State Assessment

### ✅ What's Already Working
- **Backend Query Optimizer**: `AnnotationQueryOptimizer.get_document_annotations()` supports page filtering
- **GraphQL Page Resolver**: `DocumentType.pageAnnotations` field exists and works for single pages
- **Database Indexes**: Optimized for page-scoped queries (migration 0036)
- **Materialized Views**: Summary and navigation MVs created (migration 0037)
- **Caching Layer**: Per-user caching with 5-minute TTL
- **Permission Filtering**: Integrated at all levels

### ❌ Critical Gaps
- **Frontend loads ALL annotations**: Uses `allAnnotations` instead of `pageAnnotations`
- **No viewport detection**: Frontend doesn't track visible PDF pages
- **Single page only**: `pageAnnotations` doesn't accept multiple pages
- **No prefetch buffer**: Pages loaded on-demand cause scrolling lag

## High Priority: Frontend Migration to Page-Based Loading

### 1. Stop Loading All Annotations (CRITICAL)
**Problem**: `GET_DOCUMENT_KNOWLEDGE_AND_ANNOTATIONS` query uses `allAnnotations`, loading 10,000+ annotations when only ~100 are visible on screen.

**Implementation**:
- **Frontend** (`DocumentKnowledgeBase.tsx`):
  - Remove `allAnnotations` from GraphQL query
  - Add viewport detection to track visible PDF pages
  - Load annotations per page using existing `pageAnnotations` field
- **Metrics**: Track migration with logging in both old and new resolvers

### 2. Add Multi-Page Support to Backend
**Problem**: Loading pages 1, 2, 3 requires 3 separate GraphQL queries.

**Implementation**:
- **Query Optimizer** (`query_optimizer.py`): Add `pages: List[int]` parameter, use `filter(page__in=pages)`
- **GraphQL** (`graphene_types.py`): Update `pageAnnotations` to accept `pages: [Int]` array
- **Benefit**: Load viewport + buffer in single query

### 3. Implement Smart Prefetching
**Problem**: Loading annotations on scroll causes visible lag.

**Implementation**:
- **Frontend**: Load visible pages ± 2 for smooth scrolling
- **Caching**: Keep recently viewed pages in memory
- **Invalidation**: Clear cache on corpus/document change

## Quick Wins (Can Do Immediately)

### 4. Optimize Existing allAnnotations Query
Until frontend migration is complete, ensure `allAnnotations` uses the query optimizer:
```python
def resolve_all_annotations(self, info, corpus_id=None, ...):
    # Use optimizer instead of raw ORM
    return AnnotationQueryOptimizer.get_document_annotations(
        document_id=self.id,
        user=info.context.user,
        corpus_id=corpus_id,
        use_cache=True  # This alone provides 5-10x speedup
    )
```

### 5. Add Usage Monitoring
Track which queries are being used to measure migration progress:
- Log `allAnnotations` usage with warning
- Log `pageAnnotations` usage with page counts
- Dashboard showing query patterns over time

## Medium Priority Enhancements

### 6. Navigation Index Field
- Expose `annotation_navigation_mv` data via GraphQL
- Enables jump-to menu without loading all annotations
- Already have the MV, just need GraphQL field

### 7. Batch Operations
- `pageAnnotationsBatch(pages: [Int!])` for non-contiguous pages
- Relationship batch loading
- Label statistics batching

### 8. Request-Scoped Permission Cache
- Cache permission checks within single GraphQL request
- Reduces repeated database hits for same document/corpus
- Store in `info.context._permission_cache`

## Migration Plan

### Week 1: Backend Preparation
- [ ] Add multi-page support to query optimizer
- [ ] Update GraphQL resolver for multiple pages
- [ ] Add monitoring/metrics
- [ ] Deploy and verify with single-page queries still working

### Week 2: Frontend Migration
- [ ] Implement viewport detection hook
- [ ] Create page-based loading component
- [ ] Update annotation atoms/context
- [ ] Test with subset of users

### Week 3: Rollout & Optimization
- [ ] Enable for all users
- [ ] Fine-tune buffer sizes
- [ ] Monitor performance metrics
- [ ] Remove old query paths once stable

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Initial Load Time | 10-30s | <500ms |
| Query Count | 1 massive | 3-5 per viewport |
| Data Transfer | 5-10MB | ~50KB/page |
| Memory Usage | 500MB+ | <50MB |
| Scroll Performance | Janky | Smooth |

## Technical Debt to Address

- Remove `allAnnotations` field entirely once migration complete
- Consolidate duplicate annotation filtering logic
- Document progressive loading patterns for future features
- Add e2e tests for viewport-based loading

## References
- Query Optimizer: `opencontractserver/annotations/query_optimizer.py`
- GraphQL Types: `config/graphql/graphene_types.py`
- Frontend Component: `frontend/src/components/knowledge_base/document/DocumentKnowledgeBase.tsx`
- Original optimization doc: `docs/frontend/doc-data-query-optimizations.md`

