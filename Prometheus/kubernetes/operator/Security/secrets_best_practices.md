# Управление секретами в Prometheus Operator

## Определения

**Secrets Management** — безопасное хранение и использование чувствительных данных в Prometheus Operator: webhook-URL, routing keys, пароли, TLS-сертификаты.

> **Навигация:** [Главная Security](./index.md) | [Контроль доступа](./access_control.md)

---

## Basic Concepts

### Типы секретов в Prometheus Operator

| Тип | Примеры | Где используются |
|---|---|---|
| **Receiver credentials** | Slack webhook, PagerDuty key, SMTP password | AlertmanagerConfig receivers |
| **TLS-сертификаты** | CA, client cert/key | ServiceMonitor tlsConfig, Ingress TLS |
| **Admin credentials** | Grafana admin user/password | Grafana Deployment |
| **Basic Auth** | htpasswd file, username/password | Prometheus/Alertmanager Ingress auth |

### Механизмы хранения

| Механизм | Описание | Когда использовать |
|---|---|---|
| **Kubernetes Secret (Opaque)** | Base64-encoded, хранится в etcd | Базовый вариант, внутренний контур |
| **External Secrets (Vault, SOPS)** | Секреты во внешнем хранилище, синхронизация в кластер | Production, compliance-требования |
| **Sealed Secrets** | Зашифрованные Secret-манифесты, хранятся в Git | GitOps без внешнего хранилища |

### Безопасность Kubernetes Secrets

- Secrets хранится в etcd в **base64** (не шифруется по умолчанию)
- Для шифрования требуется `EncryptionConfiguration` на API-сервере
- Доступ контролируется через **RBAC** (Role/RoleBinding к `secrets`)
- Секреты монтируются в Pod как **tmpfs** (не записываются на диск)

> **Подробно:** [Kubernetes Secret для Alertmanager](../../examples/alertmanager-karma-manifests-tutorial/secrets.md) — tutorial по созданию Secret для Alertmanager.

---

## Practical Scenarios

### Secrets Management

#### Хранение чувствительных данных

```bash
# Slack webhook
kubectl create secret generic slack-webhook \
  --from-literal=url='https://hooks.slack.com/services/xxx/yyy/zzz' \
  -n monitoring

# PagerDuty routing key
kubectl create secret generic pagerduty-secret \
  --from-literal=routing-key='your-routing-key' \
  -n monitoring

# SMTP password
kubectl create secret generic smtp-secret \
  --from-literal=password='your-smtp-password' \
  -n monitoring
```

---

#### Использование в AlertmanagerConfig

```yaml
receivers:
  - name: 'slack'
    slackConfigs:
      - channel: '#monitoring'
        apiURL:
          name: slack-webhook
          key: url
```

---

## Security Best Practices

### Хранение секретов

1. **Не храните секреты в plain text в манифестах** — используйте `kubectl create secret` или External Secrets Operator.
2. **Включите EncryptionConfiguration** для шифрования Secrets в etcd (AES-CBC или aescbc).
3. **Ограничьте доступ к Secrets через RBAC** — отдельные Role/RoleBinding только для namespace `monitoring`.

### Использование в конфигурации

1. **Используйте `secretKeyRef` вместо hardcode** — монтируйте секреты через environment variables или volume mounts.
2. **Отдельный Secret на каждый тип** — не объединяйте Slack, PagerDuty, SMTP в одном Secret.
3. **Не логируйте значения секретов** — убедитесь, что лог-уровень не выводит содержимое env-переменных.

### Ротация и мониторинг

1. **Ротируйте секреты минимум раз в 90 дней** — автоматизируйте через External Secrets Operator + Vault.
2. **Мониторьте доступ к Secrets** — audit-лог Kubernetes API (`watch`/`get` на `secrets`).
3. **Исключите секреты из Git** — `.gitignore` для файлов с реальными значениями; используйте SOPS или Sealed Secrets для GitOps.

---

## Additional Information

> **См. также:** [Kubernetes Secret для Alertmanager](../../examples/alertmanager-karma-manifests-tutorial/secrets.md) — tutorial по созданию Secret; [High Availability](../high_availability.md) — HA конфигурация; [Prometheus CRD](../crd/prometheus.md) — описание Prometheus CRD.
