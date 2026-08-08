# Установка Grafana через Helm

## Определения

**Grafana** — платформа для аналитики и визуализации данных. См. [Обзор Grafana](../grafana_overview.md).

**Helm** — пакетный менеджер для Kubernetes, автоматизирующий жизненный цикл приложений через шаблонизированные чарты.

**Helm-чарт Grafana** — набор шаблонов Kubernetes-ресурсов (Deployment, Service, ConfigMap, Secret, Ingress), необходимых для развертывания Grafana.

**`values.yaml`** — файл параметров конфигурации Helm-чарта, позволяющий переопределять стандартные настройки установки.

> **Примечание:** Для установки Grafana в составе полного стека мониторинга рекомендуется использовать [kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md).

### Миграция репозитория (2026)

С начала 2026 года официальные Open Source чарты Grafana Labs переехали в комьюнити-репозиторий. Оригинальный репозиторий `grafana/helm-charts` теперь ориентирован преимущественно на Enterprise-версии.

**Актуальный репозиторий для OSS Grafana 13.x:**

```bash
# Добавление репозитория
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# Поиск версий чарта
helm search repo grafana-community/grafana --versions
```

---

## Основные концепции

### Персистентность (Persistence)

Для сохранения данных (дашбордов, настроек, пользователей) требуется использование **PersistentVolumeClaim (PVC)**. По умолчанию Grafana использует SQLite.

**Важно:** SQLite не поддерживает режим доступа `ReadWriteMany`, что ограничивает масштабирование Grafana до одного пода. Для обеспечения высокой доступности (HA) и горизонтального масштабирования необходимо использовать внешнюю базу данных (PostgreSQL или MySQL).

### Внешний доступ (Ingress)

Ресурс Ingress предоставляет доступ к веб-интерфейсу. При настройке Ingress критически важно синхронизировать параметр `root_url` в `grafana.ini` с фактическим DNS-именем для корректной работы ссылок в уведомлениях и экспорта отчетов.

### Автоматизация (Provisioning через Sidecar)

Helm-чарт включает sidecar-контейнер (`k8s-sidecar`), который сканирует ConfigMaps и Secrets в кластере на наличие меток (labels). При обнаружении ресурса с заданной меткой sidecar автоматически загружает его в Grafana без перезагрузки основного пода. См. [Провиженинг Grafana](../grafana_provisioning.md).

---

## Практические сценарии

### Сценарий 1: Базовая установка с Ingress и PVC

Конфигурация для небольших или тестовых окружений.

```yaml
# grafana-values.yaml
adminPassword: "StrongPassword123"

persistence:
  enabled: true
  type: pvc
  size: 10Gi
  storageClassName: standard

ingress:
  enabled: true
  ingressClassName: nginx
  hosts:
    - grafana.example.com
  tls:
    - secretName: grafana-tls
      hosts:
        - grafana.example.com

grafana.ini:
  server:
    domain: grafana.example.com
    root_url: "https://%(domain)s/"
    enable_gzip: true
```

### Сценарий 2: Production-конфигурация (HA, SMTP, внешняя БД)

Рекомендуется для стабильной работы и масштабирования.

```yaml
# production-values.yaml
replicas: 3

# Использование внешней PostgreSQL для обеспечения HA
database:
  type: postgres
  host: postgres-service.db-namespace.svc.cluster.local:5432
  name: grafana
  user: grafana
  existingSecret: "grafana-db-secret" # Секрет с ключами "user" и "password"
  userKey: "user"
  passwordKey: "password"

# Настройка SMTP для уведомлений
grafana.ini:
  smtp:
    enabled: true
    host: "smtp.sendgrid.net:587"
    user: "apikey"
    password: "${SMTP_PASSWORD}"
    from_address: "grafana@example.com"
    starttls_policy: MandatoryStartTLS

# Настройки безопасности
podSecurityContext:
  runAsUser: 472
  runAsGroup: 472
  fsGroup: 472

resources:
  limits:
    cpu: 1000m
    memory: 2Gi
  requests:
    cpu: 500m
    memory: 1Gi
```

### Сценарий 3: Самомониторинг и масштабирование

Настройка автоматического сбора метрик самой Grafana и горизонтального масштабирования.

```yaml
# monitoring-values.yaml

# Включение ServiceMonitor для Prometheus Operator
serviceMonitor:
  enabled: true
  namespace: monitoring
  interval: 30s
  labels:
    release: kube-prometheus-stack

# Горизонтальное масштабирование по CPU
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

# Интеграция с External Secrets (использование существующего секрета)
envFromSecret: "grafana-external-secrets"
```

### Сценарий 4: Управление жизненным циклом

**Установка или обновление:**

```bash
# --install создает релиз, если его нет
# --atomic откатывает изменения при неудаче
helm upgrade --install grafana grafana-community/grafana \
  -f values.yaml \
  --namespace monitoring \
  --create-namespace \
  --atomic
```

**Проверка состояния:**

```bash
# Проверка подов и контейнеров (основной и sidecar)
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana

# Просмотр логов процесса загрузки дашбордов
kubectl logs -l app.kubernetes.io/name=grafana -c grafana-sc-dashboards -n monitoring
```

---

## Дополнительная информация

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **PVC не переходит в Bound** | Неверный `storageClassName` или отсутствие ресурсов | Проверьте описание PVC: `kubectl describe pvc` |
| **CrashLoopBackOff основного контейнера** | Ошибка в `grafana.ini` или правах на volume | Проверьте логи: `kubectl logs <pod> -c grafana` |
| **Дашборды не импортируются** | Отсутствует метка на ConfigMap | Проверьте наличие label `grafana_dashboard: "1"` (или значения из values) |
| **ServiceMonitor не собирает метрики** | Несоответствие селекторов меток | Убедитесь, что метки в `serviceMonitor.labels` совпадают с ожидаемыми в Prometheus |

### Полезные команды Helm

```bash
# Вывод всех доступных параметров чарта
helm show values grafana-community/grafana

# Отладка манифестов без применения (Dry Run)
helm install test grafana-community/grafana -f values.yaml --dry-run --debug

# Получение пароля администратора (если не задан явно)
kubectl get secret --namespace monitoring grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

**См. также:**

- [Провиженинг Grafana](../grafana_provisioning.md) — детальное описание работы sidecar.
- [Высокая доступность Grafana](../high_availability.md) — архитектурные нюансы масштабирования.
- [Конфигурация Grafana в kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/grafana_config.md) — специфика встроенной Grafana.
- [Управление плагинами](../grafana_plugins.md) — установка и обновление расширений.
