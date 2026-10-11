"""Tests for RAG system utilities."""
import os
import sys
import json
import uuid
import shutil
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rag_utils
import ingest
from unified_search import deduplicate


class TestIsExcluded(unittest.TestCase):
    def test_excluded_extension(self):
        self.assertTrue(rag_utils.is_excluded('file.pdf'))
        self.assertTrue(rag_utils.is_excluded('notes.docx'))

    def test_excluded_filename(self):
        self.assertTrue(rag_utils.is_excluded('GEMINI.md'))
        self.assertTrue(rag_utils.is_excluded('MEMORY.md'))

    def test_excluded_dir(self):
        self.assertTrue(rag_utils.is_excluded('.git/config'))
        self.assertTrue(rag_utils.is_excluded('.obsidian/note.md'))
        self.assertTrue(rag_utils.is_excluded('venv/bin/python'))
        self.assertTrue(rag_utils.is_excluded('rag_system/query.py'))

    def test_hidden_file(self):
        self.assertTrue(rag_utils.is_excluded('.hidden.md'))

    def test_normal_markdown(self):
        self.assertFalse(rag_utils.is_excluded('Databases/PostgreSQL/overview.md'))
        self.assertFalse(rag_utils.is_excluded('notes/devops.md'))

    def test_empty_path(self):
        self.assertFalse(rag_utils.is_excluded(''))
        self.assertFalse(rag_utils.is_excluded(None))


class TestKeywordOverlap(unittest.TestCase):
    def test_full_overlap(self):
        score = rag_utils.keyword_overlap('postgresql database', 'postgresql database')
        self.assertEqual(score, 1.0)

    def test_partial_overlap(self):
        score = rag_utils.keyword_overlap('postgresql replication', 'postgresql database')
        self.assertEqual(score, 0.5)

    def test_no_overlap(self):
        score = rag_utils.keyword_overlap('python flask', 'postgresql database')
        self.assertEqual(score, 0.0)

    def test_empty_query(self):
        score = rag_utils.keyword_overlap('', 'some text')
        self.assertEqual(score, 0.0)

    def test_russian(self):
        score = rag_utils.keyword_overlap('база данных', 'база данных postgresql')
        self.assertGreater(score, 0.5)


class TestNormalizeWord(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(rag_utils.normalize_word('PostgreSQL'), 'postgresql')

    def test_special_chars(self):
        result = rag_utils.normalize_word('hello-world')
        self.assertIsInstance(result, str)

    def test_caching(self):
        w1 = rag_utils.normalize_word('PostgreSQL')
        w2 = rag_utils.normalize_word('PostgreSQL')
        self.assertEqual(w1, w2)


class TestGetDevice(unittest.TestCase):
    def test_returns_string(self):
        device = rag_utils.get_device()
        self.assertIn(device, ['cpu', 'cuda', 'mps'])


class TestGetFiles(unittest.TestCase):
    def test_returns_list_of_tuples(self):
        files = rag_utils.get_files()
        self.assertIsInstance(files, list)
        if files:
            path, rel = files[0]
            self.assertTrue(os.path.isabs(path))
            self.assertIsInstance(rel, str)


class TestConfig(unittest.TestCase):
    def test_engines_have_required_keys(self):
        required = {'dir', 'collection', 'model', 'chunk_size', 'chunk_overlap', 'label', 'batch_size', 'query_prefix', 'doc_prefix'}
        for name, cfg in rag_utils.ENGINES.items():
            with self.subTest(engine=name):
                self.assertTrue(required.issubset(cfg.keys()))

    def test_excluded_lists_are_lists(self):
        self.assertIsInstance(rag_utils.EXCLUDED_DIRS, list)
        self.assertIsInstance(rag_utils.EXCLUDED_FILES, list)
        self.assertIsInstance(rag_utils.EXCLUDED_EXTENSIONS, list)

    def test_new_constants_exist(self):
        self.assertIsInstance(rag_utils.HYBRID_EXTRA_K_OFFSET, int)
        self.assertIsInstance(rag_utils.MMR_COMPARE_DEFAULT_K, int)
        self.assertIsInstance(rag_utils.RERANKER_MAX_CHARS, int)
        self.assertIsInstance(rag_utils.HF_HUB_TIMEOUT, int)

    def test_bge_prefixes_different(self):
        bge = rag_utils.ENGINES.get("bge", {})
        self.assertNotEqual(bge.get("query_prefix", ""), bge.get("doc_prefix", ""))
        self.assertTrue(bge.get("doc_prefix", "").startswith("Represent this document"))

    def test_reranker_model_exists(self):
        self.assertIn("mmarco", rag_utils.RERANKER_MODEL)

    def test_make_chunk_id(self):
        cid = rag_utils.make_chunk_id("path/to/file.md", 0, "hello world")
        self.assertIn("path_to_file.md", cid)
        self.assertIn("0", cid)

    def test_make_chunk_id_stable(self):
        cid1 = rag_utils.make_chunk_id("f.md", 0, "content")
        cid2 = rag_utils.make_chunk_id("f.md", 0, "content")
        self.assertEqual(cid1, cid2)

    def test_make_chunk_id_changes_on_content(self):
        cid1 = rag_utils.make_chunk_id("f.md", 0, "content1")
        cid2 = rag_utils.make_chunk_id("f.md", 0, "content2")
        self.assertNotEqual(cid1, cid2)


class TestDeduplicate(unittest.TestCase):
    def setUp(self):
        self.deduplicate = deduplicate

    def test_removes_duplicates(self):
        results = [
            {'source': 'a.md', 'content': 'hello'},
            {'source': 'a.md', 'content': 'hello'},
            {'source': 'b.md', 'content': 'world'},
        ]
        unique = self.deduplicate(results)
        self.assertEqual(len(unique), 2)

    def test_empty_input(self):
        self.assertEqual(self.deduplicate([]), [])


class TestManifestAtomicity(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_script_dir = rag_utils.SCRIPT_DIR
        rag_utils.set_script_dir(self.tmpdir)
        import ingest
        self.orig_manifest = ingest.MANIFEST_FILE
        ingest.MANIFEST_FILE = os.path.join(self.tmpdir, "manifest.json")

    def tearDown(self):
        rag_utils.set_script_dir(self.orig_script_dir)
        import ingest
        ingest.MANIFEST_FILE = self.orig_manifest
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_load_roundtrip(self):
        import json
        from ingest import save_manifest, load_manifest, MANIFEST_FILE
        test_data = {"test_engine": {"files": {"test.md": {"mtime": 1.0, "chunk_ids": ["id1"]}}}}
        save_manifest(test_data)
        loaded = load_manifest()
        self.assertEqual(loaded, test_data)


class TestDocPrefixEmbeddings(unittest.TestCase):
    def setUp(self):
        class _MockEmbeddings:
            def embed_documents(self, texts):
                return [[len(t)] for t in texts]
            def embed_query(self, text):
                return [len(text)]
        self.mock = _MockEmbeddings()
        self.lock = threading.Lock()

    def test_doc_prefix_applied_to_embed_documents(self):
        wrapper = rag_utils._DocPrefixEmbeddings(self.mock, "PREFIX: ", self.lock)
        result = wrapper.embed_documents(["hello"])
        self.assertEqual(result, [[13]])

    def test_doc_prefix_not_applied_to_embed_query(self):
        wrapper = rag_utils._DocPrefixEmbeddings(self.mock, "PREFIX: ", self.lock)
        result = wrapper.embed_query("hello")
        self.assertEqual(result, [5])

    def test_multiple_texts(self):
        wrapper = rag_utils._DocPrefixEmbeddings(self.mock, "PRE: ", self.lock)
        result = wrapper.embed_documents(["a", "ab", "abc"])
        expected = [[6], [7], [8]]
        self.assertEqual(result, expected)


class TestGetEmbeddingsDocPrefix(unittest.TestCase):
    def setUp(self):
        self.mock_emb = unittest.mock.MagicMock()
        self.patcher = unittest.mock.patch(
            "langchain_huggingface.HuggingFaceEmbeddings",
            return_value=self.mock_emb,
        )
        self.patcher.start()
        rag_utils._clear_model_caches()

    def tearDown(self):
        self.patcher.stop()
        rag_utils._clear_model_caches()

    def test_get_embeddings_returns_wrapper_when_prefix_given(self):
        result = rag_utils.get_embeddings("fake-model", "cpu", doc_prefix="TEST: ")
        self.assertIsInstance(result, rag_utils._DocPrefixEmbeddings)

    def test_get_embeddings_returns_raw_when_no_prefix(self):
        result = rag_utils.get_embeddings("fake-model", "cpu", doc_prefix="")
        self.assertNotIsInstance(result, rag_utils._DocPrefixEmbeddings)


class TestBM25Scores(unittest.TestCase):
    def test_bm25_empty_query(self):
        scores = rag_utils.bm25_scores("", ["hello world"])
        self.assertEqual(scores, [0.0])

    def test_bm25_empty_texts(self):
        scores = rag_utils.bm25_scores("test", [])
        self.assertEqual(scores, [])

    def test_bm25_exact_match_highest(self):
        texts = ["apple banana", "apple banana cherry", "something else"]
        scores = rag_utils.bm25_scores("apple banana", texts)
        self.assertGreater(scores[0], scores[2])
        self.assertGreater(scores[1], scores[2])

    def test_bm25_no_match(self):
        scores = rag_utils.bm25_scores("zzzzz", ["hello world"])
        self.assertEqual(scores[0], 0.0)

    def test_bm25_russian(self):
        texts = ["база данных postgresql", "docker контейнеры"]
        scores = rag_utils.bm25_scores("база данных", texts)
        self.assertGreater(scores[0], scores[1])


class TestPerformSearchIntegration(unittest.TestCase):
    @unittest.mock.patch("rag_utils.load_qdrant")
    @unittest.mock.patch("rag_utils.get_reranker")
    @unittest.mock.patch("rag_utils.get_embeddings")
    @unittest.mock.patch("rag_utils.get_sparse_embedding_model")
    def test_search_returns_results(self, mock_sparse, mock_dense, mock_reranker, mock_load_qdrant):
        from unified_search import perform_search, bust_cache
        bust_cache()

        mock_reranker.return_value = None
        
        mock_dense.return_value.embed_query.return_value = [0.1, 0.2]
        
        mock_sparse_res = unittest.mock.MagicMock()
        mock_sparse_res.indices = unittest.mock.MagicMock(tolist=lambda: [1, 2])
        mock_sparse_res.values = unittest.mock.MagicMock(tolist=lambda: [0.5, 0.6])
        mock_sparse.return_value.embed.return_value = [mock_sparse_res]

        fake_point = unittest.mock.MagicMock()
        fake_point.payload = {"source": "test.md", "page_content": "test content about useradd and usermod"}
        fake_point.score = 0.5
        fake_point.vector = {"dense": [0.1, 0.2]}

        fake_result = unittest.mock.MagicMock()
        fake_result.points = [fake_point]

        fake_vs = unittest.mock.MagicMock()
        fake_vs.query_points.return_value = fake_result
        fake_cfg = {"query_prefix": "", "model": "fake", "dir": "/tmp", "collection": "test"}
        mock_load_qdrant.return_value = (fake_vs, fake_cfg)

        results = perform_search("unique_returns_test", engine_names=["bge"], top_k=5, use_rerank=False)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        self.assertIn("source", results[0])
        self.assertIn("content", results[0])
        self.assertIn("score", results[0])

    @unittest.mock.patch("rag_utils.load_qdrant")
    @unittest.mock.patch("rag_utils.get_reranker")
    @unittest.mock.patch("rag_utils.get_embeddings")
    @unittest.mock.patch("rag_utils.get_sparse_embedding_model")
    def test_search_deduplicates(self, mock_sparse, mock_dense, mock_reranker, mock_load_qdrant):
        from unified_search import perform_search, bust_cache
        bust_cache()

        mock_reranker.return_value = None

        mock_dense.return_value.embed_query.return_value = [0.1, 0.2]
        
        mock_sparse_res = unittest.mock.MagicMock()
        mock_sparse_res.indices = unittest.mock.MagicMock(tolist=lambda: [1, 2])
        mock_sparse_res.values = unittest.mock.MagicMock(tolist=lambda: [0.5, 0.6])
        mock_sparse.return_value.embed.return_value = [mock_sparse_res]

        fake_point1 = unittest.mock.MagicMock()
        fake_point1.payload = {"source": "test.md", "page_content": "duplicate content"}
        fake_point1.score = 0.3
        fake_point1.vector = {"dense": [0.1, 0.2]}
        
        fake_point2 = unittest.mock.MagicMock()
        fake_point2.payload = {"source": "test.md", "page_content": "duplicate content"}
        fake_point2.score = 0.5
        fake_point2.vector = {"dense": [0.1, 0.2]}

        fake_result = unittest.mock.MagicMock()
        fake_result.points = [fake_point1, fake_point2]

        fake_vs = unittest.mock.MagicMock()
        fake_vs.query_points.return_value = fake_result
        fake_cfg = {"query_prefix": "", "model": "fake", "dir": "/tmp", "collection": "test"}
        mock_load_qdrant.return_value = (fake_vs, fake_cfg)

        results = perform_search("unique_dedup_test", engine_names=["bge"], top_k=5, use_rerank=False)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["score"], 0.5)

    @unittest.mock.patch("rag_utils.load_qdrant")
    @unittest.mock.patch("rag_utils.get_reranker")
    @unittest.mock.patch("rag_utils.get_embeddings")
    @unittest.mock.patch("rag_utils.get_sparse_embedding_model")
    def test_search_empty_results(self, mock_sparse, mock_dense, mock_reranker, mock_load_qdrant):
        from unified_search import perform_search, bust_cache
        bust_cache()

        mock_reranker.return_value = None

        mock_dense.return_value.embed_query.return_value = [0.1, 0.2]
        
        mock_sparse_res = unittest.mock.MagicMock()
        mock_sparse_res.indices = unittest.mock.MagicMock(tolist=lambda: [1, 2])
        mock_sparse_res.values = unittest.mock.MagicMock(tolist=lambda: [0.5, 0.6])
        mock_sparse.return_value.embed.return_value = [mock_sparse_res]

        fake_result = unittest.mock.MagicMock()
        fake_result.points = []

        fake_vs = unittest.mock.MagicMock()
        fake_vs.query_points.return_value = fake_result
        fake_cfg = {"query_prefix": "", "model": "fake", "dir": "/tmp", "collection": "test"}
        mock_load_qdrant.return_value = (fake_vs, fake_cfg)

        results = perform_search("unique_empty_test", engine_names=["bge"], top_k=5, use_rerank=False)
        self.assertEqual(results, [])


class TestMMRDiversify(unittest.TestCase):
    def setUp(self):
        self.results = [
            {"source": "a.md", "content": "python programming language", "score": 0.9},
            {"source": "b.md", "content": "java programming language", "score": 0.8},
            {"source": "c.md", "content": "python django web framework", "score": 0.7},
            {"source": "d.md", "content": "rust systems programming", "score": 0.6},
        ]

    def test_returns_all_when_less_than_k(self):
        from unified_search import mmr_diversify
        res = mmr_diversify(self.results, "python", top_k=10)
        self.assertEqual(len(res), 4)

    def test_returns_k_results(self):
        from unified_search import mmr_diversify
        res = mmr_diversify(self.results, "python", top_k=2)
        self.assertEqual(len(res), 2)

    def test_empty_results(self):
        from unified_search import mmr_diversify
        res = mmr_diversify([], "query", top_k=5)
        self.assertEqual(res, [])

    def test_preserves_top_relevant(self):
        from unified_search import mmr_diversify
        res = mmr_diversify(self.results, "python", top_k=1)
        self.assertEqual(res[0]["score"], 0.9)

    def test_single_result(self):
        from unified_search import mmr_diversify
        res = mmr_diversify([self.results[0]], "python", top_k=5)
        self.assertEqual(len(res), 1)

    def test_with_emb_matrix(self):
        from unified_search import mmr_diversify
        emb_matrix = [
            [1.0, 0.3, 0.8, 0.1],
            [0.3, 1.0, 0.2, 0.4],
            [0.8, 0.2, 1.0, 0.1],
            [0.1, 0.4, 0.1, 1.0],
        ]
        res = mmr_diversify(self.results, "python", top_k=3, emb_matrix=emb_matrix)
        self.assertEqual(len(res), 3)

    def test_rerank_score_used(self):
        from unified_search import mmr_diversify
        results = [
            {"source": "a.md", "content": "hello world", "rerank_score": 0.9},
            {"source": "b.md", "content": "hello world different", "rerank_score": 0.5},
        ]
        res = mmr_diversify(results, "hello", top_k=2)
        self.assertEqual(res[0]["rerank_score"], 0.9)


class TestReranker(unittest.TestCase):
    def test_reranker_none_returns_original(self):
        from unified_search import rerank
        results = [{"source": "a.md", "content": "test", "score": 0.5}]
        res = rerank("query", results, reranker=None)
        self.assertEqual(res, results)

    def test_reranker_empty_results(self):
        from unified_search import rerank
        res = rerank("query", [], unittest.mock.MagicMock())
        self.assertEqual(res, [])

    def test_rerank_sets_scores(self):
        from unified_search import rerank

        class FakeReranker:
            def predict(self, pairs):
                return [0.9, 0.1]

        results = [
            {"source": "a.md", "content": "relevant doc about python", "score": 0.5},
            {"source": "b.md", "content": "unrelated note", "score": 0.5},
        ]
        res = rerank("python", results, FakeReranker())
        self.assertIn("rerank_score", res[0])
        self.assertEqual(res[0]["rerank_score"], 0.9)

    def test_rerank_sorts_by_score(self):
        from unified_search import rerank

        class FakeReranker:
            def predict(self, pairs):
                return [0.1, 0.9]

        results = [
            {"source": "a.md", "content": "low relevance", "score": 0.5},
            {"source": "b.md", "content": "high relevance", "score": 0.5},
        ]
        res = rerank("python", results, FakeReranker())
        self.assertEqual(res[0]["source"], "b.md")

    def test_rerank_error_handling(self):
        from unified_search import rerank

        class BrokenReranker:
            def predict(self, pairs):
                raise RuntimeError("model failure")

        results = [{"source": "a.md", "content": "test", "score": 0.5}]
        res = rerank("query", results, BrokenReranker())
        self.assertEqual(len(res), 1)

    @unittest.mock.patch("unified_search.rag_utils.RERANKER_MAX_CHARS", 10)
    def test_rerank_truncates_content(self):
        from unified_search import rerank

        class FakeReranker:
            def predict(self, pairs):
                self.seen = pairs
                return [0.5]

        results = [{"source": "a.md", "content": "x" * 100, "score": 0.5}]
        reranker = FakeReranker()
        rerank("query", results, reranker)
        self.assertLessEqual(len(reranker.seen[0][1]), 10)


class TestScoreThreshold(unittest.TestCase):
    def test_none_threshold_keeps_all(self):
        from unified_search import apply_score_threshold
        results = [{"rerank_score": -5.0}, {"rerank_score": 3.0}]
        res = apply_score_threshold(results, None)
        self.assertEqual(len(res), 2)

    def test_filters_below_threshold(self):
        from unified_search import apply_score_threshold
        results = [
            {"rerank_score": 3.0},
            {"rerank_score": -2.9},
            {"rerank_score": -3.1},
            {"rerank_score": 0.0},
        ]
        res = apply_score_threshold(results, -3.0)
        self.assertEqual(len(res), 3)
        for r in res:
            self.assertGreaterEqual(r["rerank_score"], -3.0)

    def test_uses_score_when_no_rerank(self):
        from unified_search import apply_score_threshold
        results = [{"score": 0.01}, {"score": 0.02}]
        res = apply_score_threshold(results, -3.0)
        self.assertEqual(len(res), 2)

    def test_threshold_constant_is_float(self):
        self.assertIsInstance(rag_utils.RERANK_SCORE_THRESHOLD, float)


class TestIngestHelpers(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_script_dir = rag_utils.SCRIPT_DIR
        rag_utils.set_script_dir(self.tmpdir)
        self.ingest = __import__("ingest")
        self.orig_manifest_file = self.ingest.MANIFEST_FILE
        self.ingest.MANIFEST_FILE = os.path.join(self.tmpdir, "manifest.json")

    def tearDown(self):
        rag_utils.set_script_dir(self.orig_script_dir)
        self.ingest.MANIFEST_FILE = self.orig_manifest_file
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_file(self, path: str, content: str = "content") -> str:
        full = os.path.join(self.tmpdir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        return full

    def test_load_manifest_not_exists(self):
        self.ingest.MANIFEST_FILE = os.path.join(self.tmpdir, "no_such_file.json")
        result = self.ingest.load_manifest()
        self.assertEqual(result, {})

    def test_save_manifest_creates_file(self):
        mf = os.path.join(self.tmpdir, "manifest.json")
        self.ingest.MANIFEST_FILE = mf
        data = {"test": {"files": {"a.md": {"mtime": 1.0, "chunk_ids": ["id1"]}}}}
        self.ingest.save_manifest(data)
        loaded = self.ingest.load_manifest()
        self.assertEqual(loaded, data)
        self.assertTrue(os.path.exists(mf))

    def test_get_changed_files_new_db(self):
        db_dir = os.path.join(self.tmpdir, "qdrant_db")
        os.makedirs(db_dir)
        files = [("/tmp/a.md", "a.md"), ("/tmp/b.md", "b.md")]
        changed, deleted, manifest, es = self.ingest.get_changed_files("e5", files, force=False, db_dir=db_dir)
        self.assertEqual(len(changed), 2)
        self.assertEqual(len(deleted), 0)

    def _write_manifest(self, engine: str, data: dict) -> None:
        mf_path = os.path.join(self.tmpdir, "manifest.json")
        full = {engine: {"files": data}}
        with open(mf_path, "w") as f:
            json.dump(full, f)

    def test_get_changed_files_force(self):
        fpath = self._make_file("a.md", "data")
        self._write_manifest("e5", {"a.md": {"mtime": 1.0, "chunk_ids": ["id1"]}})
        db_dir = os.path.join(self.tmpdir, "qdrant_db")
        os.makedirs(db_dir)
        files = [(fpath, "a.md")]
        changed, deleted, manifest, es = self.ingest.get_changed_files("e5", files, force=True, db_dir=db_dir)
        self.assertEqual(len(changed), 1)

    def test_get_changed_files_no_changes(self):
        fpath = self._make_file("test.md", "hello")
        db_dir = os.path.join(self.tmpdir, "qdrant_db")
        os.makedirs(db_dir)
        self._write_manifest("e5", {"test.md": {"mtime": os.path.getmtime(fpath), "chunk_ids": ["id1"]}})
        files = [(fpath, "test.md")]
        changed, deleted, manifest, es = self.ingest.get_changed_files("e5", files, force=False, db_dir=db_dir)
        self.assertEqual(len(changed), 0)
        self.assertEqual(len(deleted), 0)

    def test_get_changed_files_deleted(self):
        self._write_manifest("e5", {"old.md": {"mtime": 1.0, "chunk_ids": ["id1"]}})
        db_dir = os.path.join(self.tmpdir, "qdrant_db")
        os.makedirs(db_dir)
        files = []
        changed, deleted, manifest, es = self.ingest.get_changed_files("e5", files, force=False, db_dir=db_dir)
        self.assertEqual(len(changed), 0)
        self.assertEqual(len(deleted), 1)
        self.assertIn("old.md", deleted)

    def test_process_files_basic(self):
        header_splitter, text_splitter = self.ingest.build_text_splitters({"chunk_size": 500, "chunk_overlap": 50})
        fpath = self._make_file("test.md", "# Section 1\n\nHello world\n\n## Sub\n\nMore content")
        docs, info = self.ingest.process_files([(fpath, "test.md")], header_splitter, text_splitter)
        self.assertGreater(len(docs), 0)
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0][0], "test.md")

    def test_process_files_empty_file(self):
        header_splitter, text_splitter = self.ingest.build_text_splitters({"chunk_size": 500, "chunk_overlap": 50})
        fpath = self._make_file("empty.md", "")
        docs, info = self.ingest.process_files([(fpath, "empty.md")], header_splitter, text_splitter)
        self.assertEqual(len(docs), 0)

    def test_process_files_error_handling(self):
        header_splitter, text_splitter = self.ingest.build_text_splitters({"chunk_size": 500, "chunk_overlap": 50})
        docs, info = self.ingest.process_files([("/nonexistent/file.md", "file.md")], header_splitter, text_splitter)
        self.assertEqual(len(docs), 0)

    def test_revalidate_changed_removes_valid(self):
        fpath = self._make_file("valid.md", "same mtime")
        mtime = os.path.getmtime(fpath)
        changed = [(fpath, "valid.md")]
        fresh = {"valid.md": {"mtime": mtime}}
        result = self.ingest._revalidate_changed(changed, fresh)
        self.assertEqual(len(result), 0)

    def test_revalidate_changed_keeps_newer(self):
        fpath = self._make_file("newer.md", "data")
        changed = [(fpath, "newer.md")]
        fresh = {"newer.md": {"mtime": 1.0}}
        result = self.ingest._revalidate_changed(changed, fresh)
        self.assertEqual(len(result), 1)

    def test_revalidate_deleted(self):
        result = self.ingest._revalidate_deleted(["a.md", "b.md"], {"a.md": {"mtime": 1.0}})
        self.assertEqual(result, ["a.md"])

    def test_revalidate_deleted_all_fresh(self):
        result = self.ingest._revalidate_deleted(["a.md"], {"a.md": {"mtime": 1.0}})
        self.assertEqual(result, ["a.md"])

    def test_revalidate_deleted_all_stale(self):
        result = self.ingest._revalidate_deleted(["a.md", "b.md"], {})
        self.assertEqual(result, [])


class TestUpdateManifest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_manifest = ingest.MANIFEST_FILE
        self.orig_lock = ingest.MANIFEST_LOCK_FILE
        ingest.MANIFEST_FILE = os.path.join(self.tmpdir, "manifest.json")
        ingest.MANIFEST_LOCK_FILE = ingest.MANIFEST_FILE + ".lock"

    def tearDown(self):
        ingest.MANIFEST_FILE = self.orig_manifest
        ingest.MANIFEST_LOCK_FILE = self.orig_lock
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_manifest(self, data):
        with open(ingest.MANIFEST_FILE, "w") as f:
            json.dump(data, f)

    def _deleted_uuids(self, fake_client):
        out = set()
        for selector in fake_client.deleted:
            out.update(selector.points)
        return out

    def test_reingest_same_ids_does_not_delete_points(self):
        self._write_manifest({"e5": {"files": {"a.md": {"mtime": 1.0, "chunk_ids": ["x1", "x2"]}}}})
        fake = FakeQdrantClient()
        ingest._update_manifest(
            "e5", fake, "col",
            changed=[("/p/a.md", "a.md")],
            deleted=[],
            file_chunk_info=[("a.md", ["x1", "x2"], 2.0)],
        )
        self.assertEqual(fake.deleted, [], "must not delete freshly re-uploaded ids")
        manifest = ingest.load_manifest()
        self.assertEqual(manifest["e5"]["files"]["a.md"], {"mtime": 2.0, "chunk_ids": ["x1", "x2"]})

    def test_reingest_changed_content_deletes_only_old_ids(self):
        self._write_manifest({"e5": {"files": {"a.md": {"mtime": 1.0, "chunk_ids": ["old1", "old2"]}}}})
        fake = FakeQdrantClient()
        ingest._update_manifest(
            "e5", fake, "col",
            changed=[("/p/a.md", "a.md")],
            deleted=[],
            file_chunk_info=[("a.md", ["new1", "new2"], 2.0)],
        )
        expected = {str(uuid.uuid5(uuid.NAMESPACE_URL, i)) for i in ["old1", "old2"]}
        self.assertEqual(self._deleted_uuids(fake), expected)

    def test_deleted_file_chunks_removed(self):
        self._write_manifest({"e5": {"files": {"c.md": {"mtime": 1.0, "chunk_ids": ["c1"]}}}})
        fake = FakeQdrantClient()
        ingest._update_manifest("e5", fake, "col", changed=[], deleted=["c.md"], file_chunk_info=[])
        expected = {str(uuid.uuid5(uuid.NAMESPACE_URL, "c1"))}
        self.assertEqual(self._deleted_uuids(fake), expected)
        manifest = ingest.load_manifest()
        self.assertNotIn("c.md", manifest["e5"]["files"])


class FakeQdrantClient:
    def __init__(self):
        self.deleted = []

    def delete(self, collection_name, points_selector):
        self.deleted.append(points_selector)


class TestDeleteSourcePoints(unittest.TestCase):
    def setUp(self):
        self.ingest = __import__("ingest")

    class _ScrollClient:
        def __init__(self, points):
            self.points = points
            self.deleted_ids = []
            self.used_filters = []

        class _Record:
            def __init__(self, pid):
                self.id = pid

        def scroll(self, collection_name, limit, with_payload, with_vectors, offset, scroll_filter):
            self.used_filters.append(scroll_filter)
            start = 0 if offset is None else int(offset)
            page = [self._Record(p["id"]) for p in self.points[start:start + limit]]
            nxt = start + limit if start + limit < len(self.points) else None
            return page, nxt

        def delete(self, collection_name, points_selector):
            self.deleted_ids.extend(points_selector.points)

    def test_deletes_all_matching_points(self):
        client = self._ScrollClient([{"id": "1"}, {"id": "2"}, {"id": "3"}])
        n = self.ingest._delete_source_points(client, "col", "stale.md")
        self.assertEqual(n, 3)
        self.assertEqual(sorted(client.deleted_ids), ["1", "2", "3"])

    def test_multiple_pages(self):
        client = self._ScrollClient([{"id": str(i)} for i in range(25)])
        n = self.ingest._delete_source_points(client, "col", "stale.md")
        self.assertEqual(n, 25)
        self.assertEqual(len(client.deleted_ids), 25)

    def test_empty_collection(self):
        client = self._ScrollClient([])
        n = self.ingest._delete_source_points(client, "col", "stale.md")
        self.assertEqual(n, 0)
        self.assertEqual(client.deleted_ids, [])

    def test_uses_match_filter_for_source(self):
        client = self._ScrollClient([{"id": "1"}])
        self.ingest._delete_source_points(client, "col", "stale.md")
        cond = client.used_filters[0].must[0]
        self.assertEqual(cond.match.value, "stale.md")

    def test_uses_is_empty_filter_for_null_source(self):
        import qdrant_client.http.models as qmodels
        client = self._ScrollClient([{"id": "1"}])
        self.ingest._delete_source_points(client, "col", "<none>", null_source=True)
        cond = client.used_filters[0].must[0]
        self.assertIsInstance(cond, qmodels.IsEmptyCondition)


class TestComputeCosineSimMatrix(unittest.TestCase):
    def test_empty_input(self):
        result = rag_utils.compute_cosine_sim_matrix([])
        self.assertEqual(result, [])

    def test_single_vector(self):
        result = rag_utils.compute_cosine_sim_matrix([[1.0, 0.0]])
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0][0], 1.0)

    def test_identical_vectors(self):
        result = rag_utils.compute_cosine_sim_matrix([[1.0, 0.0], [1.0, 0.0]])
        self.assertAlmostEqual(result[0][1], 1.0)
        self.assertAlmostEqual(result[1][0], 1.0)

    def test_orthogonal_vectors(self):
        result = rag_utils.compute_cosine_sim_matrix([[1.0, 0.0], [0.0, 1.0]])
        self.assertAlmostEqual(result[0][1], 0.0, places=6)
        self.assertAlmostEqual(result[1][0], 0.0, places=6)


class TestConfigLoading(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_cfg_path = rag_utils._CFG_PATH
        rag_utils._CFG_PATH = os.path.join(self.tmpdir, "config.yaml")

    def tearDown(self):
        rag_utils._CFG_PATH = self.orig_cfg_path
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_config_no_file(self):
        result = rag_utils._load_config()
        self.assertIn("engines", result)
        self.assertIn("excluded_dirs", result)
        self.assertIn("excluded_files", result)

    def test_load_config_bad_yaml(self):
        with open(rag_utils._CFG_PATH, "w") as f:
            f.write("{bad: yaml: unclosed")
        result = rag_utils._load_config()
        self.assertIn("engines", result)

    def test_load_config_custom_engine(self):
        cfg = {
            "engines": {
                "test_engine": {
                    "dir": "/tmp/qdrant_test",
                    "collection": "test_coll",
                    "model": "test-model",
                    "chunk_size": 500,
                    "chunk_overlap": 50,
                    "batch_size": 10,
                    "label": "Test",
                    "query_prefix": "q: ",
                    "doc_prefix": "d: ",
                }
            }
        }
        import yaml
        with open(rag_utils._CFG_PATH, "w") as f:
            yaml.dump(cfg, f)
        result = rag_utils._load_config()
        self.assertIn("test_engine", result["engines"])
        self.assertEqual(result["engines"]["test_engine"]["collection"], "test_coll")


class TestHybridSearch(unittest.TestCase):
    @unittest.mock.patch("rag_utils.get_embeddings")
    @unittest.mock.patch("rag_utils.get_sparse_embedding_model")
    def test_hybrid_search_no_results(self, mock_sparse, mock_dense):
        from unified_search import hybrid_search
        mock_dense.return_value.embed_query.return_value = [0.1, 0.2]

        mock_sparse_res = unittest.mock.MagicMock()
        mock_sparse_res.indices = unittest.mock.MagicMock(tolist=lambda: [1, 2])
        mock_sparse_res.values = unittest.mock.MagicMock(tolist=lambda: [0.5, 0.6])
        mock_sparse.return_value.embed.return_value = [mock_sparse_res]

        fake_result = unittest.mock.MagicMock()
        fake_result.points = []

        fake_vs = unittest.mock.MagicMock()
        fake_vs.query_points.return_value = fake_result
        fake_cfg = {"query_prefix": "", "model": "fake", "dir": "/tmp", "collection": "test", "doc_prefix": ""}

        results = hybrid_search("bge", "test query", 10, fake_vs, fake_cfg)
        self.assertEqual(results, [])

    @unittest.mock.patch("rag_utils.get_embeddings")
    @unittest.mock.patch("rag_utils.get_sparse_embedding_model")
    def test_hybrid_search_filters_excluded(self, mock_sparse, mock_dense):
        from unified_search import hybrid_search
        mock_dense.return_value.embed_query.return_value = [0.1, 0.2]

        mock_sparse_res = unittest.mock.MagicMock()
        mock_sparse_res.indices = unittest.mock.MagicMock(tolist=lambda: [1, 2])
        mock_sparse_res.values = unittest.mock.MagicMock(tolist=lambda: [0.5, 0.6])
        mock_sparse.return_value.embed.return_value = [mock_sparse_res]

        fake_point = unittest.mock.MagicMock()
        fake_point.payload = {"source": "GEMINI.md", "page_content": "excluded content"}
        fake_point.score = 0.9
        fake_point.vector = {"dense": [0.1, 0.2]}

        fake_result = unittest.mock.MagicMock()
        fake_result.points = [fake_point]

        fake_vs = unittest.mock.MagicMock()
        fake_vs.query_points.return_value = fake_result
        fake_cfg = {"query_prefix": "", "model": "fake", "dir": "/tmp", "collection": "test", "doc_prefix": ""}

        results = hybrid_search("bge", "test", 10, fake_vs, fake_cfg)
        self.assertEqual(len(results), 0)


class TestManifestLock(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.lock_path = os.path.join(self.tmpdir, "test.lock")
        import ingest
        self.ManifestLock = ingest._ManifestLock

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_lock_acquire_release(self):
        lock = self.ManifestLock(self.lock_path)
        with lock:
            self.assertTrue(os.path.exists(self.lock_path))
        self.assertIsNone(lock.fd)

    def test_lock_serializes(self):
        results = []
        def worker():
            with self.ManifestLock(self.lock_path):
                results.append(1)
        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual(len(results), 2)


class TestBustCache(unittest.TestCase):
    def test_bust_cache_clears(self):
        import unified_search
        v = unified_search._SEARCH_CACHE_VERSION
        unified_search._SEARCH_CACHE["key"] = (1.0, ["data"])
        unified_search.bust_cache()
        self.assertEqual(len(unified_search._SEARCH_CACHE), 0)
        self.assertEqual(unified_search._SEARCH_CACHE_VERSION, v + 1)


class TestVenvReexec(unittest.TestCase):
    def test_venv_check_present(self):
        import _venv_check
        self.assertTrue(hasattr(_venv_check, "_VENV_PYTHON"))
        self.assertTrue(os.path.exists(_venv_check._VENV_PYTHON))


if __name__ == '__main__':
    unittest.main()
