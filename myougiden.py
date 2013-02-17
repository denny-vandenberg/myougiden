#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import re
import gzip
import sqlite3 as sql
# import subprocess

PATHS = {}
PATHS['sharedir'] = '.'
PATHS['database'] = os.path.join(PATHS['sharedir'], 'jmdict.sqlite')
PATHS['jmdict_url'] = 'http://ftp.monash.edu.au/pub/nihongo/JMdict_e.gz'

regexp_store = {}
def get_regex(pattern, flags):
    '''Return a compiled regexp from persistent store; make one if needed.

    We use this helper function so that the SQL hooks don't have to
    compile the same regexp at every query.

    Flags are not part of the hash; i.e. this function doesn't work
    for the same pattern with different flags.
    '''

    if pattern in regexp_store.keys():
        return regexp_store[pattern]
    else:
        comp = re.compile(pattern, re.U | flags)

        regexp_store[pattern] = comp
        return comp


def regexp_sensitive(pattern, field):
    '''SQL hook function for case-sensitive regexp matching.'''
    reg = get_regex(pattern, 0)
    return reg.search(field) is not None

def regexp_insensitive(pattern, field):
    '''SQL hook function for case-insensitive regexp matching.'''
    reg = get_regex(pattern, re.I)
    return reg.search(field) is not None

def opendb(case_sensitive=False):
    '''Open SQL database; returns (con, cur).'''

    con = sql.connect(PATHS['database'])
    cur = con.cursor()

    if case_sensitive:
        con.create_function('regexp', 2, regexp_sensitive)
        cur.execute('PRAGMA case_sensitive_like = 1;')
    else:
        con.create_function('regexp', 2, regexp_insensitive)
        cur.execute('PRAGMA case_sensitive_like = 0;')


    return con, cur

def format_entry_tsv(kanjis, readings, senses):
    return '%s\t%s\t%s' % (
        '；'.join(kanjis),
        '；'.join(readings),
        ';'.join(senses)
        )

def fetch_entry(cur, ent_seq):
    '''Return tuple of lists (kanjis, readings, senses).'''

    kanjis = []
    readings = []
    senses = []

    cur.execute('SELECT kanji FROM kanjis WHERE ent_seq = ?;', [ent_seq])
    for row in cur.fetchall():
        kanjis.append(row[0])

    cur.execute('SELECT reading FROM readings WHERE ent_seq = ?;', [ent_seq])
    for row in cur.fetchall():
        readings.append(row[0])

    cur.execute('SELECT sense FROM senses WHERE ent_seq = ?;', [ent_seq])
    for row in cur.fetchall():
        senses.append(row[0])

    return (kanjis, readings, senses)


def search_by(cur, field, query, partial=False, word=False, regexp=False, case_sensitive=False):
    '''Main search function.  Return list of ent_seqs.

    Field in ('kanji', 'reading', 'sense').
    '''


    if field == 'kanji':
        table = 'kanjis'
    elif field == 'reading':
        table = 'readings'
    elif field == 'sense':
        table = 'senses'

    if regexp:
        operator = 'REGEXP'
    else:
        operator = 'LIKE'

    if regexp:
        if word:
            query = r'\b' + query + r'\b'
        elif not partial:
            query = '^' + query + '$'
    else:
        if word:
            pass # TODO
        elif partial:
            query = '%' + query + '%'

    cur.execute('''
SELECT ent_seq
FROM entries
  NATURAL INNER JOIN %s
WHERE %s.%s %s ?
;'''
                % (table, table, field, operator),
                [query])

    res = []
    for row in cur.fetchall():
        res.append(row[0])
    return res

def guess_search(cur, conditions):
    '''Try many searches.

    conditions -- list of dictionaries.

    Each dictionary in *conditions is a set of keyword arguments for
    search_by() (including the mandatory arguments!).

    guess_search will try all in order, and return the first one with
    >0 results.
    '''

    for condition in conditions:
        res = search_by(cur, **condition)
        if len(res) > 0:
            return res


if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser()

    ap.add_argument('-k', '--by-kanji', action='store_const', dest='field', const='kanji', default='guess',
                    help="Search entry with kanji field matching query")

    ap.add_argument('-r', '--by-reading', action='store_const', dest='field', const='reading',
                    help="Search entry with reading field (in kana) matching query")

    ap.add_argument('-s', '--by-sense', action='store_const', dest='field', const='sense',
                    help="Search entry with sense field (English translation) matching query")


    ap.add_argument('--case-sensitive', '--sensitive', action='store_true',
                    help="Case-sensitive search (distinguish uppercase from lowercase)")

    ap.add_argument('-p', '--partial', action='store_true',
                    help="Search partial matches")

    ap.add_argument('-w', '--word', action='store_true',
                    help="Search partial matches, but only if query matches a whole word (FIXME: currently requires -x)")

    ap.add_argument('-x', '--regexp', action='store_true',
                    help="Regular expression search")

    ap.add_argument('query')

    # ap.add_argument('--db-compress',
    #                 action='store_true',
    #                 help='Compress myougiden database.  Uses less disk space, but queries are slower.')
    # ap.add_argument('--db-uncompress',
    #                 action='store_true',
    #                 help='Uncompress myougiden database.  Uses more disk space, but queries are faster.')

    args = ap.parse_args()


    # if args.db_compress:
    #     subprocess.call(['gzip', PATHS['database']])
    # elif args.db_uncompress:
    #     subprocess.call(['gzip', '-d', PATHS['database']])

    if not args.case_sensitive:
        if  re.search("[A-Z]", args.query):
            args.case_sensitive = True

    con, cur = opendb(case_sensitive=args.case_sensitive)

    if args.field != 'guess':
        entries = search_by(cur, **vars(args))
    else:
        args = vars(args)

        conditions = []

        args['field'] = 'kanji'
        conditions.append(args.copy())
        args['field'] = 'reading'
        conditions.append(args.copy())
        args['field'] = 'sense'
        conditions.append(args.copy())

        entries = guess_search(cur, conditions)

    for row in [fetch_entry(cur, ent_seq) for ent_seq in entries]:
        print(format_entry_tsv(*row))
