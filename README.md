# Gene Autoannotator

## Introduction / Purpose

An application that uses LLMs to summarize published literature on supplied genes into specified fields, in order to automate the curation of gene annotations.

## High Level Overview:

1. **Input:** Gene identifier (locus or name).

2. **Paper Retrieval:** Query PubMed Central to obtain relevant research articles.

3. **Section Extraction:** Extract the abstract, results, and discussion sections from each paper.

4. **Initial LLM Summarization:** Submit each section to multiple large language models (`mistral-nemo:12b`, `llama3:8b`, `gemma3:12b`) to generate independent summaries.

5. **Consensus Generation:** Reconcile the outputs from the three LLMs using a tiebreaker model (`phi4:14b`) to produce a unified section summary.

6. **Gene-Level Aggregation:** Combine the consensus summaries across all papers using `gemma3:12b` to generate a final, aggregated gene annotation.

7. **Output:** Structured gene annotation for the input gene.

## Installation / Requirements

## Usage

## Limitations / Considerations

## References
