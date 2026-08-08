# Операции cert-manager: мониторинг, резервное копирование и обновление

## Определения

**Операции cert-manager (Day 2 Operations)** — комплекс регулярных задач по обеспечению непрерывности работы (High Availability), мониторингу состояния сертификатов, резервному копированию критических данных и плановому обновлению компонентов контроллера.

**ARI (ACME Renewal Information)** — механизм, позволяющий оператору отслеживать не только срок истечения, но и "окно продления", рекомендованное центром сертификации.

**cmctl** — специализированная CLI-утилита для операционного управления cert-manager (продление, проверка статуса, инспекция секретов).

---

## Основные концепции

### Архитектура мониторинга

cert-manager предоставляет нативный эндпоинт для сбора метрик в формате Prometheus на порту `9402`. Для интеграции с `kube-prometheus-stack` используется ресурс `ServiceMonitor`.

**Объекты мониторинга:**
1.  **Контроллер:** здоровье процесса, лидерство (Leader Election), нагрузка на очередь (Workqueue).
2.  **Сертификаты:** время до истечения, статус готовности, количество попыток продления.
3.  **Взаимодействие с CA:** частота запросов к ACME-серверу, ошибки API (Rate Limits).
4.  **Webhook:** задержка валидации и ошибки инъекции CA.

### Стратегии обновления и риски

Обновление cert-manager требует тщательного тестирования из-за тесной интеграции с Kubernetes API через CRD.

*   **Минорные обновления:** (например, 1.20 -> 1.21) обычно проходят бесшовно.
*   **Мажорные обновления:** требуют проверки совместимости API-версий ресурсов (`v1beta1` vs `v1`).
*   **Риски:** При обновлении Webhook может возникнуть "окно недоступности", в течение которого создание любых ресурсов в кластере (не только cert-manager) может быть заблокировано. Рекомендуется использовать HA-конфигурацию (3 реплики webhook).

---

## Практические сценарии

### Мониторинг и алертинг

#### Ключевые метрики Prometheus

| Метрика | Описание | Критический порог |
| :--- | :--- | :--- |
| `certmanager_certificate_ready_status` | Статус готовности (condition=True: 1, False: 0) | `< 1` |
| `certmanager_certificate_expiration_timestamp_seconds` | Время истечения (Unix timestamp) | `< 7 days` |
| `certmanager_http_acme_client_request_count` | Количество запросов к ACME API | Аномальный рост |
| `controller_runtime_reconcile_errors_total` | Общее количество ошибок реконсиляции | `> 0` |

#### Настройка алертов (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cert-manager-alerts
  namespace: cert-manager
spec:
  groups:
  - name: cert-manager.rules
    rules:
    - alert: CertManagerCertificateExpiration
      expr: |
        certmanager_certificate_expiration_timestamp_seconds - time() < 7 * 24 * 3600
      for: 1h
      labels:
        severity: warning
      annotations:
        description: "Сертификат {{ $labels.name }} в namespace {{ $labels.namespace }} истекает менее чем через 7 дней."
    
    - alert: CertManagerControllerDown
      expr: up{job="cert-manager"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        description: "Контроллер cert-manager недоступен."
```

### Резервное копирование и восстановление

#### Резервное копирование критических данных

Для восстановления PKI-инфраструктуры необходимо бэкапировать не только ресурсы, но и секреты, содержащие приватные ключи CA и аккаунтов.

```bash
# 1. Резервное копирование всех ресурсов cert-manager
kubectl get issuers,clusterissuers,certificates,certificaterequests -A -o yaml > cert-manager-backup.yaml

# 2. Резервное копирование CA-секретов (самое важное)
# ВАЖНО: Храните эти файлы в зашифрованном виде!
kubectl get secret -n cert-manager -l controller.cert-manager.io/fcl=true -o yaml > ca-secrets-backup.yaml

# 3. Резервное копирование ключей ACME-аккаунтов
kubectl get secret -n cert-manager letsencrypt-prod-account-key -o yaml > acme-account-backup.yaml
```

#### Проверка целостности бэкапа

Рекомендуется ежеквартально проверять возможность восстановления в изолированном namespace или тестовом кластере.

### Миграция между кластерами

Алгоритм переноса активных сертификатов без перевыпуска (избегание Rate Limits):

1.  **Кластер-источник:** Экспортируйте ресурсы и секреты (см. выше).
2.  **Новый кластер:** Установите cert-manager той же или более новой версии.
3.  **Импорт секретов:** Сначала примените файлы с секретами (`ca-secrets-backup.yaml`).
4.  **Импорт ресурсов:** Примените манифесты `Issuers` и `Certificates`.
5.  **Верификация:** Проверьте статус через `kubectl get certificate -A`. Контроллер должен подхватить существующие секреты без запроса новых в CA.

### Плановое обновление (Helm)

Перед обновлением всегда проверяйте текущие версии и делайте бэкап.

```bash
# Просмотр текущей конфигурации
helm get values cert-manager -n cert-manager

# Обновление до целевой версии (например, v1.21.0)
# Пояснение: --version указывает версию чарта, --reuse-values сохраняет текущие настройки
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.21.0 \
  --reuse-values \
  --wait
```

### Использование cmctl для операционных задач

Утилита `cmctl` (устанавливается отдельно) значительно упрощает Day 2 операции.

```bash
# Принудительное продление сертификата (внеплановая ротация)
cmctl renew <cert-name> -n <namespace>

# Инспекция сертификата в секрете (аналог openssl x509)
cmctl inspect secret <secret-name> -n <namespace>

# Проверка статуса выпуска
cmctl status certificate <cert-name> -n <namespace>
```

---

## Дополнительная информация

### Лучшие практики эксплуатации

*   **Staging для тестов:** Всегда используйте Let's Encrypt Staging для проверки миграций и обновлений инфраструктуры.
*   **Разделение Issuer:** Используйте разные Issuer для публичных (Let's Encrypt) и внутренних (Vault/Self-signed) нужд для упрощения аудита.
*   **Мониторинг Webhook:** Настройте алерты на `certmanager_webhook_request_duration_seconds`. Рост задержки может замедлить работу всего кластера.

### Смотрите также

- **[Cert-manager: Администрирование](./index.md)** — HA, RBAC и Garbage Collection.
- **[Cert-manager: Диагностика](./troubleshooting.md)** — глубокий анализ ошибок и логирования.
- **[Предотвращение истечения сертификатов](../../Operations/ssl_expiration_prevention.md)** — общие стратегии мониторинга TLS.
