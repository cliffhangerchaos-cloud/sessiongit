"""
Search functionality for SessionGit using SQLite FTS5

Provides fast full-text search across sessions with filters for date, status, etc.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import json


class SessionSearch:
    """Full-text search engine for sessions"""

    def __init__(self, storage_path: Path):
        """
        Initialize search engine

        Args:
            storage_path: Path to SessionGit storage directory
        """
        self.storage_path = Path(storage_path)
        self.db_path = self.storage_path / "search.db"

        # Create search database if needed
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with FTS5 tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create FTS5 table for session content
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS session_search USING fts5(
                session_id UNINDEXED,
                title,
                user_content,
                assistant_content,
                state_content,
                turn_number UNINDEXED,
                timestamp UNINDEXED,
                tokenize = 'porter unicode61'
            )
        """)

        # Create metadata table for filtering
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_metadata (
                session_id TEXT PRIMARY KEY,
                title TEXT,
                status TEXT,
                created TEXT,
                last_active TEXT,
                total_turns INTEGER,
                provider TEXT,
                model TEXT,
                source TEXT
            )
        """)

        # Create index on commonly filtered fields
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_status ON session_metadata(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_created ON session_metadata(created)
        """)

        conn.commit()
        conn.close()

    def index_session(self, session_manager, session_id: str, incremental: bool = True):
        """
        Index a session for searching

        Args:
            session_manager: SessionManager instance
            session_id: Session to index
            incremental: If True, only index new turns; if False, reindex everything
        """
        # Load session
        session = session_manager.load_session(session_id, load_all_turns=True)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Index session metadata
            cursor.execute("""
                INSERT OR REPLACE INTO session_metadata
                (session_id, title, status, created, last_active, total_turns, provider, model, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session.metadata.session_id,
                session.metadata.title,
                session.metadata.status,
                session.metadata.created.isoformat(),
                session.metadata.last_active.isoformat(),
                session.metadata.total_turns,
                session.metadata.provider,
                session.metadata.primary_model,
                session.metadata.source,
            ))

            # Determine which turns to index
            if incremental:
                # Get last indexed turn
                cursor.execute("""
                    SELECT MAX(turn_number) FROM session_search WHERE session_id = ?
                """, (session_id,))
                result = cursor.fetchone()
                last_indexed = result[0] if result[0] is not None else 0
                turns_to_index = [t for t in session.turns if t.turn > last_indexed]
            else:
                # Reindex everything - delete old entries
                cursor.execute("DELETE FROM session_search WHERE session_id = ?", (session_id,))
                turns_to_index = session.turns

            # Index turns
            for turn in turns_to_index:
                # Extract state content
                state_content = " ".join([
                    turn.state.goal,
                    turn.state.next_step,
                    turn.state.context_summary,
                    " ".join(turn.state.decisions or []),
                    " ".join(turn.state.open_questions or []),
                ])

                cursor.execute("""
                    INSERT INTO session_search
                    (session_id, title, user_content, assistant_content, state_content, turn_number, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    session.metadata.session_id,
                    session.metadata.title,
                    turn.user_input.content,
                    turn.assistant_output.content,
                    state_content,
                    turn.turn,
                    turn.timestamp.isoformat(),
                ))

            conn.commit()

        finally:
            conn.close()

    def index_all_sessions(self, session_manager):
        """
        Index all sessions in the repository

        Args:
            session_manager: SessionManager instance
        """
        sessions = session_manager.list_sessions()

        for session in sessions:
            try:
                self.index_session(session_manager, session.metadata.session_id, incremental=True)
            except Exception as e:
                print(f"Warning: Failed to index session {session.metadata.session_id}: {e}")

    def search(
        self,
        query: str,
        status: Optional[str] = None,
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search sessions

        Args:
            query: Search query (FTS5 syntax)
            status: Filter by status (active, archived)
            after_date: Only sessions created after this date
            before_date: Only sessions created before this date
            provider: Filter by provider
            model: Filter by model
            limit: Maximum results to return

        Returns:
            List of search results with metadata and snippets
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Build query with filters
        sql_parts = ["""
            SELECT
                s.session_id,
                s.title,
                s.turn_number,
                s.timestamp,
                snippet(session_search, -1, '[MATCH]', '[/MATCH]', '...', 32) as snippet,
                m.status,
                m.created,
                m.total_turns,
                m.provider,
                m.model
            FROM session_search s
            JOIN session_metadata m ON s.session_id = m.session_id
        """]

        conditions = ["session_search MATCH ?"]
        params = [query]

        if status:
            conditions.append("m.status = ?")
            params.append(status)

        if after_date:
            conditions.append("m.created >= ?")
            params.append(after_date.isoformat())

        if before_date:
            conditions.append("m.created <= ?")
            params.append(before_date.isoformat())

        if provider:
            conditions.append("m.provider = ?")
            params.append(provider)

        if model:
            conditions.append("m.model = ?")
            params.append(model)

        if conditions:
            sql_parts.append("WHERE " + " AND ".join(conditions))

        sql_parts.append("ORDER BY rank")
        sql_parts.append(f"LIMIT {limit}")

        query_sql = " ".join(sql_parts)

        try:
            cursor.execute(query_sql, params)
            results = []

            for row in cursor.fetchall():
                results.append({
                    'session_id': row[0],
                    'title': row[1],
                    'turn_number': row[2],
                    'timestamp': row[3],
                    'snippet': row[4],
                    'status': row[5],
                    'created': row[6],
                    'total_turns': row[7],
                    'provider': row[8],
                    'model': row[9],
                })

            return results

        except sqlite3.OperationalError as e:
            # FTS syntax errors
            if 'fts5' in str(e).lower() or 'syntax' in str(e).lower():
                raise ValueError(f"Invalid search query syntax: {e}")
            else:
                raise

        finally:
            conn.close()

    def remove_session(self, session_id: str):
        """
        Remove a session from the search index

        Args:
            session_id: Session to remove
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM session_search WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM session_metadata WHERE session_id = ?", (session_id,))
            conn.commit()
        finally:
            conn.close()

    def rebuild_index(self, session_manager):
        """
        Rebuild entire search index from scratch

        Args:
            session_manager: SessionManager instance
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Clear existing data
        cursor.execute("DELETE FROM session_search")
        cursor.execute("DELETE FROM session_metadata")
        conn.commit()
        conn.close()

        # Reindex all sessions
        self.index_all_sessions(session_manager)

    def stats(self) -> Dict[str, int]:
        """
        Get search index statistics

        Returns:
            Dict with index stats
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Count sessions
            cursor.execute("SELECT COUNT(DISTINCT session_id) FROM session_metadata")
            session_count = cursor.fetchone()[0]

            # Count indexed turns
            cursor.execute("SELECT COUNT(*) FROM session_search")
            turn_count = cursor.fetchone()[0]

            # Get database size
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

            return {
                'indexed_sessions': session_count,
                'indexed_turns': turn_count,
                'database_size_bytes': db_size,
            }

        finally:
            conn.close()


def get_search_engine(storage_path: Path) -> SessionSearch:
    """
    Get search engine instance

    Args:
        storage_path: SessionGit storage path

    Returns:
        SessionSearch instance
    """
    return SessionSearch(storage_path)
