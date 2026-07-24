# Операции cert-manager: мониторинг, backup, обновление

## Определения

**Операции cert-manager** — регулярные задачи по мониторингу, резервному копированию, обновлению и обеспечению безопасности контроллера.

## Основные концепции

### Архитектура мониторинга

cert-manager экспортирует метрики Prometheus на порту `9402` (по умолчанию — `metrics` ServiceMonitor). Ключевые показатели для мониторинга: статус готовности Certificate, время истечения, ACME-запросы и ошибки контроллера.

### Стратегия обновления

Обновление cert-manager должно выполняться последовательно, пропуская минорные версии только при подтверждении совместимости. Прямой переход через несколько минорных версий может привести к несовместимости CRD. Всегда проверяйте [release notes](https://github.com/cert-manager/cert-manager/releases) на наличие критических изменений. Актуальные поддерживаемые версии доступны на [endoflife.date/cert-manager](https://endoflife.date/cert-manager).

## Практические сценарии

### Мониторинг и алертинг

#### Prometheus-метрики

**Ключевые метрики:**

| Метрика | Описание |
| :--- | :--- |
| `certmanager_certificate_ready_status` | Статус готовности Certificate (0/1) |
| `certmanager_certificate_expiration_timestamp_seconds` | Время истечения сертификата (Unix timestamp) |
| `certmanager_certificate_renewal_timestamp_seconds` | Время следующего планового продления |
| `certmanager_http_acme_client_request_count` | Счётчик запросов к ACME-серверу |
| `certmanager_http_acme_client_request_duration_seconds` | Длительность ACME-запросов |

**Пример алерта (Prometheus):**

```yaml
groups:
- name: cert-manager
  rules:
  - alert: CertificateExpiringSoon
    expr: certmanager_certificate_expiration_timestamp_seconds - time() < 7*24*3600
    for: 1h
    labels:
      severity: warning
    annotations:
      summary: "Сертификат {{ $labels.name }} истекает через {{ $value | humanizeDuration }}"

  - alert: CertificateNotReady
    expr: certmanager_certificate_ready_status{condition="True"} == 0
    for: 10m
    labels:
      severity: critical
    annotations:
      summary: "Сертификат {{ $labels.name }} не готов"
```

#### Grafana Dashboard

Официальный дашборд доступен в репозитории проекта. Рекомендуется использовать ID `11001` или `14595` из Grafana Labs для базового мониторинга.

### Резервное копирование и восстановление

#### Резервное копирование CA-секретов

**Критичные Secret:**

```bash
# Экспорт CA-секрета
kubectl get secret <ca-secret> -n <namespace> -o yaml > ca-secret-backup.yaml

# Экспорт ACME-ключа
kubectl get secret letsencrypt-prod-key -o yaml > acme-key-backup.yaml
```

**Восстановление:**

```bash
kubectl apply -f ca-secret-backup.yaml
```

> **Важно:** Храните бэкапы в защищённом месте, так как Secret содержат приватные ключи.

#### Миграция между кластерами

1. Экспортируйте все Certificate и Issuer ресурсы:

   ```bash
   kubectl get certificates,issuers,clusterissuers --all-namespaces -o yaml > cert-manager-resources.yaml
   ```

2. Экспортируйте CA-секреты и ACME-ключи.

3. Установите cert-manager в новом кластере (см. [установка](../installation.md)).

4. Восстановите CA-секреты.

5. Примените ресурсы:

   ```bash
   kubectl apply -f cert-manager-resources.yaml
   ```

### Обновление cert-manager

#### Через Helm (рекомендуемый способ)

```bash
# Проверка доступных версий
helm search repo jetstack/cert-manager --versions

# Обновление
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.20.0 \
  --reuse-values
```

#### Через kubectl

```bash
# Удалить старую версию
kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.18.0/cert-manager.yaml

# Установить новую
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.19.0/cert-manager.yaml
```

> **Важно:** При использовании `kubectl` убедитесь, что CRD обновлены корректно.

### Безопасность

#### RBAC для cert-manager

cert-manager требует расширенных прав для управления Certificate и Secret. Ограничивайте доступ к Secret через `resourceNames` в специфичных Role:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: secret-reader
  namespace: cert-manager
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["kubernetes-ca-secret"]
  verbs: ["get"]
```

#### Лучшие практики (Best Practices)

| Практика | Описание |
| :--- | :--- |
| **Изоляция namespace** | Установка cert-manager в выделенный namespace (обычно `cert-manager`) |
| **Ограниченный доступ** | RBAC на чтение Secret только для администраторов и контроллера |
| **Мониторинг** | Обязательная настройка алертов на истечение сертификатов |
| **Ротация ключей** | Использование `rotationPolicy: Always` для автоматической смены ключей |
| **Audit логи** | Включение аудита Kubernetes API для отслеживания изменений в Secret |

## Дополнительная информация

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Prometheus-метрики | **10** | Встроены в cert-manager, стабильный API |
| Backup/Restore | **10** | Стандартные манипуляции с ресурсами K8s |
| Обновление Helm | **10** | Официальный и рекомендуемый метод установки |
| RBAC | **9** | Требует тщательной настройки под конкретную среду |

### Смотрите также

- **[Cert-manager: Администрирование](./index.md)** — концепции и управление жизненным циклом
- **[Cert-manager: Установка](../installation.md)** — параметры установки и первоначальная настройка
- **[Cert-manager: Определения](../definitions.md)** — базовая структура и ресурсы
