# Операции Cert-manager: мониторинг, backup, обновление

## Определения

**Операции cert-manager** — регулярные задачи по мониторингу, резервному копированию, обновлению и обеспечению безопасности.

> **Навигация:** [Главная Administration](./index.md) | [Troubleshooting](./troubleshooting.md)

---

## Practical Scenarios

### Мониторинг и алертинг

#### Prometheus-метрики

cert-manager экспортирует метрики на порту 9402.

**Ключевые метрики:**

| Метрика | Описание |
| :--- | :--- |
| `certmanager_certificate_ready_status` | Статус готовности Certificate |
| `certmanager_certificate_expiration_timestamp_seconds` | Время истечения сертификата |
| `certmanager_certificate_renewal_timestamp_seconds` | Время следующего продления |
| `certmanager_http_acme_client_request_count` | Запросы к ACME-серверу |
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

Импортировать [официальный dashboard](https://github.com/cert-manager/cert-manager/tree/master/contrib/prometheus-metrics).

---

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

> **Важно:** Храните backup в защищённом месте (Secret содержат приватные ключи).

#### Миграция между кластерами

1. Экспортировать все Certificate и Issuer ресурсы:

   ```bash
   kubectl get certificates,issuers,clusterissuers --all-namespaces -o yaml > cert-manager-resources.yaml
   ```

2. Экспортировать CA-секреты (см. выше)

3. Установить cert-manager в новом кластере

4. Восстановить CA-секреты

5. Применить ресурсы:

   ```bash
   kubectl apply -f cert-manager-resources.yaml
   ```

---

### Обновление cert-manager

#### Helm

```bash
# Проверка доступных версий
helm search repo jetstack/cert-manager --versions

# Обновление
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.15.0 \
  --reuse-values
```

#### kubectl

```bash
# Удалить старую версию
kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.2/cert-manager.yaml

# Установить новую
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.0/cert-manager.yaml
```

> **Важно:** Проверить [release notes](https://github.com/cert-manager/cert-manager/releases) на breaking changes.

---

### Безопасность

#### RBAC для cert-manager

cert-manager требует широкие права для управления Certificate и Secret.

**Ограничение доступа к Secret:**

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
  resourceNames: ["kubernetes-ca-secret"]  # Только конкретные Secret
  verbs: ["get"]
```

#### Best Practices

| Практика | Описание |
| :--- | :--- |
| **Изоляция namespace** | Устанавливать cert-manager в отдельный namespace |
| **Ограниченный доступ** | RBAC на чтение Secret только для администраторов |
| **Мониторинг** | Алерты на истечение сертификатов |
| **Rotation ключей** | Регулярная ротация ACME-ключей и CA |
| **Audit логи** | Включить аудит Kubernetes API для cert-manager |

---

## Additional Information

### Связанные темы

- [Private CA](../private_ca.md) — создание собственного CA
- [LetsEncrypt](../LetsEncrypt/) — практические сценарии с Let's Encrypt
- [Installation](../install.md) — установка cert-manager
