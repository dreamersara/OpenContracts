# Comprehensive Performance Improvement Plan for Document Annotation System

## 🎯 Core Problem

The `GetDocumentKnowledgeAndAnnotations` query loads ALL annotations, relationships, and notes for an entire corpus in a single request, causing 10-30+ second load times. However, we need to maintain the ability to jump to any annotation anywhere in the document instantly.

## 📋 Strategic Approach

Implement a **three-tier data loading strategy** that balances performance with UX requirements:

1. **Navigation Layer** - Lightweight index for jumping (always loaded)
2. **Active Layer** - Full data for current/target pages (loaded on demand)
3. **Background Layer** - Remaining data (loaded progressively)

---

## Phase 1: Foundation (Week 1-2)

_Enable fast navigation without loading everything_

### 1.1 Create Annotation Manifest System

- **New GraphQL Type**: `AnnotationManifestType` containing:
  - Total annotation count by type
  - Page-level annotation index (id, page, label, minimal position data)
  - Structural annotation IDs (cached separately)
- **Affected Files**:
  - `/config/graphql/graphene_types.py` - Add new type and resolver
  - `/frontend/src/graphql/queries.ts` - Add manifest query
- **Purpose**: Enable instant jump-to-annotation with ~10KB instead of ~10MB

### 1.2 Split Monolithic Query

- **Replace** `GetDocumentKnowledgeAndAnnotations` with:
  - `GetDocumentWithManifest` - Document basics + annotation index
  - `GetPageAnnotations` - Full data for specific page(s)
  - `GetDocumentNotes` - Paginated notes (separate query)
  - `GetDocumentRelationships` - Paginated relationships (separate query)
- **Affected Components**:
  - `/frontend/src/components/knowledge_base/document/DocumentKnowledgeBase.tsx`
  - Existing `processAnnotationsData` function needs complete rewrite

### 1.3 Implement Page-Based Annotation Loading

- **Backend**: Add `page_annotations` resolver with proper prefetching
  - Must include: `select_related('annotation_label', 'creator', 'analysis')`
  - Must include: `prefetch_related('user_feedback__edges__node')`
- **Frontend**: New loading strategy in `DocumentKnowledgeBase.tsx`:
  ```typescript
  // Pseudocode for new loading pattern
  1. Load manifest on component mount
  2. If targetAnnotationId exists, load that page first
  3. Load current viewport pages
  4. Queue background loading of remaining pages
  ```

---

## Phase 2: Optimization (Week 2-3)

_Make the fast path faster_

### 2.1 Database Indexing

- **Required Indexes**:

  ```sql
  -- Critical for page-based loading
  CREATE INDEX idx_annotation_doc_page ON annotation(document_id, page, corpus_id);

  -- Critical for corpus filtering
  CREATE INDEX idx_annotation_corpus_analysis ON annotation(corpus_id, analysis_id)
    WHERE structural = false;

  -- For structural annotation queries
  CREATE INDEX idx_annotation_structural ON annotation(document_id)
    WHERE structural = true;
  ```

- **Location**: New migration in `/opencontractserver/annotations/migrations/`

### 2.2 Implement DataLoader for N+1 Prevention

- **Target Resolvers**:
  - `AnnotationType.user_feedback` (currently triggers query per annotation)
  - `RelationshipType.source_annotations`
  - `RelationshipType.target_annotations`
- **New File**: `/config/graphql/dataloaders.py`
- **Integration**: Update middleware in `/config/graphql/permissioning/`

### 2.3 Add Redis Caching Layer

- **Cache Targets**:
  - Annotation manifest (TTL: 5 minutes)
  - Structural annotations (TTL: 1 hour)
  - Corpus label sets (TTL: 1 hour)
- **Affected Files**:
  - `/config/graphql/graphene_types.py` - Add cache decorators
  - New utility: `/opencontractserver/utils/cache_utils.py`

---

## Phase 3: Progressive Enhancement (Week 3-4)

_Smooth user experience_

### 3.1 Viewport-Aware Loading System

- **Frontend Components**:
  - New hook: `useViewportAnnotationLoader`
  - Manages priority queue for page loading
  - Preloads ±2 pages from current viewport
- **Location**: `/frontend/src/components/annotator/hooks/`

### 3.2 Client-Side Caching Enhancement

- **Extend existing** `documentCacheManager.ts` to handle:
  - Annotation manifest (stored in IndexedDB)
  - Page-level annotation data
  - Note: Keep structural annotations in memory (they're used everywhere)
- **Update Apollo Cache Policy**:
  - Manifest: `cache-first`
  - Page annotations: `cache-and-network`
  - Notes/Relationships: `network-only` (can change frequently)

### 3.3 Background Loading Queue

- **New Service**: `/frontend/src/services/annotationQueueLoader.ts`
  - Manages progressive loading of non-visible pages
  - Respects network conditions
  - Cancellable on navigation
- **Integration Point**: `DocumentKnowledgeBase.tsx` `useEffect` hooks

---

## Phase 4: Advanced Optimization (Week 4+)

_Scale to massive documents_

### 4.1 Aggregation Endpoints

- **New GraphQL Fields**:
  ```graphql
  type DocumentType {
    annotationStats(corpusId: ID!): AnnotationStats!
    noteCount(corpusId: ID!): Int!
    relationshipCount(corpusId: ID!): Int!
  }
  ```
- **Purpose**: Display counts without loading data

### 4.2 Materialized Views for Common Patterns

- **Database Views**:
  - `annotation_page_summary` - Pre-aggregated page counts
  - `document_corpus_stats` - Pre-calculated statistics
- **Update Triggers**: On annotation create/update/delete

### 4.3 Query Complexity Limiting

- **Implement** query depth limiting in `/config/graphql/schema.py`
- **Add** query cost analysis to prevent expensive queries
- **Set** maximum result set sizes

---

## 📊 Success Metrics

### Target Performance:

- **Initial Document Load**: < 500ms (vs current 10-30s)
- **Jump to Annotation**: < 200ms (maintain current UX)
- **Page Navigation**: < 100ms (with preloading)
- **Full Document Background Load**: 5-10s (invisible to user)

### Key Measurements:

1. Time to First Meaningful Paint (document visible)
2. Time to Annotation Jump Ready (manifest loaded)
3. Time to Full Interactivity (current page fully loaded)
4. Total Data Transfer (should reduce by 80-90%)

---

## 🚨 Critical Path Items

### Must Complete First:

1. **Annotation Manifest** - Nothing works without this
2. **Page-based Loading** - Core of the new architecture
3. **Database Indexes** - Immediate performance boost

### Can Defer:

- Redis caching (nice-to-have)
- Materialized views (optimization)
- Query complexity limiting (protection)

---

## 🔄 Migration Strategy

### Phase 1: Parallel Implementation

- Keep existing query working
- Add new queries alongside
- Feature flag to switch between old/new

### Phase 2: Gradual Rollout

- Test with small corpora first
- Monitor performance metrics
- Gradually increase usage

### Phase 3: Deprecation

- Remove old query
- Clean up unused code
- Document new patterns

---

## 📝 Known Technical Requirements

### Backend Changes:

- `DocumentType` in `/config/graphql/graphene_types.py` - Major refactor
- New resolvers for manifest and page-based queries
- Database migrations for indexes
- Possible new Django model for annotation summaries

### Frontend Changes:

- `DocumentKnowledgeBase.tsx` - Complete rewrite of data loading
- New GraphQL queries in `/frontend/src/graphql/queries/`
- Extended caching in `documentCacheManager.ts`
- New loading state management

### Infrastructure:

- Redis setup for caching (optional but recommended)
- Monitoring for query performance
- Possible CDN for static annotation data

---

## Implementation Notes

### Current Query Structure Issues:

1. **N+1 Query Problems** - Each resolver executes separate database queries without prefetching
2. **No Pagination** - Returns ALL annotations, relationships, and notes for a corpus
3. **Nested Relationship Loading** - userFeedback edges trigger additional queries per annotation
4. **Multiple Distinct() Operations** - Expensive distinct operations on large datasets
5. **Complex Permission Checks** - Permission annotator middleware runs for each object
6. **No Query Optimization** - Missing select_related/prefetch_related calls
7. **No Caching** - Structural annotations are repeatedly fetched without caching

### Files Requiring Updates:

- `/config/graphql/graphene_types.py` - DocumentType class (lines 557-805)
- `/frontend/src/components/knowledge_base/document/DocumentKnowledgeBase.tsx`
- `/frontend/src/graphql/queries.ts`
- `/opencontractserver/annotations/models.py` - Annotation model
- `/config/graphql/schema.py` - Query definitions

This plan maintains the critical UX requirement (instant annotation jumping) while dramatically improving performance through intelligent data loading strategies.
