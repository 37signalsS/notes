"""Tests for RAG system utilities."""
import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rag_utils
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

    def test_rrf_constants(self):
        self.assertIsInstance(rag_utils.RRF_K, int)
        self.assertIsInstance(rag_utils.RRF_DENSE_WEIGHT, int)
        self.assertIsInstance(rag_utils.RRF_KEYWORD_WEIGHT, int)

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
        rag_utils.SCRIPT_DIR = self.tmpdir
        import ingest
        self.orig_manifest = ingest.MANIFEST_FILE
        ingest.MANIFEST_FILE = os.path.join(self.tmpdir, "manifest.json")

    def tearDown(self):
        rag_utils.SCRIPT_DIR = self.orig_script_dir
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

    def test_doc_prefix_applied_to_embed_documents(self):
        wrapper = rag_utils._DocPrefixEmbeddings(self.mock, "PREFIX: ")
        result = wrapper.embed_documents(["hello"])
        self.assertEqual(result, [[13]])

    def test_doc_prefix_not_applied_to_embed_query(self):
        wrapper = rag_utils._DocPrefixEmbeddings(self.mock, "PREFIX: ")
        result = wrapper.embed_query("hello")
        self.assertEqual(result, [5])

    def test_multiple_texts(self):
        wrapper = rag_utils._DocPrefixEmbeddings(self.mock, "PRE: ")
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
        rag_utils._load_embedding_model.cache_clear()

    def tearDown(self):
        self.patcher.stop()
        rag_utils._load_embedding_model.cache_clear()

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
    @unittest.mock.patch("rag_utils.load_chroma")
    @unittest.mock.patch("rag_utils.get_reranker")
    def test_search_returns_results(self, mock_reranker, mock_load_chroma):
        from unified_search import perform_search, bust_cache
        bust_cache()

        mock_reranker.return_value = None

        fake_doc = unittest.mock.MagicMock()
        fake_doc.metadata = {"source": "test.md"}
        fake_doc.page_content = "test content about useradd and usermod"

        fake_vs = unittest.mock.MagicMock()
        fake_vs.similarity_search_with_score.return_value = [(fake_doc, 0.5)]
        fake_cfg = {"query_prefix": "", "model": "fake", "dir": "/tmp", "collection": "test"}
        mock_load_chroma.return_value = (fake_vs, fake_cfg)

        results = perform_search("unique_returns_test", engine_names=["bge"], top_k=5, use_rerank=False)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        self.assertIn("source", results[0])
        self.assertIn("content", results[0])
        self.assertIn("score", results[0])

    @unittest.mock.patch("rag_utils.load_chroma")
    @unittest.mock.patch("rag_utils.get_reranker")
    def test_search_deduplicates(self, mock_reranker, mock_load_chroma):
        from unified_search import perform_search, bust_cache
        bust_cache()

        mock_reranker.return_value = None

        fake_doc = unittest.mock.MagicMock()
        fake_doc.metadata = {"source": "test.md"}
        fake_doc.page_content = "duplicate content"

        fake_vs = unittest.mock.MagicMock()
        fake_vs.similarity_search_with_score.return_value = [(fake_doc, 0.3), (fake_doc, 0.5)]
        fake_cfg = {"query_prefix": "", "model": "fake", "dir": "/tmp", "collection": "test"}
        mock_load_chroma.return_value = (fake_vs, fake_cfg)

        results = perform_search("unique_dedup_test", engine_names=["bge"], top_k=5, use_rerank=False)
        self.assertEqual(len(results), 1)

    @unittest.mock.patch("rag_utils.load_chroma")
    @unittest.mock.patch("rag_utils.get_reranker")
    def test_search_empty_results(self, mock_reranker, mock_load_chroma):
        from unified_search import perform_search, bust_cache
        bust_cache()

        mock_reranker.return_value = None

        fake_vs = unittest.mock.MagicMock()
        fake_vs.similarity_search_with_score.return_value = []
        fake_cfg = {"query_prefix": "", "model": "fake", "dir": "/tmp", "collection": "test"}
        mock_load_chroma.return_value = (fake_vs, fake_cfg)

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


class TestIngestHelpers(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_script_dir = rag_utils.SCRIPT_DIR
        rag_utils.SCRIPT_DIR = self.tmpdir
        self.ingest = __import__("ingest")
        self.orig_manifest_file = self.ingest.MANIFEST_FILE
        self.ingest.MANIFEST_FILE = os.path.join(self.tmpdir, "manifest.json")

    def tearDown(self):
        rag_utils.SCRIPT_DIR = self.orig_script_dir
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
        db_dir = os.path.join(self.tmpdir, "chroma_db")
        os.makedirs(db_dir)
        files = [("/tmp/a.md", "a.md"), ("/tmp/b.md", "b.md")]
        changed, deleted, manifest, es, fm = self.ingest.get_changed_files("mpnet", files, force=False, db_dir=db_dir)
        self.assertEqual(len(changed), 2)
        self.assertEqual(len(deleted), 0)

    def _write_manifest(self, engine: str, data: dict) -> None:
        mf_path = os.path.join(self.tmpdir, "manifest.json")
        full = {engine: {"files": data}}
        with open(mf_path, "w") as f:
            json.dump(full, f)

    def test_get_changed_files_force(self):
        fpath = self._make_file("a.md", "data")
        self._write_manifest("mpnet", {"a.md": {"mtime": 1.0, "chunk_ids": ["id1"]}})
        db_dir = os.path.join(self.tmpdir, "chroma_db")
        os.makedirs(db_dir)
        files = [(fpath, "a.md")]
        changed, deleted, manifest, es, fm = self.ingest.get_changed_files("mpnet", files, force=True, db_dir=db_dir)
        self.assertEqual(len(changed), 1)

    def test_get_changed_files_no_changes(self):
        fpath = self._make_file("test.md", "hello")
        db_dir = os.path.join(self.tmpdir, "chroma_db")
        os.makedirs(db_dir)
        self._write_manifest("mpnet", {"test.md": {"mtime": os.path.getmtime(fpath), "chunk_ids": ["id1"]}})
        files = [(fpath, "test.md")]
        changed, deleted, manifest, es, fm = self.ingest.get_changed_files("mpnet", files, force=False, db_dir=db_dir)
        self.assertEqual(len(changed), 0)
        self.assertEqual(len(deleted), 0)

    def test_get_changed_files_deleted(self):
        self._write_manifest("mpnet", {"old.md": {"mtime": 1.0, "chunk_ids": ["id1"]}})
        db_dir = os.path.join(self.tmpdir, "chroma_db")
        os.makedirs(db_dir)
        files = []
        changed, deleted, manifest, es, fm = self.ingest.get_changed_files("mpnet", files, force=False, db_dir=db_dir)
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

    def test_delete_chunks_empty(self):
        mock_vs = unittest.mock.MagicMock()
        self.ingest.delete_chunks(mock_vs, [])
        mock_vs.delete.assert_not_called()

    def test_delete_chunks_with_ids(self):
        mock_vs = unittest.mock.MagicMock()
        self.ingest.delete_chunks(mock_vs, ["id1", "id2"])
        mock_vs.delete.assert_called_once_with(["id1", "id2"])

    def test_delete_chunks_none_vectorstore(self):
        self.ingest.delete_chunks(None, ["id1"])


class TestVenvReexec(unittest.TestCase):
    def test_venv_check_present(self):
        import unified_search
        self.assertTrue(hasattr(unified_search, "_VENV_PYTHON"))
        self.assertTrue(os.path.exists(unified_search._VENV_PYTHON))


if __name__ == '__main__':
    unittest.main()
