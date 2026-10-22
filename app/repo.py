"""Data access. THIS is where ownership is enforced.

Every function that reads or changes user data takes `user_id` and puts it in the WHERE clause:
    SELECT ... WHERE id = ? AND user_id = ?
So even if a route forgets to check, another user's row can never be returned. "Not yours" and
"does not exist" look identical (no row), so the API answers 404 for both and leaks nothing.
The only function that works without a user is get_shared_report(), and it needs a valid,
unexpired, unrevoked share token.
"""
import json
import sqlite3
import time

from .engine import Table


def now() -> int:
    return int(time.time())


# ---------------------------------------------------------------- users & sessions

def create_user(conn, email, password_hash):
    try:
        cur = conn.execute("INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                           (email, password_hash, now()))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_user_by_email(conn, email):
    return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def create_session(conn, user_id, token_hash, expires_at):
    conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                 (token_hash, user_id, expires_at))
    conn.commit()


def get_session_user(conn, token_hash, at):
    return conn.execute(
        "SELECT u.id, u.email FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > ?", (token_hash, at)).fetchone()


def delete_session(conn, token_hash):
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
    conn.commit()


# ---------------------------------------------------------------- datasets

def insert_dataset(conn, user_id, name, filename, profile, rows):
    cur = conn.execute(
        "INSERT INTO datasets (user_id, name, original_filename, profile_json, row_count, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, name, filename, json.dumps(profile), profile["row_count"], now()))
    dataset_id = cur.lastrowid
    conn.executemany("INSERT INTO data_rows (dataset_id, row_num, values_json) VALUES (?, ?, ?)",
                     ((dataset_id, line, json.dumps(values)) for line, values in rows))
    conn.commit()
    return dataset_id


def list_datasets(conn, user_id):
    return conn.execute(
        "SELECT id, name, original_filename, row_count, profile_json, created_at FROM datasets "
        "WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user_id,)).fetchall()


def get_dataset(conn, user_id, dataset_id):
    return conn.execute("SELECT * FROM datasets WHERE id = ? AND user_id = ?", (dataset_id, user_id)).fetchone()

def count_reports(conn, user_id, dataset_id):
    return conn.execute("SELECT COUNT(*) FROM reports WHERE dataset_id = ? AND user_id = ?",
                        (dataset_id, user_id)).fetchone()[0]


def delete_dataset(conn, user_id, dataset_id):
    """Deletes the dataset's rows, its reports and their share links too (ON DELETE CASCADE).
    Only the owner can do it: the user_id is part of the WHERE clause."""
    cur = conn.execute("DELETE FROM datasets WHERE id = ? AND user_id = ?", (dataset_id, user_id))
    conn.commit()
    return cur.rowcount == 1

def load_table(conn, user_id, dataset_id):
    ds = get_dataset(conn, user_id, dataset_id)
    if ds is None:
        return None
    columns = json.loads(ds["profile_json"])["columns"]
    rows = [(r["row_num"], json.loads(r["values_json"])) for r in conn.execute(
        "SELECT row_num, values_json FROM data_rows WHERE dataset_id = ? ORDER BY row_num", (dataset_id,))]
    return Table(columns, rows)


def preview_rows(conn, user_id, dataset_id, limit=10):
    if get_dataset(conn, user_id, dataset_id) is None:
        return []
    return [{"row": r["row_num"], "cells": json.loads(r["values_json"])} for r in conn.execute(
        "SELECT row_num, values_json FROM data_rows WHERE dataset_id = ? ORDER BY row_num LIMIT ?",
        (dataset_id, limit))]


# ---------------------------------------------------------------- reports

def insert_report(conn, user_id, dataset_id, title):
    if get_dataset(conn, user_id, dataset_id) is None:   # you can only build on your own dataset
        return None
    t = now()
    cur = conn.execute(
        "INSERT INTO reports (user_id, dataset_id, title, blocks_json, filters_json, created_at, updated_at) "
        "VALUES (?, ?, ?, '[]', '{}', ?, ?)", (user_id, dataset_id, title, t, t))
    conn.commit()
    return cur.lastrowid


def list_reports(conn, user_id):
    return conn.execute(
        "SELECT r.id, r.title, r.updated_at, d.name AS dataset_name FROM reports r "
        "JOIN datasets d ON d.id = r.dataset_id WHERE r.user_id = ? ORDER BY r.updated_at DESC, r.id DESC",
        (user_id,)).fetchall()


def get_report(conn, user_id, report_id):
    return conn.execute("SELECT * FROM reports WHERE id = ? AND user_id = ?", (report_id, user_id)).fetchone()


def update_report(conn, user_id, report_id, title, blocks, filters):
    cur = conn.execute(
        "UPDATE reports SET title = ?, blocks_json = ?, filters_json = ?, updated_at = ? "
        "WHERE id = ? AND user_id = ?",
        (title, json.dumps(blocks), json.dumps(filters), now(), report_id, user_id))
    conn.commit()
    return cur.rowcount == 1


def delete_report(conn, user_id, report_id):
    cur = conn.execute("DELETE FROM reports WHERE id = ? AND user_id = ?", (report_id, user_id))
    conn.commit()
    return cur.rowcount == 1


# ---------------------------------------------------------------- share links

def create_share(conn, user_id, report_id, token_hash, hint, expires_at):
    if get_report(conn, user_id, report_id) is None:
        return None
    cur = conn.execute(
        "INSERT INTO share_links (report_id, token_hash, token_hint, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (report_id, token_hash, hint, now(), expires_at))
    conn.commit()
    return cur.lastrowid


def list_shares(conn, user_id, report_id):
    return conn.execute(
        "SELECT s.id, s.token_hint, s.created_at, s.expires_at, s.revoked_at FROM share_links s "
        "JOIN reports r ON r.id = s.report_id WHERE s.report_id = ? AND r.user_id = ? "
        "ORDER BY s.created_at DESC, s.id DESC", (report_id, user_id)).fetchall()


def revoke_share(conn, user_id, report_id, share_id):
    cur = conn.execute(
        "UPDATE share_links SET revoked_at = ? WHERE id = ? AND report_id = ? AND revoked_at IS NULL "
        "AND report_id IN (SELECT id FROM reports WHERE id = ? AND user_id = ?)",
        (now(), share_id, report_id, report_id, user_id))
    conn.commit()
    return cur.rowcount == 1


def get_shared_report(conn, token_hash, at):
    """The one lookup that needs no user. Valid only if the link is unrevoked and unexpired.
    Checked on EVERY request, so revoking takes effect immediately."""
    return conn.execute(
        "SELECT r.*, s.expires_at AS link_expires_at FROM share_links s JOIN reports r ON r.id = s.report_id "
        "WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?", (token_hash, at)).fetchone()
