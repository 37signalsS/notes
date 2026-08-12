# Управление секретами в Prometheus Operator

## Определения

**Управление секретами** — комплекс процессов по обеспечению жизненного цикла конфиденциальных данных (паролей, токенов, сертификатов) в стеке мониторинга. В Kubernetes-среде это включает безопасное хранение в `etcd`, динамическую доставку в поды через тома (Volumes) и интеграцию с внешними системами управления ключами (KMS).

**Secret SSoT Pattern** — стратегия «единого источника истины», при которой секреты не хранятся в Git в открытом виде, а синхронизируются из внешних источников (например, Vault) напрямую в Kubernetes через специализированные контроллеры, что исключает попадание открытых данных в Git.

---

## Основные концепции

### Типы секретов в экосистеме Operator

| Тип | Назначение | Основной ресурс (CRD) |
|:---|:---|:---|
| **Auth Credentials** | Токены Basic Auth, OAuth2 Client ID/Secret | `ServiceMonitor`, `ScrapeConfig` |
| **Alerting Config** | Webhooks (Slack, Telegram), SMTP, PagerDuty | `AlertmanagerConfig` |
| **TLS/mTLS** | CA сертификаты, клиентские ключи/сертификаты | `Prometheus` (web), `ServiceMonitor` |
| **Storage Auth** | Конфигурация доступа к S3/GCS/Azure | `Prometheus` (Thanos Sidecar) |

### Механизмы автоматизации и ротации (2025–2026)

Современная инфраструктура требует минимизации ручного управления секретами:

*   **External Secrets Operator (ESO):** Стандарт для синхронизации секретов из облачных KMS (AWS KMS, GCP KMS) или Vault. Поддерживает автоматическое обновление K8s Secret при изменении в источнике.
*   **Automatic Hot Reload:** Prometheus Operator внедряет sidecar `config-reloader`, который отслеживает изменения в примонтированных секретах и вызывает `/-/reload` без перезапуска пода.
*   **CSI Secrets Store:** Позволяет монтировать секреты напрямую из внешних хранилищ в файловую систему пода, минуя создание объекта `Secret` в Kubernetes.

---

## Практические сценарии

### Использование ScrapeConfig с OAuth2 ротацией

`ScrapeConfig` (v0.65.0+) позволяет гибко настраивать авторизацию для внешних сервисов. При обновлении секрета `config-reloader` автоматически обновит путь к `client_secret_file`.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: secure-api-scrape
spec:
  staticConfigs:
    - targets: ["api.corp.local"]
  oauth2:
    clientId:
      secret: { name: oauth-creds, key: id }
    clientSecret:
      name: oauth-creds
      key: secret
    tokenUrl: https://auth.corp.local/token
```

### Безопасный доступ к объектному хранилищу Thanos

Для защиты данных в S3 рекомендуется избегать статических ключей (`access_key`), используя **IRSA (AWS)** или **Workload Identity (GCP)**.

1.  **Конфигурация (objstore.yml):**
    ```yaml
    type: S3
    config:
      bucket: "thanos-metrics"
      endpoint: "s3.us-east-1.amazonaws.com"
      sse_config:
        type: "SSE-KMS" # Шифрование на стороне S3 с помощью KMS
        kms_key_id: "arn:aws:kms:..."
    ```
2.  **Привязка к CRD:**
    ```yaml
    spec:
      thanos:
        objectStorageConfig:
          name: thanos-objstore-secret
          key: objstore.yml
    ```

### Автоматическая ротация через ESO и Vault

Сценарий, при котором пароль Alertmanager обновляется в Vault и автоматически доставляется в мониторинг.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: alertmanager-vault-sync
spec:
  refreshInterval: 1h # Частота проверки обновлений
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: alertmanager-main-creds
  data:
    - secretKey: slack_url
      remoteRef:
        key: secret/monitoring/alerts
        property: slack_webhook
```

---

## Рекомендации по безопасности

### Защита на уровне инфраструктуры

1. **Encryption at Rest:** Обязательное включение шифрования `etcd` в Kubernetes через `EncryptionConfiguration` с использованием KMS плагина.
2. **Minimal RBAC:** Ограничение прав `watch/list` на секреты в неймспейсе `monitoring`. Только ServiceAccount оператора должен иметь доступ к чтению конфигурационных секретов.
3. **Network Isolation:** Использование Network Policies для запрета доступа к портам Prometheus/Alertmanager извне кластера без авторизации.

### Эксплуатация и Hardening

1. **Read-Only Mounts:** При монтировании секретов в `spec.secrets` всегда используйте `readOnly: true` в настройках контейнера (через `securityContext`).
2. **Исключение Env Vars:** Никогда не передавайте секреты через переменные окружения, так как они логируются и доступны через `/proc`. Используйте только файловое монтирование.
3. **Аудит ротации:** Настройте мониторинг метрики `prometheus_config_last_reload_success_timestamp_seconds` для подтверждения успешного применения новых секретов.

---

## Дополнительная информация

- **[Безопасность (Главная)](./index.md)** — архитектура защиты стека.
- **[Контроль доступа](./access_control.md)** — NetworkPolicy и RBAC.
- **[Внешние менеджеры секретов](../../../Kubernetes/Base/secrets/external_managers.md)** — интеграция с Vault и ESO.
