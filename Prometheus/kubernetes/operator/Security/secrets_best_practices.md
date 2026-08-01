# Управление секретами в Prometheus Operator

## Определения

**Управление секретами** — жизненный цикл конфиденциальных данных (паролей, токенов, сертификатов) в стеке мониторинга. Включает в себя безопасное хранение, автоматическую доставку в поды Prometheus/Alertmanager и интеграцию с внешними системами управления ключами (KMS).

**Secret SSoT Pattern** — стратегия, при которой секреты не хранятся в Git в открытом виде, а синхронизируются из внешних источников (например, Vault) напрямую в Kubernetes через специализированные операторы.

> **Навигация:** [Главная Security](./index.md) | [Контроль доступа](./access_control.md) | **Надёжность: 10**

---

## Основные концепции

### Типы секретов в Prometheus Operator

| Тип | Примеры | Основной потребитель (CRD) |
|:---|:---|:---|
| **Auth Credentials** | Bearer tokens, OAuth2 Client ID/Secret | `ServiceMonitor`, `PodMonitor`, `ScrapeConfig` |
| **Alerting Config** | Slack Webhook, SMTP Pass, PagerDuty Key | `AlertmanagerConfig` |
| **TLS/mTLS** | CA certs, Client cert/key | `Prometheus` (web), `Alertmanager` (cluster), `ServiceMonitor` |
| **Storage Auth** | AWS/S3 access keys | `Prometheus` (Thanos Sidecar / Remote Write) |

### Механизмы хранения и автоматизация (2026)

Для обеспечения безопасности и соответствия стандартам (PCI DSS, SOC2) в современных инфраструктурах используются следующие подходы:

*   **External Secrets Operator (ESO):** Стандарт де-факто для синхронизации секретов из HashiCorp Vault, AWS Secrets Manager или Azure Key Vault. Секреты создаются в Kubernetes динамически.
*   **Sealed Secrets / SOPS:** Используются для хранения зашифрованных данных в Git (GitOps), но считаются менее гибкими по сравнению с ESO для управления ротацией.
*   **CSI Secrets Store:** Обеспечивает монтирование секретов напрямую в поды как файлов, минуя объект `Secret` в etcd Kubernetes.

> **Подробно:** [Внешние менеджеры секретов](../../../Kubernetes/Base/secrets/external_managers.md) — SSoT по интеграции Vault/ESO.

---

## Практические сценарии

### Создание секретов для алертинга

Секреты должны создаваться в том же неймспейсе, где находится ресурс `AlertmanagerConfig` (или в неймспейсе оператора, в зависимости от настроек прав).

```bash
# Создание секрета для Slack Webhook
kubectl create secret generic slack-webhook \
  --from-literal=url='https://hooks.slack.com/services/T000/B000/XXXX' \
  -n monitoring
# → secret/slack-webhook created
```

### Использование секретов в ScrapeConfig (OAuth2)

`ScrapeConfig` (введен в Operator v0.90+) является современным способом настройки сбора метрик с внешних эндпоинтов, требующих OAuth2 авторизации.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: external-api-secure
spec:
  staticConfigs:
    - targets: ["api.external-service.com"]
  oauth2:
    clientId:
      secret:
        name: oauth-api-creds
        key: client-id
    clientSecret:
      name: oauth-api-creds
      key: client-secret
    tokenUrl: https://auth.external-service.com/token
```

### Автоматическая синхронизация через External Secrets (ESO)

Паттерн для синхронизации ключа Alertmanager из HashiCorp Vault.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: slack-webhook-vault
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: slack-webhook # Итоговый K8s Secret
  data:
    - secretKey: url
      remoteRef:
        key: secret/monitoring/alertmanager
        property: webhook_url
```

### Настройка TLS для ServiceMonitor

Для сбора метрик с защищённых эндпоинтов сертификаты монтируются в под Prometheus через секреты. В современных версиях рекомендуется использование `keySecret` вместо прямых путей.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: secure-app
spec:
  endpoints:
    - port: https
      scheme: https
      tlsConfig:
        ca:
          secret: { name: app-tls-ca, key: ca.crt }
        cert:
          secret: { name: app-tls-client, key: tls.crt }
        keySecret:
          name: app-tls-client
          key: tls.key
```

---

## Рекомендации по безопасности

### Хранение и передача

1. **Запрет Plain Text:** Никогда не храните секреты в YAML-манифестах. Используйте GitOps с шифрованием (ESO + Vault).
2. **Сетевой контроль (eBPF):** Используйте eBPF-базируемые CNI (Cilium) для ограничения доступа к портам Prometheus/Alertmanager на уровне L7, предотвращая перехват трафика с секретами.
3. **RBAC Isolation:** Ограничивайте доступ к секретам в неймспейсе `monitoring`. Только оператор должен иметь права `watch` на объекты `secrets`.

### Эксплуатация и жизненный цикл

1. **Автоматическая ротация:** Настройте ротацию токенов и сертификатов через ESO или Vault. Убедитесь, что Prometheus Operator автоматически обнаруживает обновление (реконсиляция Secret).
2. **Аудит доступа:** Включите аудит Kubernetes API для всех операций с ресурсами `secrets` в неймспейсе мониторинга.
3. **Удаление устаревших ресурсов:** Переходите с `additionalScrapeConfigs` (в Secret-ах) на `ScrapeConfig` (в CRD), чтобы обеспечить гранулярный контроль доступа и валидацию.

## Дополнительная информация

- **[Безопасность (Главная)](./index.md)** — архитектура защиты стека.
- **[Контроль доступа](./access_control.md)** — NetworkPolicy и RBAC.
- **[Внешние менеджеры секретов](../../../Kubernetes/Base/secrets/external_managers.md)** — детальная интеграция с Vault/ESO.
- **[Безопасность Secret в Kubernetes](../../../Kubernetes/Base/secrets/security.md)** — фундаментальные основы защиты объектов Secret.
