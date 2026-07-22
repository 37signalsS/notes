# Установка Grafana через Helm

## Определения

- **Grafana**: Платформа для аналитики и визуализации. См. [Обзор Grafana](../grafana_overview.md).
- **Helm**: Пакетный менеджер для Kubernetes, автоматизирующий жизненный цикл приложений.
- **Helm-чарт Grafana**: Набор шаблонов Kubernetes-ресурсов (Deployment, Service, ConfigMap, Secret, Ingress) для развертывания Grafana.
- **`values.yaml`**: Основной файл конфигурации Helm-чарта, позволяющий переопределять стандартные параметры установки.

> **Примечание:** Для установки Grafana в составе полного стека мониторинга (Prometheus + Alertmanager + Grafana) рекомендуется использовать [kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md).

### Миграция репозитория (2026)

С начала 2026 года официальные Open Source чарты Grafana Labs переехали в комьюнити-репозиторий. Оригинальный репозиторий `grafana/helm-charts` теперь ориентирован преимущественно на Enterprise-версии.

**Актуальный репозиторий для OSS Grafana:**

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

Для сохранения данных (дашбордов, настроек, пользователей) необходимо использование **PersistentVolumeClaim (PVC)**. По умолчанию Grafana использует SQLite, файл которой должен храниться на персистентном диске.

**Важно:** SQLite не поддерживает режим `ReadWriteMany`, что ограничивает масштабирование Grafana до одного пода. Для High Availability (HA) требуется внешняя база данных (PostgreSQL/MySQL).

### Внешний доступ (Ingress)

Ресурс Ingress предоставляет доступ к веб-интерфейсу. При настройке Ingress критически важно синхронизировать параметр `root_url` в `grafana.ini` с фактическим DNS-именем, иначе функции экспорта и генерации ссылок в уведомлениях будут работать некорректно.

### Автоматизация (Provisioning через Sidecar)

Helm-чарт включает sidecar-контейнер (на базе `k8s-sidecar`), который сканирует ConfigMaps и Secrets в кластере на наличие специфических меток (labels). При обнаружении нового ресурса sidecar автоматически загружает его в Grafana без перезагрузки пода. См. [Провиженинг Grafana](../grafana_provisioning.md).

---

## Практические сценарии

### Сценарий 1: Базовая установка с Ingress и PVC

Типовая конфигурация для небольших окружений.

```yaml
# grafana-values.yaml
adminPassword: "StrongPassword123" # В продакшене используйте существующий Secret

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
  analytics:
    reporting_enabled: false
```

### Сценарий 2: Production-конфигурация (HA, SMTP, DB)

Для стабильной работы и масштабирования рекомендуется использовать внешнюю БД и настроить отправку уведомлений.

```yaml
# production-values.yaml
replicas: 2

# Использование внешней PostgreSQL для HA
database:
  type: postgres
  host: postgres-service.db-namespace.svc.cluster.local:5432
  name: grafana
  user: grafana
  # Пароль рекомендуется передавать через существующий Secret
  existingSecret: "grafana-db-secret"
  userKey: "user"
  passwordKey: "password"

# Настройка SMTP для алертинга
grafana.ini:
  smtp:
    enabled: true
    host: "smtp.sendgrid.net:587"
    user: "apikey"
    password: "${SMTP_PASSWORD}" # Можно использовать переменные окружения
    from_address: "grafana@example.com"
    starttls_policy: MandatoryStartTLS

# Безопасность и ресурсы
podSecurityContext:
  runAsUser: 472
  runAsGroup: 472
  fsGroup: 472

resources:
  limits:
    cpu: 500m
    memory: 1Gi
  requests:
    cpu: 200m
    memory: 512Mi

# Sidecar для автоматического импорта дашбордов из ConfigMap
sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard
    labelValue: "1"
    searchNamespace: ALL
```

### Сценарий 3: Управление и обновление

**Установка или обновление:**

```bash
# --install создает релиз, если его нет
# --atomic откатывает изменения при ошибке
helm upgrade --install grafana grafana-community/grafana \
  -f grafana-values.yaml \
  --namespace monitoring \
  --create-namespace \
  --atomic
```

**Проверка состояния:**

```bash
# Проверка подов и логов sidecar
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
kubectl logs -f <grafana-pod-name> -c grafana-sc-dashboards -n monitoring
```

---

## Дополнительная информация

### Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **PVC не монтируется** | `storageClassName` не существует или нет прав | Проверьте `kubectl get sc` и события в `kubectl describe pvc` |
| **Циклическая перезагрузка** | Ошибка в `grafana.ini` или правах на `/var/lib/grafana` | Проверьте логи: `kubectl logs <pod> -c grafana` |
| **Sidecar не видит дашборд** | Отсутствует метка на ConfigMap | Убедитесь, что на ConfigMap есть label `grafana_dashboard: "1"` |
| **SMTP не отправляет почту** | Блокировка порта или неверные учетные данные | Проверьте логи Grafana на наличие ошибок "SMTP authentication failed" |

### Полезные команды Helm

```bash
# Просмотр всех доступных параметров чарта с описанием
helm show values grafana-community/grafana

# Проверка рендеринга шаблонов без установки (dry-run)
helm install grafana grafana-community/grafana -f values.yaml --dry-run --debug

# Получение пароля администратора (если не задан в values)
kubectl get secret --namespace monitoring grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

**См. также:**

- [Провиженинг Grafana](../grafana_provisioning.md)
- [Высокая доступность Grafana](../high_availability.md)
- [Конфигурация Grafana в kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/grafana_config.md)
- [Управление плагинами](../grafana_plugins.md)
