"""Benchmark/oracle harness for generate_and_download_report.

Run from an Odoo shell against a real database. Produces a baseline
xlsx (oracle), a per-step timing breakdown and a deterministic hash
that can be diff'd between optimizations.

Usage (Odoo shell):

    from odoo.addons.l10n_co_exogenous_information_reporting.tools.benchmark_report import (
        run_baseline, diff_against_oracle,
    )
    setting = env['l10n_co.exogenous_format_setting'].browse(SETTING_ID)

    # Once, before any optimization is applied:
    oracle = run_baseline(setting, label='baseline')

    # After each optimization, compare:
    after = run_baseline(setting, label='step1')
    diff_against_oracle(oracle['xlsx_path'], after['xlsx_path'])

The harness writes the xlsx to /tmp and prints timings and a SHA-256
of the *normalized* dataframe (rows sorted by all columns, numbers
forced to int64) so a small float reordering does not produce a false
positive diff.
"""

import hashlib
import io
import logging
import os
import time
from contextlib import contextmanager

import pandas as pd
from openpyxl import load_workbook

_logger = logging.getLogger(__name__)


@contextmanager
def _timed(label, timings):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        timings[label] = time.perf_counter() - t0


def _xlsx_to_dataframe(path):
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.values)
    if not rows:
        return pd.DataFrame()
    header, *data = rows
    df = pd.DataFrame(data, columns=header)
    return df


def _normalize_for_hash(df):
    """Sort rows so that ordering differences don't produce false diffs."""
    if df.empty:
        return df
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].fillna(0).round(0).astype('int64')
        else:
            df[col] = df[col].fillna('').astype(str)
    df = df.sort_values(by=list(df.columns), kind='stable').reset_index(drop=True)
    return df


def _hash_dataframe(df):
    norm = _normalize_for_hash(df)
    payload = norm.to_csv(index=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def run_baseline(setting, label='baseline', out_dir='/tmp'):
    """Generate the report, save xlsx, return timings + hash."""
    timings = {}
    with _timed('total', timings):
        setting.generate_and_download_report()

    if not setting.binary_file:
        raise RuntimeError("Report did not produce a binary_file")

    import base64
    xlsx_bytes = base64.b64decode(setting.binary_file)
    xlsx_path = os.path.join(out_dir, f"exogena_{label}_{setting.id}.xlsx")
    with open(xlsx_path, 'wb') as fh:
        fh.write(xlsx_bytes)

    df = _xlsx_to_dataframe(xlsx_path)
    digest = _hash_dataframe(df)

    _logger.info("[%s] rows=%d cols=%d total=%.3fs sha256=%s",
                 label, len(df), len(df.columns), timings['total'], digest)

    return {
        'label': label,
        'xlsx_path': xlsx_path,
        'rows': len(df),
        'cols': len(df.columns),
        'timings': timings,
        'sha256': digest,
        'dataframe': df,
    }


def diff_against_oracle(oracle_path, candidate_path):
    """Print a row-by-row diff between two xlsx files (after normalization)."""
    df_a = _normalize_for_hash(_xlsx_to_dataframe(oracle_path))
    df_b = _normalize_for_hash(_xlsx_to_dataframe(candidate_path))

    if df_a.shape != df_b.shape:
        _logger.error("Shape diff: oracle=%s candidate=%s", df_a.shape, df_b.shape)
        return False

    if list(df_a.columns) != list(df_b.columns):
        _logger.error("Column diff:\n  oracle:    %s\n  candidate: %s",
                      list(df_a.columns), list(df_b.columns))
        return False

    eq = (df_a == df_b)
    if eq.all().all():
        _logger.info("OK: oracle == candidate (%d rows)", len(df_a))
        return True

    bad_rows = (~eq.all(axis=1))
    _logger.error("DIFF: %d rows differ. First 10:", bad_rows.sum())
    for idx in df_a[bad_rows].index[:10]:
        for col in df_a.columns:
            if df_a.at[idx, col] != df_b.at[idx, col]:
                _logger.error("  row=%d col=%s oracle=%r candidate=%r",
                              idx, col, df_a.at[idx, col], df_b.at[idx, col])
    return False
