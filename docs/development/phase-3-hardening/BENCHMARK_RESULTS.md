# Output Rail Chunk Tuning Benchmark

> **Status**: Methodology defined. Actual benchmarking deferred to live-stack validation.
> **Defaults**: `OUTPUT_RAIL_CHUNK_SIZE=200`, `OUTPUT_RAIL_OVERLAP=50` (unchanged from Phase 2).

## Methodology

1. Prepare 10 representative agent responses (short, medium, long, with/without PII)
2. Test chunk sizes: 100, 150, 200 (current), 300, 500 approximate tokens (characters / 4)
3. Test overlap sizes: 25, 50 (current), 75, 100 approximate tokens
4. Measure: guardrail processing time per response, number of chunks, detection rate for embedded PII
5. For each combination, run 5 iterations and record median latency

## Test Scenarios

| Scenario | Description | Expected Behavior |
|---|---|---|
| Short (~100 tokens) | Single chunk at 200 | Should be safe at all sizes |
| Medium (~500 tokens) | 2-3 chunks at 200 | Check PII at chunk boundary |
| Long (~2000 tokens) | 10 chunks at 200 | Measure total latency |
| PII at boundary | Email/UUID at exact overlap zone | Must detect at all overlap sizes |
| Rapid PII | Short response with PII early | Caught at chunk 1 |

## Decision Tree

```
Detection rate at boundary >= 95%?
├── YES at current defaults (200/50) → Keep defaults
└── NO at 200/50 → Increase overlap to 75 or 100, re-test
    ├── YES at 200/75 → Update default
    └── NO → Decrease chunk size to 150, re-test

Median latency per response < 2s?
├── YES → Accept configuration
└── NO → Consider increasing chunk size or reducing LLM calls
```

## Note on Token Counting

The current `src/proxy/streaming.py` implementation uses an approximate character-to-token conversion (`_CHARS_PER_TOKEN = 4`), not real tokenizer-based counting. Benchmarks should measure against this approximation as-is.

## Results

*To be populated after live-stack benchmarking.*
