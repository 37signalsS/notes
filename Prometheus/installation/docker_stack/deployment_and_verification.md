# Запуск и проверка стека

1. Убедитесь, что все файлы и директории созданы согласно [структуре проекта](./overview.md#структура-проекта).
2. Перейдите в директорию `monitoring/`.
3. Запустите стек Docker Compose:

    ```bash
    docker-compose up -d
    ```

4. **Prometheus**: Откройте `http://localhost:9090`. На вкладке **Status -> Targets** убедитесь, что все цели (`prometheus`, `node-exporter`, `cadvisor`) имеют статус `UP`.
5. **Grafana**: Откройте `http://localhost:3000`. Войдите (`admin`/`admin`), добавьте Prometheus как [Data Source](../../../Grafana/grafana_datasources.md) (`http://prometheus:9090`) и импортируйте [дашборды](../../../Grafana/dashboards/definitions_and_concepts.md) (например, `1860` для Node Exporter, `13981` для Docker/cAdvisor).
6. **Alertmanager**: Откройте `http://localhost:9093`.
