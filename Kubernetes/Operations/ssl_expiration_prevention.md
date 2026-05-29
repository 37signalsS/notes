# Предотвращение истечения SSL-сертификатов в Kubernetes

## Определения

**SSL/TLS Rotation** — процесс автоматического или ручного обновления сертификатов до истечения их срока действия.

**Kubelet Serving Certificate** — сертификат, используемый kubelet для обработки входящих TLS-соединений (например, от API Server для `logs`, `exec`).

**ACME (Automated Certificate Management Environment)** — протокол автоматизации выпуска и продления SSL-сертификатов (используется Let's Encrypt).

## Основные концепции

Проблемы с истечением сертификатов в Kubernetes обычно делятся на три уровня:

1. **Инфраструктурный уровень (Control Plane):** сертификаты API Server, etcd, scheduler. По умолчанию действуют 1 год.
2. **Уровень узлов (Kubelet):** клиентские сертификаты для подключения к API и серверные сертификаты для метрик/логов.
3. **Уровень приложений (Ingress/Services):** сертификаты для внешних пользователей, управляемые через Ingress-контроллеры или Service Mesh.

**Основная стратегия предотвращения проблем:** переход от ручного управления к автоматизации (Cert-manager, Kubelet Bootstrap) и внедрение проактивного мониторинга.

## Практические сценарии

### 1. Control Plane (Инфраструктура)

Если кластер развернут через `kubeadm`, сертификаты обновляются автоматически при обновлении версии Kubernetes (`kubeadm upgrade`).

**Ручная проверка и обновление:**

* **Проверка:** `sudo kubeadm certs check-expiration`
* **Обновление:** `sudo kubeadm certs renew all`

Подробные инструкции по ротации инфраструктурных сертификатов см. в [Управление сертификатами через kubeadm](./certificate_management.md).

### 2. Автопродление сертификатов Kubelet

По умолчанию Kubelet генерирует самоподписанные серверные сертификаты. Для автоматической ротации сертификатов, подписанных Cluster CA, необходимо включить `serverTLSBootstrap`.

**Настройка в KubeletConfiguration:**

```yaml
serverTLSBootstrap: true
```

**Процесс:**

1. Kubelet создает запрос на подпись (CSR) при запуске.
2. Администратор (или контроллер) должен одобрить CSR: `kubectl certificate approve <csr-name>`.
3. После одобрения Kubelet автоматически обновляет сертификат до истечения срока.

### 3. Автоматизация для приложений (Cert-manager)

Для приложений (Ingress, Gateway API) стандартом является использование **cert-manager**.

**Ключевые настройки для надежности:**

* **Issuer/ClusterIssuer:** настройте несколько способов проверки (HTTP-01 для внешних, DNS-01 для внутренних/wildcard).
* **RenewBefore:** параметр в ресурсе `Certificate`, определяющий, за сколько времени до истечения начинать продление (по умолчанию 30 дней).

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: example-com
spec:
  secretName: example-com-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  renewBefore: 360h # Начать продление за 15 дней (360ч)
  dnsNames:
  - example.com
```

Подробные сценарии использования см. в [Cert-manager Scenarios](../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md).

### 4. Мониторинг и алертинг

Автоматизация может дать сбой (например, из-за изменения DNS-записей или проблем с API Let's Encrypt). Мониторинг является обязательным последним рубежом обороны.

#### Prometheus-метрики

При использовании cert-manager мониторьте метрику:
`certmanager_certificate_expiration_timestamp_seconds - time() < (21 * 24 * 3600)` — алерт за 21 день.

#### Внешний мониторинг

Используйте специализированные экспортеры для проверки внешних эндпоинтов (например, **Blackbox Exporter**):

```yaml
- alert: SSLCertExpiringSoon
  expr: probe_ssl_earliest_cert_expiry - time() < 86400 * 14
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "SSL сертификат на {{ $labels.instance }} истекает через 14 дней"
```

## Best Practices

| Практика | Описание |
| :--- | :--- |
| **Автоматизация через cert-manager** | Исключите ручное создание Secret с сертификатами для Ingress. |
| **Использование staging ACME** | Всегда тестируйте выпуск сертификатов через Let's Encrypt Staging, чтобы избежать Rate Limits. |
| **Срок RenewBefore** | Устанавливайте `renewBefore` достаточным для ручного вмешательства (минимум 15-30 дней). |
| **Мониторинг Control Plane** | Настройте CronJob для регулярного запуска `kubeadm certs check-expiration`. |
| **Backup CA** | Храните резервные копии корневых CA и приватных ключей в зашифрованном виде (Vault, Ansible Vault). |

## Дополнительная информация

* [Управление сертификатами через kubeadm](./certificate_management.md) — SSoT для инфраструктуры.
* [Операции Cert-manager](../ToolsUtilities/cert_manager/Administration/operations.md) — мониторинг и алерты для cert-manager.
* [Диагностика Cert-manager](../ToolsUtilities/cert_manager/Administration/troubleshooting.md) — что делать, если автопродление не сработало.
* [TLS и mTLS в Kubernetes](../Security/tls_and_mtls_in_kubernetes.md) — теоретические основы.
