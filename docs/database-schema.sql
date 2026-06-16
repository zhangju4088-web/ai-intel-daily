-- PostgreSQL schema draft for the AI intelligence MVP.
-- This file is a design baseline; adapt indexes and enum values during implementation.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE login_captcha_challenges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  challenge_key TEXT NOT NULL UNIQUE,
  answer_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE login_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_token_hash TEXT NOT NULL UNIQUE,
  ip_address INET,
  user_agent TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE login_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT,
  ip_address INET,
  user_agent TEXT,
  success BOOLEAN NOT NULL DEFAULT FALSE,
  failure_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX login_attempts_ip_created_idx ON login_attempts(ip_address, created_at DESC);
CREATE INDEX login_attempts_email_created_idx ON login_attempts(email, created_at DESC);

CREATE TABLE sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category_hint TEXT NOT NULL CHECK (category_hint IN ('大模型动态', 'AI行业资讯', '国际形势影响', '国际金融', 'auto')),
  source_type TEXT NOT NULL CHECK (source_type IN ('official', 'media', 'research', 'finance', 'wechat', 'other')),
  method TEXT NOT NULL CHECK (method IN ('rss', 'rsshub', 'crawl', 'sitemap', 'playwright', 'manual_link')),
  url TEXT,
  account_id TEXT,
  language TEXT NOT NULL DEFAULT 'zh',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  weight NUMERIC(5, 2) NOT NULL DEFAULT 1.00,
  crawl_interval_minutes INT NOT NULL DEFAULT 720,
  selectors JSONB,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE source_fetch_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('success', 'partial', 'failed')),
  fetched_count INT NOT NULL DEFAULT 0,
  new_count INT NOT NULL DEFAULT 0,
  error_message TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE raw_articles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
  source_type TEXT NOT NULL,
  original_title TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  author TEXT,
  published_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw_excerpt TEXT,
  extracted_text TEXT,
  extracted_text_hash TEXT,
  title_hash TEXT,
  language TEXT NOT NULL DEFAULT 'zh',
  fetch_status TEXT NOT NULL DEFAULT 'pending' CHECK (fetch_status IN ('pending', 'extracted', 'failed', 'skipped')),
  UNIQUE (canonical_url)
);

CREATE INDEX raw_articles_source_id_idx ON raw_articles(source_id);
CREATE INDEX raw_articles_published_at_idx ON raw_articles(published_at DESC);
CREATE INDEX raw_articles_text_hash_idx ON raw_articles(extracted_text_hash);
CREATE INDEX raw_articles_title_hash_idx ON raw_articles(title_hash);

CREATE TABLE events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_date DATE NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('大模型动态', 'AI行业资讯', '国际形势影响', '国际金融')),
  ai_title TEXT NOT NULL,
  one_sentence_summary TEXT NOT NULL,
  detailed_summary TEXT NOT NULL,
  key_points JSONB NOT NULL DEFAULT '[]'::jsonb,
  why_it_matters TEXT,
  impact_analysis JSONB NOT NULL DEFAULT '{}'::jsonb,
  topic_angle TEXT,
  avoid_angle TEXT,
  recommended BOOLEAN NOT NULL DEFAULT FALSE,
  priority_score NUMERIC(5, 2) NOT NULL DEFAULT 0,
  confidence NUMERIC(4, 3) NOT NULL DEFAULT 0,
  source_count INT NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'hidden', 'archived')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX events_event_date_category_score_idx ON events(event_date DESC, category, priority_score DESC);
CREATE INDEX events_recommended_idx ON events(event_date DESC, recommended, priority_score DESC);

CREATE TABLE event_sources (
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  article_id UUID NOT NULL REFERENCES raw_articles(id) ON DELETE CASCADE,
  source_role TEXT NOT NULL CHECK (source_role IN ('primary', 'supporting', 'wechat_analysis', 'duplicate')),
  link_label TEXT,
  display_order INT NOT NULL DEFAULT 100,
  is_primary_reading_link BOOLEAN NOT NULL DEFAULT FALSE,
  similarity_score NUMERIC(4, 3),
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (event_id, article_id)
);

CREATE INDEX event_sources_event_order_idx ON event_sources(event_id, display_order, source_role);

CREATE VIEW event_reading_links AS
SELECT
  es.event_id,
  ra.id AS article_id,
  s.id AS source_id,
  s.name AS source_name,
  s.source_type,
  es.source_role,
  COALESCE(es.link_label, s.name) AS link_label,
  ra.original_title,
  ra.canonical_url,
  ra.published_at,
  es.display_order,
  es.is_primary_reading_link
FROM event_sources es
JOIN raw_articles ra ON ra.id = es.article_id
JOIN sources s ON s.id = ra.source_id
ORDER BY es.event_id, es.display_order, es.source_role, ra.published_at DESC NULLS LAST;

CREATE TABLE daily_digests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  digest_date DATE NOT NULL UNIQUE,
  top10_event_ids UUID[] NOT NULL DEFAULT '{}',
  topic_pool JSONB NOT NULL DEFAULT '[]'::jsonb,
  peer_hot_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
  hidden_gems JSONB NOT NULL DEFAULT '[]'::jsonb,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE saved_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('saved', 'to_write', 'writing', 'done', 'ignored')),
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, event_id)
);

CREATE TABLE prompt_templates (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  model TEXT NOT NULL,
  template TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE operation_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  ip_address INET,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
