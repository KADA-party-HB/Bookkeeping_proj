CREATE TABLE IF NOT EXISTS admin_calendar_notes (
  id SERIAL PRIMARY KEY,
  note_date DATE NOT NULL,
  note_text TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_calendar_notes_note_date
  ON admin_calendar_notes(note_date, created_at);
