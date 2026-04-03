# Операции Cert-manager: мониторинг, backup, обновление

## Определения

**Операции cert-manager** — регулярные задачи по мониторингу, резервному копированию, обновлению и обеспечению безопасности.

## Basic Concepts

### Архитектура мониторинга

cert-manager экспортирует метрики Prometheus на порту `9402` (по умолчанию — `metrics` ServiceMonitor). Ключевые компоненты для мониторинга: статус готовности Certificate, время истечения, ACME-запросы и ошибки.

### Стратегия обновления

Обновление cert-manager должно выполняться последовательно, пропуская минорные версии. Прямой переход через несколько минорных версий может привести к несовместимости CRD. Всегда проверяйте [release notes](https://github.com/cert-manager/cert-manager/releases) на breaking changes. Актуальные поддерживаемые версии — на [endoflife.date/cert-manager](https://endoflife.date/cert-manager).

## Practical Scenarios

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

Официальный [dashboard](https://github.com/cert-manager/cert-manager/tree/master/contrib/prometheus-metrics) доступен в репозитории cert-manager.

### Резервное копирование и восстановление

#### Backup CA-секретов

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

> **Важно:** Храните backup в защищённом месте — Secret содержат приватные ключи.

#### Миграция между кластерами

1. Экспортировать все Certificate и Issuer ресурсы:

   ```bash
   kubectl get certificates,issuers,clusterissuers --all-namespaces -o yaml > cert-manager-resources.yaml
   ```

2. Экспортировать CA-секреты и ACME-ключи.

3. Установить cert-manager в новом кластере (см. [установка](../installation.md)).

4. Восстановить CA-секреты.

5. Применить ресурсы:

   ```bash
   kubectl apply -f cert-manager-resources.yaml
   ```

### Обновление cert-manager

#### Helm

```bash
# Проверка доступных версий
helm search repo jetstack/cert-manager --versions

# Обновление
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.19.0 \
  --reuse-values
```

#### kubectl

```bash
# Удалить старую версию
kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.18.0/cert-manager.yaml

# Установить новую
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.19.0/cert-manager.yaml
```

> **Важно:** Обновляйте CRD отдельно при переходе между минорными версиями: `kubectl apply -f <crd.yaml>`.

### Безопасность

#### RBAC для cert-manager

cert-manager требует широкие права для управления Certificate и Secret. Ограничивайте доступ к Secret через `resourceNames`:

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

#### Best Practices

| Практика | Описание |
| :--- | :--- |
| **Изоляция namespace** | Устанавливать cert-manager в отдельный namespace |
| **Ограниченный доступ** | RBAC на чтение Secret только для администраторов |
| **Мониторинг** | Алерты на истечение сертификатов (см. выше) |
| **Rotation ключей** | Регулярная ротация ACME-ключей и CA |
| **Audit логи** | Включить аудит Kubernetes API для cert-manager namespace |

## Additional Information

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Prometheus-метрики | **10** | Официальная документация cert-manager.io |
| Backup/Restore | **9** | Стандартная практика Kubernetes |
| Обновление | **9** | Release notes cert-manager |
| RBAC | **9** | Kubernetes RBAC best practices |
