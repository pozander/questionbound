import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import openalex_pearl_search as pearl


def book(n, refs=()):
    return dict(id=f'https://openalex.org/W{n}', type='book', display_name=f'Book {n}',
                referenced_works=[f'https://openalex.org/W{x}' for x in refs])


def page(records, count=None, cursor=None):
    return dict(results=records, meta=dict(count=len(records) if count is None else count, next_cursor=cursor))


class PearlTests(unittest.TestCase):
    def test_plan_and_validation(self):
        p = pearl.plan(['https://openalex.org/W2', 'W1', 'w2'], 'both', 500, 30)
        self.assertEqual(p['seeds'], ['W1', 'W2'])
        self.assertEqual(p['queries']['backward']['filter'], 'type:book,cited_by:W1|W2')
        self.assertEqual(p['queries']['forward']['filter'], 'type:book,cites:W1|W2')
        for seeds, limit in [(['not-an-id'], 1), (['W1'], 0)]:
            with self.assertRaises(ValueError):
                pearl.plan(seeds, 'both', limit, 30)

    def test_both_directions_dedupe_and_edges(self):
        get = Mock(side_effect=[book(1, [3]), book(2, [3]),
                                page([book(3, [1,2])]), page([book(3, [1,2])])])
        works, edges, progress = {}, set(), {}
        pearl.collect(pearl.plan(['W1','W2'], 'both', 500, 30), get, works, edges, progress)
        self.assertEqual(list(works), ['W3'])
        self.assertEqual(len(edges), 4)
        self.assertTrue(all(x['complete'] for x in progress.values()))

    def test_pagination_cap(self):
        get = Mock(side_effect=[book(1), page([book(2)], 3, 'next'), page([book(3)], 3, 'last')])
        works, edges, progress = {}, set(), {}
        pearl.collect(pearl.plan(['W1'], 'forward', 2, 30), get, works, edges, progress)
        self.assertTrue(progress['forward']['capped'])
        self.assertFalse(progress['forward']['complete'])
        self.assertEqual(get.call_args.args[1]['cursor'], 'next')
        self.assertIn(('', 'forward', 'W2', 'query_match_only_seed_unresolved'), edges)

    def test_empty_and_nonbook(self):
        pearl.collect(pearl.plan(['W1'], 'forward', 2, 30), Mock(side_effect=[book(1), page([])]), {}, set(), {})
        bad = book(2)
        bad['type'] = 'article'
        with self.assertRaises(RuntimeError):
            pearl.collect(pearl.plan(['W1'], 'forward', 2, 30), Mock(side_effect=[book(1), page([bad])]), {}, set(), {})

    def test_dry_run_has_no_network(self):
        with patch.object(pearl.requests, 'get', side_effect=AssertionError('network')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pearl.main(['--seed', 'W1', '--dry-run']), 0)

    def test_request_ceiling_and_secret_sanitization(self):
        with tempfile.TemporaryDirectory() as d:
            client = pearl.Client(Path(d), 'SECRET-KEY', 1)
            with patch.object(pearl.requests, 'get', side_effect=pearl.requests.RequestException('URL?api_key=SECRET-KEY')):
                with self.assertRaisesRegex(RuntimeError, 'Network request failed'):
                    client.get(pearl.API, {'filter': 'type:book'})
            self.assertNotIn('SECRET-KEY', ''.join(p.read_text() for p in Path(d).iterdir()))
            with self.assertRaisesRegex(RuntimeError, 'ceiling'):
                client.get(pearl.API, {})

    def test_raw_provenance_export_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            response = Mock(status_code=200, content=json.dumps(book(1)).encode())
            with patch.object(pearl.requests, 'get', return_value=response):
                pearl.Client(root, 'SECRET-KEY', 1).get(pearl.API, {})
            self.assertTrue((root/'request-001.raw.json').exists())
            self.assertIn('sha256', json.loads((root/'request-001.json').read_text()))
            pearl.export(root, {'W2': book(2)}, {('W1','forward','W2','reference_list')})
            self.assertIn('@book', (root/'books.bib').read_text())
            self.assertIn('W2', (root/'citation-edges.csv').read_text())
            brief = root/'brief.txt'
            brief.write_text('Test fixture, not research approval.')
            with patch.dict(pearl.os.environ, {'OPENALEX_API_KEY': 'SECRET-KEY'}), patch.object(pearl.requests,'get',side_effect=AssertionError('network')):
                with self.assertRaises(FileExistsError):
                    pearl.main(['--seed','W1','--brief',str(brief),'--output-dir',str(root)])


if __name__ == '__main__':
    unittest.main()
