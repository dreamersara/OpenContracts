# Query Optimization Quick Reference

## 🚀 TL;DR - Key Changes

**Old Way (Monolithic):**
- One massive query fetches everything
- 30-60 second load times for large documents
- N+1 query problems everywhere

**New Way (Progressive):**
- Load data on-demand as needed
- Sub-second initial load times
- Optimized queries with prefetching

## 🎯 Essential Commands

### For Developers

```python
# ALWAYS use the query optimizer
from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer

# Get annotations (optimized)
annotations = AnnotationQueryOptimizer.get_document_annotations(
    document_id=doc_id,
    corpus_id=corpus_id,
    page=page_number,  # Optional: filter by page
    analysis_id=analysis_id  # Optional: filter by analysis
)

# Get summary (instant from materialized view)
summary = AnnotationQueryOptimizer.get_annotation_summary(
    document_id=doc_id,
    corpus_id=corpus_id
)

# Invalidate cache after changes
AnnotationQueryOptimizer.invalidate_cache(doc_id, corpus_id)
```

### For GraphQL Queries

```graphql
# Fast summary (materialized view)
query QuickSummary($docId: String!, $corpusId: ID!) {
  document(id: $docId) {
    annotationSummary(corpusId: $corpusId) {
      annotationCount
      pagesWithAnnotations
    }
  }
}

# Page-specific annotations (indexed)
query PageAnnotations($docId: String!, $corpusId: ID!, $page: Int!) {
  document(id: $docId) {
    pageAnnotations(corpusId: $corpusId, page: $page) {
      id
      rawText
      userFeedback { totalCount }
    }
  }
}
```

## ⚠️ Common Mistakes to Avoid

### ❌ DON'T: Direct ORM Queries
```python
# BAD - No optimization, causes N+1
annotations = Annotation.objects.filter(document_id=doc_id)
for ann in annotations:
    feedback = ann.user_feedback.all()  # N+1 QUERY!
```

### ✅ DO: Use Query Optimizer
```python
# GOOD - Optimized with prefetching
annotations = AnnotationQueryOptimizer.get_document_annotations(
    document_id=doc_id
)
# user_feedback is already prefetched!
```

### ❌ DON'T: Forget to Combine Annotations
```python
# BAD - Missing structural annotations
page_anns = get_page_annotations(page=1)
return page_anns  # Incomplete!
```

### ✅ DO: Combine Structural + Page
```python
# GOOD - Complete annotation set
structural = get_structural_annotations()
page_anns = get_page_annotations(page=1)
all_anns = combine_and_deduplicate(structural + page_anns)
```

### ❌ DON'T: Use Wrong Related Names
```python
# BAD - Wrong related name (common bug!)
.prefetch_related("userfeedback_set")  # WRONG!
```

### ✅ DO: Use Correct Related Names
```python
# GOOD - Correct related name
.prefetch_related("user_feedback")  # RIGHT!
```

## 📊 Performance Cheat Sheet

| Operation | Old Time | New Time | Method |
|-----------|----------|----------|---------|
| Get Summary | 2-5s | <100ms | Materialized View |
| Load Page | 500ms | 50ms | Indexed Query |
| Initial Load (100 pages) | 30s | 500ms | Progressive Loading |
| Get Structural | 2s | 200ms | Prefetch Related |

## 🔍 Debug Commands

### Check Query Count
```python
from django.db import connection
from django.db import reset_queries

reset_queries()
# Your code here
print(f"Queries: {len(connection.queries)}")
```

### Check Materialized View Staleness
```sql
SELECT
    NOW() - pg_stat_user_tables.last_vacuum as staleness
FROM pg_stat_user_tables
WHERE tablename = 'annotation_summary_mv';
```

### Force Cache Clear
```python
from django.core.cache import cache
cache.clear()  # Nuclear option

# Or pattern-based
cache.delete_pattern(f"annotations:{doc_id}:*")
```

## 🏗️ Database Indexes

Key indexes that make it fast:

```sql
-- Composite index for corpus + document + page
CREATE INDEX idx_annotation_corpus_doc_page
ON annotations_annotation(corpus_id, document_id, page);

-- Structural annotations index
CREATE INDEX idx_annotation_structural
ON annotations_annotation(structural)
WHERE structural = true;

-- Analysis filter index
CREATE INDEX idx_annotation_analysis
ON annotations_annotation(analysis_id)
WHERE analysis_id IS NOT NULL;
```

## 📈 Monitoring Queries

### In Development
```python
# settings/local.py
LOGGING = {
    'loggers': {
        'django.db.backends': {
            'level': 'DEBUG',  # See all SQL
        }
    }
}
```

### In Production
```python
# Add to view or middleware
from django.db import connection

# After request
logger.info(f"Query count: {len(connection.queries)}")
```

## 🎭 Test Data Tips

### Creating Test Data
```python
# ALWAYS use valid enum values!
label = AnnotationLabel.objects.create(
    label_type="SPAN_LABEL",  # ✅ Valid
    # NOT: "human_annotation"  # ❌ Old/Invalid
)

# Use TransactionTestCase for clean state
class MyTest(TransactionTestCase):  # ✅
    # NOT: BaseFixtureTestCase  # ❌ Has old data
```

### Testing Data Parity
```python
# Always combine and deduplicate
structural = result['allStructuralAnnotations']
page_anns = result['pageAnnotations']
combined = deduplicate(structural + page_anns)

# Assert same data
assert len(combined) == len(monolithic_result)
```

## 🔄 Migration Checklist

When migrating code to use progressive loading:

- [ ] Replace `GET_DOCUMENT_KNOWLEDGE_AND_ANNOTATIONS` with progressive queries
- [ ] Add `prefetch_related("user_feedback")` to annotation queries
- [ ] Use `AnnotationQueryOptimizer` instead of direct ORM
- [ ] Combine structural + page annotations correctly
- [ ] Test data parity with monolithic approach
- [ ] Add loading states to UI for progressive updates
- [ ] Monitor query counts and performance

## 💡 Pro Tips

1. **Materialized views refresh automatically** after annotation changes
2. **Cache TTL is 5 minutes** - usually enough for active editing
3. **First 3 pages load by default** - adjust based on viewport
4. **Analysis filter changes behavior** - None = user annotations, ID = analysis annotations
5. **Structural annotations ignore corpus** - they're document-wide

## 🆘 Getting Help

- Check query count: `len(connection.queries)`
- View SQL: `str(queryset.query)`
- Check cache: `cache.get(f"annotation_summary:{doc_id}:{corpus_id}")`
- Force refresh: `use_mv=False` in query optimizer calls
- Debug logging: `logger.setLevel(logging.DEBUG)`

## 📚 Full Documentation

- [Architectural Overview](./query-optimization-paradigm.md)
- [Implementation Examples](./implementation-examples.md)
- [Performance Benchmarks](../../../frontend/doc-data-query-optimizations.md)

---

**Remember:** The goal is **sub-second initial loads** with **complete data parity**. When in doubt, use the `AnnotationQueryOptimizer`!
