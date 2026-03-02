# kube-prometheus-stack: Практические сценарии

## Определения

**Онлайн установка** — стандартный метод развертывания стека мониторинга с прямым доступом к публичным Helm-репозиториям и контейнерным реестрам.

**Оффлайн установка (Air-gapped)** — метод развертывания в изолированных средах без доступа к интернету, требующий предварительной загрузки образов и чартов в приватный репозиторий.

## Основные концепции

### Выбор метода установки

| Критерий | Онлайн | Оффлайн |
| :--- | :--- | :--- |
| Доступ к интернету | Требуется | Не требуется |
| Требования | Helm, K8s cluster, Ingress (опционально) | Хост с интернетом, Harbor/Nexus, Longhorn/NFS |
| Сложность | Низкая | Высокая |
| Время развертывания | 5-10 минут | 30-60 минут |

## Практические сценарии

- [Онлайн установка](./practical_scenarios/online_installation.md)
- [Оффлайн установка (Air-gapped)](./practical_scenarios/offline_airgapped_installation.md)
- [Настройка мониторинга внешних ресурсов](./practical_scenarios/external_monitoring.md)
- [Обогащение метрик node-exporter](./practical_scenarios/node_exporter_enrichment.md)
- [Сбор метрик с master-нод](./practical_scenarios/master_nodes_monitoring.md)
- [Настройка Persistent Volumes вручную](./practical_scenarios/persistent_volumes.md)
- [Авторизация в веб-интерфейсе](./practical_scenarios/web_authentication.md)
