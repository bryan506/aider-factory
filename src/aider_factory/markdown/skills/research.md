# AI Factory Web Research & Ingestion Skill (`aider-research`)

Use this skill when searching online topics, fetching literature or web documentation, and ingesting web sources into your active LanceDB collection for Knowledge Oracle querying.

## Commands

```bash
# 1. Metasearch via SearXNG (Academic mode)
/run .aider_factory/bash/research search "negative income tax labor supply" --academic --top 5

# 2. Metasearch using a file for multiline / complex citations
/run .aider_factory/bash/research search --file query.txt --academic --top 10

# 3. Direct Oracle Web Ingestion (Direct URLs or --file line-separated input)
/run .aider_factory/bash/oracle --add-web https://example.com/article.html --collection my_collection
/run .aider_factory/bash/oracle --add-web --file urls.txt --collection my_collection
/run .aider_factory/bash/oracle --add-web --file ~/notes/urls.txt
```
