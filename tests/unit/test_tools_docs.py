import inspect

from tools.docs import search_docs


class TestSearchDocs:
    """Tests for search_docs tool (Phase 1 placeholder)."""

    def test_function_exists(self):
        """Verify the function exists and is callable."""
        assert callable(search_docs)

    def test_returns_string(self):
        """Verify the function returns a string."""
        result = search_docs("test query")
        assert isinstance(result, str)

    def test_includes_query_in_response(self):
        """Verify the response includes the search query."""
        result = search_docs("platform features")
        assert "platform features" in result

    def test_mentions_archival_memory_search(self):
        """Phase 1 implementation should guide users to archival_memory_search."""
        result = search_docs("test")
        assert "archival_memory_search" in result

    def test_accepts_query_parameter(self):
        """Verify the function accepts a query parameter."""
        sig = inspect.signature(search_docs)
        assert "query" in sig.parameters
        # With __future__ annotations, annotation is a string, not type
        assert sig.parameters["query"].annotation in (str, "str")
