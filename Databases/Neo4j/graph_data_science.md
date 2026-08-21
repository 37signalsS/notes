# Neo4j: Graph Data Science (GDS)

**Neo4j GDS** — плагин для графовой аналитики и машинного обучения. Совместимость: GDS 2026.07.x совместим с Neo4j 2026.07.x.

## Алгоритмы GDS

| Категория | Алгоритмы | Применение |
| :--- | :--- | :--- |
| **Centrality** | PageRank, Betweenness, Degree | Выявление ключевых узлов |
| **Community Detection** | Louvain, Label Propagation, Weakly Connected Components | Кластеризация узлов |
| **Pathfinding** | Shortest Path, Dijkstra, All Pairs Shortest Paths | Анализ маршрутов |
| **Similarity** | Node Similarity, Cosine Similarity, Pearson | Рекомендации, дедупликация |
| **Node Embeddings** | FastRP, Node2Vec | ML-представления узлов |
| **Link Prediction** | Common Neighbors, Adamic Adar | Предсказание связей |

## Примеры использования

```cypher
// PageRank: выявление наиболее "влиятельных" узлов
CALL gds.pageRank.stream('myGraph')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).name AS name, score
ORDER BY score DESC LIMIT 10;

// Community Detection (Louvain)
CALL gds.louvain.stream('myGraph')
YIELD nodeId, communityId
RETURN communityId, collect(gds.util.asNode(nodeId).name) AS members
ORDER BY size(members) DESC;

// Кратчайший путь
MATCH (start:Station {name: 'A'}), (end:Station {name: 'Z'})
CALL gds.shortestPath.dijkstra.stream('myGraph', {
  sourceNode: start,
  targetNode: end
})
YIELD index, sourceNode, targetNode, totalCost, nodeIds, costs, path
RETURN path, totalCost;
```

## Инсталляция GDS

```bash
# В Docker
docker run -d \
  --name neo4j-gds \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 \
  -e NEO4J_PLUGINS='["apoc","graph-data-science"]' \
  neo4j:2026.07.0-community

# Ручная установка (production)
cd $NEO4J_HOME/plugins
wget https://github.com/neo4j/graph-data-science/releases/download/2026.07.0/neo4j-graph-data-science-2026.07.0.jar
sudo systemctl restart neo4j
```

**Важно:** GDS создает проекции графа в памяти. Для больших графов убедитесь, что Page Cache достаточно для хранения данных + проекций.

## См. также
- **[Обзор Neo4j](./overview.md)** — определения и место в экосистеме.
- **[Оптимизация запросов](./query_optimization.md)** — EXPLAIN/PROFILE, индексы.
- **[APOC: библиотека расширений](./apoc.md)** — дополнительные графовые алгоритмы.
