# Предотвращение истечения SSL-сертификатов в Kubernetes

## Определения

**SSL/TLS Rotation (Ротация сертификатов)** — процесс планового обновления цифровых сертификатов до истечения их срока действия для обеспечения непрерывности работы сервисов.

**Kubelet Serving Certificate** — сертификат, используемый агентом `kubelet` для аутентификации входящих TLS-соединений (например, при выполнении команд `kubectl logs` или `kubectl exec`).

**ACME (Automated Certificate Management Environment)** — протокол автоматизации управления сертификатами, позволяющий автоматически выпускать и продлевать SSL-сертификаты без участия человека (используется Let's Encrypt).

## Основные концепции

Проблемы с истечением сертификатов в Kubernetes обычно распределяются по трём уровням:

1. **Инфраструктурный уровень (Control Plane):** Сертификаты API-сервера, etcd, планировщика и контроллеров. В кластерах `kubeadm` срок их действия по умолчанию составляет 1 год.
2. **Уровень узлов (Kubelet):** Клиентские сертификаты для аутентификации в API и серверные сертификаты для обслуживания запросов.
3. **Уровень приложений:** Сертификаты для внешних пользователей, терминируемые на Ingress-контроллерах, Gateway API или внутри Service Mesh.

**Основная стратегия предотвращения:** Переход от ручного мониторинга к автоматической ротации (Cert-manager, Kubelet Bootstrap) и внедрение многоуровневого алертинга.

## Практические сценарии

### 1. Инфраструктура (Control Plane)

В кластерах, развернутых через `kubeadm`, сертификаты обновляются автоматически при выполнении планового обновления версии Kubernetes (`kubeadm upgrade`).

* **Проверка срока действия:**

    ```bash
    sudo kubeadm certs check-expiration
    # → CERTIFICATE   EXPIRES   RESIDUAL TIME   ...
    ```

* **Ручное продление:**

    ```bash
    sudo kubeadm certs renew all
    # → [certs] Certificate for 'apiserver' renewed
    ```

Подробные инструкции и диагностика: [Управление сертификатами через kubeadm](./certificate_management.md).

### 2. Автопродление сертификатов Kubelet

По умолчанию `kubelet` генерирует самоподписанные серверные сертификаты. Для настройки автоматической ротации сертификатов, подписанных Cluster CA, необходимо включить поддержку в конфигурации.

**Настройка в `KubeletConfiguration`:**

```yaml
serverTLSBootstrap: true
```

**Процесс одобрения:**

1. Kubelet создает запрос на подпись (CSR).
2. CSR должен быть одобрен администратором:

   ```bash
   kubectl certificate approve <csr-name>
   # → certificatesigningrequest.certificates.k8s.io/<name> approved
   ```

3. После одобрения `kubelet` будет автоматически продлевать сертификат до его истечения.

### 3. Автоматизация для приложений (Cert-manager)

Для управления сертификатами Ingress и других ресурсов используется **cert-manager**.

**Настройка ротации в ресурсе `Certificate`:**
Параметр `renewBefore` определяет, за сколько времени до истечения (expiry) следует начать процесс продления.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: web-tls
spec:
  secretName: web-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  renewBefore: 360h # Начать продление за 15 дней до конца срока (360 часов)
  dnsNames:
  - example.com
```

Подробности использования: [Cert-manager: Сценарии Let's Encrypt](../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md).

### 4. Мониторинг и оповещения

Мониторинг является критическим слоем безопасности на случай сбоя автоматизации.

#### Метрики Cert-manager

При использовании Prometheus и cert-manager рекомендуется настроить алерт на время до истечения:

```yaml
# Алерт за 21 день до истечения
- alert: CertManagerCertExpiring
  expr: certmanager_certificate_expiration_timestamp_seconds - time() < (21 * 24 * 3600)
  labels:
    severity: warning
```

#### Внешний мониторинг (Blackbox Exporter)

Для проверки сертификатов на внешних эндпоинтах используется Blackbox Exporter.

```yaml
# Алерт за 14 дней до истечения
- alert: SSLCertExpiringSoon
  expr: probe_ssl_earliest_cert_expiry - time() < 86400 * 14
```

Подробный список правил и метрик: [Blackbox Exporter: Метрики и алертинг](../../Prometheus/Exporters/blackbox/blackbox_exporter_metrics_and_alerting.md).

## Дополнительная информация

### Лучшие практики

| Практика | Описание |
| :--- | :--- |
| **Отказ от ручных Secret** | Всегда используйте `cert-manager` или аналоги для создания TLS Secret. |
| **Тестирование (Staging)** | Используйте ACME Staging эндпоинты для отладки, чтобы избежать блокировок (Rate Limits) в Production. |
| **Многослойный мониторинг** | Сочетайте внутренний мониторинг (`kubeadm certs`, `cert-manager`) с внешними проверками (Blackbox). |
| **Резервное копирование CA** | Храните корневые ключи кластера в защищенном хранилище (HashiCorp Vault). |

### Связанные темы

* [Управление сертификатами через kubeadm](./certificate_management.md) — SSoT для инфраструктурных сертификатов.
* [Обновление кластера](./upgrading_clusters.md) — автоматическая ротация при обновлении.
* [Диагностика SSL сертификатов](../../Security/Tools/ssl_certificate_diagnostics.md) — инструменты проверки через CLI.
* [TLS и mTLS в Kubernetes](../Security/tls_and_mtls_in_kubernetes.md) — теоретические основы.
