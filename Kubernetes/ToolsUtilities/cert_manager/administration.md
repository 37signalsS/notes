# Администрирование Cert-manager

## Управление секретами при удалении сертификатов

### Поведение по умолчанию

По умолчанию cert-manager **не удаляет** Kubernetes `Secret` при удалении ресурса `Certificate`. Это сделано для безопасности — случайное удаление `Certificate` не должно приводить к потере рабочего TLS-сертификата.

**Проблема:** При пересоздании `Certificate` с тем же `secretName` cert-manager не обновляет существующий Secret, что может привести к использованию устаревшего сертификата.

### Включение garbage collection

Для автоматического удаления Secret при удалении Certificate используйте флаг `--enable-certificate-owner-ref=true`.

**Helm:**

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true \
  --set "extraArgs={--enable-certificate-owner-ref=true}"
```

**Поведение после включения:**

- cert-manager добавляет `ownerReference` к Secret, указывая на Certificate
- При удалении Certificate сборщик мусора Kubernetes автоматически удаляет Secret

| Преимущества | Риски |
| :--- | :--- |
| Упрощает управление жизненным циклом | Случайное удаление Certificate удаляет Secret |
| Автоматическая очистка | Возможны простои при ошибке |
| Прозрачная связь ресурсов | Требует осторожности в production |

> **Рекомендация:** Используйте с осторожностью в production. Включайте в development/staging.

---

## Диагностика и troubleshooting

### Проверка состояния ресурсов

```bash
# Статус всех Certificate
kubectl get certificates --all-namespaces

# Детали конкретного Certificate
kubectl describe certificate <name> -n <namespace>

# Статус Order (ACME)
kubectl get orders --all-namespaces

# Статус Challenge (ACME проверки)
kubectl get challenges --all-namespaces

# Проверка Issuer/ClusterIssuer
kubectl get issuers,clusterissuers --all-namespaces
kubectl describe issuer <name> -n <namespace>
```

### Логи компонентов

```bash
# Основной контроллер
kubectl logs -n cert-manager -l app=cert-manager --tail=100

# Webhook
kubectl logs -n cert-manager -l app=webhook --tail=100

# CA Injector
kubectl logs -n cert-manager -l app=cainjector --tail=100

# Поиск ошибок ACME
kubectl logs -n cert-manager -l app=cert-manager | grep -i "acme\|error"
```

### Частые проблемы и решения

#### Certificate в статусе Pending

**Причина:** ACME-проверка не пройдена.

```bash
# Проверить детали
kubectl describe certificate <name> -n <namespace>

# Проверить Challenge
kubectl describe challenge <name> -n <namespace>

# Проверить Order
kubectl describe order <name> -n <namespace>
```

**Возможные причины:**

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| HTTP-01 недоступен | `curl http://<domain>/.well-known/acme-challenge/` | Проверить Ingress, firewall |
| DNS-01 не прошёл | Проверить TXT-запись: `dig TXT _acme-challenge.<domain>` | Проверить DNS API credentials |
| Rate limit | `kubectl get order -o yaml` | Использовать staging, подождать |

#### Secret не создаётся

**Причина:** Certificate не готов или ошибка записи Secret.

```bash
# Проверить события
kubectl get events -n <namespace> --sort-by='.lastTimestamp'

# Проверить RBAC для cert-manager
kubectl describe clusterrole cert-manager-controller-certificates
```

#### Webhook timeout

**Причина:** Проблемы с сетью или ресурсами webhook.

```bash
# Проверить webhook deployment
kubectl get deployment cert-manager-webhook -n cert-manager
kubectl describe deployment cert-manager-webhook -n cert-manager

# Проверить сервис
kubectl get svc cert-manager-webhook -n cert-manager
kubectl get endpoints cert-manager-webhook -n cert-manager
```

**Решение:**

```bash
# Пересоздать webhook
kubectl rollout restart deployment cert-manager-webhook -n cert-manager
```

#### Ошибка цепочки доверия

**Причина:** Приложение не доверяет CA.

```bash
# Получить CA из Secret
kubectl get secret <ca-secret> -n <namespace> -o jsonpath='{.data.ca\.crt}' | base64 -d > ca.crt

# Проверить сертификат
openssl verify -CAfile ca.crt <cert.crt>
```

**Решение:** Импортировать `ca.crt` в trust store приложения.

---

## Мониторинг и алертинг

### Prometheus-метрики

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

### Grafana Dashboard

Импортировать [официальный dashboard](https://github.com/cert-manager/cert-manager/tree/master/contrib/prometheus-metrics).

---

## Резервное копирование и восстановление

### Backup CA-секретов

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

### Миграция между кластерами

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

## Обновление cert-manager

### Helm

```bash
# Проверка доступных версий
helm search repo jetstack/cert-manager --versions

# Обновление
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.15.0 \
  --reuse-values
```

### kubectl

```bash
# Удалить старую версию
kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.2/cert-manager.yaml

# Установить новую
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.0/cert-manager.yaml
```

> **Важно:** Проверить [release notes](https://github.com/cert-manager/cert-manager/releases) на breaking changes.

---

## Безопасность

### RBAC для cert-manager

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

### Best Practices

| Практика | Описание |
| :--- | :--- |
| **Изоляция namespace** | Устанавливать cert-manager в отдельный namespace |
| **Ограниченный доступ** | RBAC на чтение Secret только для администраторов |
| **Мониторинг** | Алерты на истечение сертификатов |
| **Rotation ключей** | Регулярная ротация ACME-ключей и CA |
| **Audit логи** | Включить аудит Kubernetes API для cert-manager |

---

## Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Garbage collection | **10** | Официальная документация cert-manager.io |
| Prometheus-метрики | **10** | Встроены в cert-manager с версии 0.11 |
| Troubleshooting | **9** | Основано на официальной документации и опыте |
| Backup/Restore | **9** | Стандартная практика Kubernetes |

---
