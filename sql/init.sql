-- Скрипт создания таблиц для Chat API (соответствует models.py).
-- Можно выполнить вручную для пустой БД: psql -U postgres -h localhost -p 5433 -d chat -f sql/init.sql
-- Либо таблицы создаются автоматически при старте API (database.create_tables()).

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(64) NOT NULL,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_messages_session_id ON messages (session_id);

COMMENT ON TABLE users IS 'Chat API: пользователи (минимальная схема)';
COMMENT ON TABLE messages IS 'Chat API: сообщения диалогов (user/assistant)';
