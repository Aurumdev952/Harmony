---
wp: "1h"
title: "Self-hosted export renderer"
status: claimed
owner_role: "backend"
instances:
  - name: "backend-8"
    files:
      - web/server/routes/views/page_renderer.py
      - web/server/routes/page_renderer.py
      - web/server/security/render_tokens.py
      - web/server/security/signal_handlers.py
      - web/server/redis/thumbnail_storage_service.py
      - web/server/routes/views/dashboard.py
      - harmony/worker/renderer/**
      - tests/web/render/test_export_renderer.py
      - tests/web/render/test_render_tokens.py
      - tests/worker/renderer/**
      - docs/modernisation/work/WP-1h.md
      - docs/modernisation/work/WP-1h-evidence/**
branch: "mig/WP-1h-export-renderer"
requirements: [SEC-7, SEC-9, SEC-10]
contracts_consumed: []
contracts_changed: [C-5]
security_review: true
---

# WP-1h: Self-hosted export renderer

Phase 1 section 1h; 03-target-architecture (render path); decision 0004. Builds on WP-0i (`mig/WP-0i-render-route-guards`, backend-7), which is merged into this branch: WP-0i owns the route-level authorisation and the thumbnail cache key; this WP replaces urlbox.io behind the same routes.
