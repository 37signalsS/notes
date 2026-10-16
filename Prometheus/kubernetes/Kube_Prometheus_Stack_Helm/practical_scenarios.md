# Практические сценарии kube-prometheus-stack

## Обзор

Данный раздел является каталогом практических руководств по развёртыванию, эксплуатации и troubleshooting kube-prometheus-stack (KPS) в Kubernetes-кластерах. Здесь собраны сценарии от базовой установки до продвинутых конфигураций для DevOps/SRE-инженеров и системных администраторов.

Структура раздела:
- **Установка и базовое развертывание:** Онлайн и оффлайн установка, настройка хранилища.
- **Мониторинг инфраструктуры:** Master-ноды, etcd, обогащение метрик Node Exporter.
- **Мониторинг приложений:** Мониторинг Node.js приложений, внешние цели.
- **Безопасность и доступ:** Защита веб-интерфейсов.

## Категории сценариев

### Установка и базовое развертывание

*   **[Онлайн-установка](./practical_scenarios/online_installation.md)** — стандартное развертывание в кластере с доступом к интернету. Включает быстрый старт, production-ready конфигурацию и валидацию установки.
*   **[Argo CD (GitOps) установка](./practical_scenarios/argocd_installation.md)** — декларативное развёртывание через Application с GitOps workflow. Application для kube-prometheus-stack, управление секретами через Sealed Secrets.
*   **[Offline (Air-gapped) установка](./practical_scenarios/offline_airgapped_installation.md)** — развертывание в изолированных контурах. Требует подготовки артефактов чарта и образов, настройки локального реестра.
*   **[Настройка Persistent Volumes](./practical_scenarios/persistent_volumes.md)** — обеспечение сохранности данных TSDB. Динамическое и статическое provisioning, retention policy, онлайн-расширение PVC.

### Мониторинг инфраструктуры

*   **[Мониторинг Master-нод](./practical_scenarios/master_nodes_monitoring.md)** — сбор метрик с компонентов Control Plane. Настройка tolerations для Node Exporter, разделение метрик хоста и сервисов.
*   **[Мониторинг etcd](./etcd-monitoring.md)** — специфические настройки для etcd. TLS-аутентификация, ServiceMonitor, EndpointSlice, upgrade мониторинга.
*   **[Обогащение метрик Node Exporter](./practical_scenarios/node_exporter_enrichment.md)** — добавление кастомных лейблов и коллекторов. scrapeClasses, relabelingConfigs, metricRelabelings, снижение кардинальности.

### Мониторинг приложений

*   **[Мониторинг Node.js приложения](./practical_scenarios/app_monitoring_node_js.md)** — полный цикл от Deployment до ServiceMonitor и AlertingRules. Настройка ингресса, проверка доступности.
*   **[Мониторинг внешних целей](./practical_scenarios/external_monitoring.md)** — подключение ресурсов вне кластера Kubernetes. Blackbox exporter, ScrapeConfig CRD, конфигурация через additionalScrapeConfigs.

### Безопасность и доступ

*   **[Настройка веб-аутентификации](./practical_scenarios/web_authentication.md)** — защита UI интерфейсов Prometheus, Alertmanager и Grafana. Basic Auth (Bcrypt), OAuth2-proxy, TLS.

## Общие паттерны операций

### Валидация конфигурации

Перед применением изменений проверяйте синтаксис и структуру manifests:

```bash
helm template monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values.yaml | kubectl apply --dry-run=client -f -
```

### Резервное копирование

Создавайте бэкап перед каждым `helm upgrade`:

```bash
# Экспорт значений релиза
helm get values monitoring -n monitoring > backup-values.yaml

# Экспорт пользовательских ресурсов
kubectl get servicemonitor,podmonitor,prometheusrule,alertmanagerconfig \
  -n monitoring -o yaml > backup-custom-resources.yaml
```

### Откат изменений

```bash
# Откат к предыдущей версии релиза
helm rollback monitoring -n monitoring

# Проверка rollout после отката
kubectl rollout status statefulset/prometheus-operated -n monitoring --timeout=5m
kubectl rollout status statefulset/alertmanager-monitoring-kube-prometheus-alertmanager -n monitoring --timeout=5m
```

### Очистка окружения

```bash
# Удаление релиза (сохранение CRD и данных)
helm uninstall monitoring -n monitoring

# Удаление namespace (если пустой)
kubectl delete namespace monitoring

# При необходимости удалить PVC
kubectl delete pvc -n monitoring -l app.kubernetes.io/instance=monitoring
```

> **Важно:** Подробные инструкции и edge cases: [Обзор kube-prometheus-stack](./overview.md), [Конфигурация компонентов](./other_components_config.md).

## Выбор сценария

1. **Новый кластер с доступом к интернету:** Начните с [Онлайн-установки](./practical_scenarios/online_installation.md) (Helm CLI) или [Argo CD установки](./practical_scenarios/argocd_installation.md) (GitOps). После установки переходите к настройке мониторинга инфраструктуры или приложений.
2. **Закрытый контур (Air-gapped):** Используйте [Offline установку](./practical_scenarios/offline_airgapped_installation.md). Подготовьте локальный реестр и артефакты заранее.
3. **Специальные требования к хранилищу:** Настройте [Persistent Volumes](./practical_scenarios/persistent_volumes.md) до установки стека.
4. **Master-ноды не мониторятся:** Настройте [Мониторинг Master-нод](./practical_scenarios/master_nodes_monitoring.md) через tolerations Node Exporter.
5. **Приложения за пределами кластера:** Используйте [Мониторинг внешних целей](./practical_scenarios/external_monitoring.md) с Blackbox exporter или ScrapeConfig.
6. **Требуется защита веб-интерфейсов:** Настройте [Веб-аутентификацию](./practical_scenarios/web_authentication.md) после установки.

## Типичные проблемы при работе со сценариями

| Проблема | Диагностика | Решение |
|:---|:---|:---|
| Pod в статусе Pending | `kubectl describe pod <pod> -n monitoring` | Проверьте StorageClass, PVC, события в namespace |
| ImagePullBackOff | `kubectl describe pod <pod> -n monitoring` | Настройте `global.imagePullSecrets`, проверьте доступность registry |
| Target DOWN | Prometheus UI → Targets | Проверьте labels на сервисе и `matchLabels` в ServiceMonitor |
| OOMKilled | `kubectl get pod <pod> -n monitoring -o yaml` | Увеличьте memory limit, включите native-histograms |
| ConfigMap Reload не срабатывает | Логи sidecar | Проверьте permissions на ConfigMap/Secret |

## Best Practices

1. **Фиксация версий:** Указывайте версию чарта (`--version`) в production для предсказуемости deployments.
2. **Namespace isolation:** Используйте выделенный namespace (например, `monitoring`) для изоляции ресурсов мониторинга.
3. **Валидация перед применением:** Используйте `helm diff upgrade` для просмотра планируемых изменений.
4. **Резервное копирование:** Создавайте бэкап `values.yaml` и пользовательских ресурсов перед каждым `helm upgrade`.
5. **Мониторинг мониторинга:** Включите `defaultRules.create: true` для алертов на состояние компонентов KPS.

## Диагностика

При возникновении проблем со сценарными настройками обращайтесь к разделу **[Troubleshooting](../../operator/troubleshooting.md)**.

## Связанные темы

- [Обзор kube-prometheus-stack](./overview.md) — архитектура, версии, жизненный цикл компонентов.
- [Конфигурация компонентов](./other_components_config.md) — RBAC, reload, default rules, Thanos Ruler.
- [Конфигурация Alertmanager](./alertmanager_config.md) — routing, receivers, AlertmanagerConfig CRD.
