# Предотвращение истечения SSL-сертификатов в Kubernetes

## Определения

**SSL/TLS Rotation (Ротация сертификатов)** — процесс планового обновления цифровых сертификатов до истечения их срока действия. В Kubernetes ротация должна быть автоматизирована для обеспечения непрерывности работы (High Availability) и исключения человеческого фактора.

**Kubelet Serving Certificate** — сертификат, используемый агентом `kubelet` для идентификации себя при входящих запросах от API-сервера (например, при командах `kubectl logs`, `exec`, `metrics-server`). По умолчанию часто не ротируется автоматически без специальной настройки.

**CSR (Certificate Signing Request) Approver** — контроллер или процесс, ответственный за автоматическую проверку и одобрение запросов на подпись сертификатов. Без него автоматизация ротации на уровне узлов (особенно серверных сертификатов Kubelet) невозможна.

**ARI (ACME Renewal Information)** — расширение протокола ACME, позволяющее центру сертификации (например, Let's Encrypt) рекомендовать клиенту (cert-manager) оптимальное время для продления сертификата, основываясь на нагрузке или технических работах на стороне CA.

**Certificate Validity Period (v1.31+)** — настраиваемый параметр в конфигурации `kubeadm` (v1beta4), позволяющий определить срок действия выпускаемых сертификатов (ранее был жестко ограничен 1 годом).

## Основные концепции

Стратегия защиты от истечения сертификатов в Kubernetes строится на трех независимых эшелонах:

### 1. Эшелон инфраструктуры (Control Plane и etcd)
Самый критический уровень. Истечение сертификата API-сервера или etcd приводит к потере управления кластером ("cluster bricking").
*   **Метод:** Плановые обновления версии кластера (автоматический `renew`) или принудительное продление через `kubeadm`.
*   **etcd:** Особое внимание требует встроенный etcd. Если etcd вынесен за пределы управления `kubeadm`, его сертификаты должны управляться внешними средствами (Ansible, Terraform, Vault).
*   **Доверие:** Корневые сертификаты (CA) имеют срок действия 10 лет, листовые — по умолчанию 1 год.

### 2. Эшелон узлов (Kubelet)
Обеспечивает связь между API и агентами на узлах.
*   **Client Certs:** Используются для авторизации узла в API. Обновляются автоматически при включенном параметре `rotateCertificates: true` (стандарт для современных дистрибутивов).
*   **Server Certs:** Требуются для безопасного сбора метрик и логов. Требуют настройки `serverTLSBootstrap: true` и наличия аппрувера в кластере.

### 3. Эшелон приложений
Сертификаты для Ingress, Gateway API и внутренних mTLS-соединений (Service Mesh).
*   **Метод:** Полная автоматизация через ACME/Vault с использованием `cert-manager`.

## Практические сценарии

### 1. Управление сроками действия в современных кластерах (v1.31+)

Начиная с версии 1.31 (API `kubeadm.k8s.io/v1beta4`), можно превентивно увеличить срок действия сертификатов, чтобы снизить частоту регламентных работ.

**Настройка через ClusterConfiguration:**
```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
certificateValidityPeriod: 43800h    # Листовые сертификаты на 5 лет
caCertificateValidityPeriod: 87600h   # CA на 10 лет
encryptionAlgorithm: ECDSA-P256       # Использование современных алгоритмов (опционально)
```
*Примечание: Использование ECDSA повышает производительность TLS-хендшейков и безопасность по сравнению с RSA.*

### 2. Автоматизация ротации Control Plane (kubeadm)

В кластерах под управлением `kubeadm` основным методом продления является регулярное обновление минорной версии (Upgrade).

*   **Проверка (Check-point):**
    ```bash
    sudo kubeadm certs check-expiration
    ```
*   **Принудительное продление:**
    Если обновление кластера невозможно, сертификаты продлеваются командой:
    ```bash
    sudo kubeadm certs renew all
    ```
    *Важно: После продления необходим перезапуск компонентов. Kubelet перезапустит поды API-сервера автоматически при изменении манифестов в `/etc/kubernetes/manifests`.*

Подробная инструкция по ручному управлению: **[Управление сертификатами через kubeadm](./certificate_management.md)**.

### 3. Настройка автоматической ротации для Kubelet

Для исключения ручного вмешательства необходимо убедиться, что Kubelet настроен на самообслуживание.

**Шаг 1: Настройка конфигурации (`kubelet-config.yaml`)**
```yaml
kind: KubeletConfiguration
serverTLSBootstrap: true
rotateCertificates: true
```

**Шаг 2: Автоматизация одобрения (CSR Approver)**
Для автоматического одобрения серверных сертификатов (Serving Certs) используйте один из методов:
1.  **kubelet-csr-approver:** Легковесный контроллер, проверяющий SAN (DNS/IP) в запросе на соответствие реальному статусу узла.
2.  **cert-manager (CSI Driver):** Позволяет Kubelet получать сертификаты напрямую из внешней PKI (например, Vault).

**Верификация ротации:**
```bash
# Проверка наличия активных CSR
kubectl get csr

# Проверка срока действия сертификата на узле
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -text -noout | grep "Not After"
```

### 4. Настройка cert-manager для приложений

Для предотвращения истечения сертификатов (например, Let's Encrypt) используйте связку `duration`, `renewBefore` и механизмы ARI.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-tls
spec:
  secretName: api-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  duration: 2160h # 90 дней
  renewBefore: 360h # Начать продление за 15 дней до конца срока
  dnsNames:
  - api.example.com
```

**Использование ARI (ACME Renewal Information, v1.15+):**
`cert-manager` автоматически интегрируется с ARI. Если CA сигнализирует о необходимости перевыпуска (например, из-за массового отзыва), `cert-manager` проигнорирует `renewBefore` и обновит сертификат в рекомендованное CA окно. Это критично для предотвращения простоев при инцидентах безопасности на стороне CA.

## Мониторинг и оповещения

Мониторинг — это последняя линия обороны. Не полагайтесь только на автоматику.

### Метрики инфраструктуры (Prometheus)
Для мониторинга файлов в `/etc/kubernetes/pki` используйте специализированные экспортеры:
1.  **x509-certificate-exporter:** Сканирует директории с сертификатами и отдает метрики `x509_cert_not_after`.
2.  **Kube-state-metrics:** Для мониторинга объектов `Certificate` (cert-manager).

### Алертинг (Prometheus Rules)
```yaml
# Алерт для сертификатов в файловой системе (через x509-exporter)
- alert: KubernetesControlPlaneCertExpiring
  expr: x509_cert_not_after{filepath=~"/etc/kubernetes/pki/.*"} - time() < 30 * 86400
  for: 1h
  labels:
    severity: critical
  annotations:
    summary: "Сертификат Control Plane {{ $labels.filepath }} истекает менее чем через 30 дней"

# Алерт для cert-manager
- alert: cert-managerCertExpiringSoon
  expr: certmanager_certificate_expiration_timestamp_seconds - time() < (21 * 24 * 3600)
  for: 1h
  labels:
    severity: warning
```

### Внешний мониторинг (Blackbox Exporter)
Проверка SSL "снаружи" через Ingress/LoadBalancer.
```yaml
- alert: SSLCertificateExpiring
  expr: probe_ssl_earliest_cert_expiry - time() < 86400 * 14
  for: 10m
  labels:
    severity: critical
```
Подробности: **[Blackbox Exporter: Метрики и алертинг](../../Prometheus/Exporters/blackbox/blackbox_exporter_metrics_and_alerting.md)**.

## Дополнительная информация

### Белые пятна и нюансы

*   **Внешний etcd:** Если ваш etcd запущен вне Kubernetes (например, на отдельных ВМ), `kubeadm certs renew` **не затронет** его. Вам нужно настроить отдельный пайплайн ротации для etcd.
*   **ServiceAccount Tokens:** Хотя это не SSL-сертификаты, токены (Bound ServiceAccount Tokens, v1.24+) имеют срок действия. Следите за алертами `serviceaccount_tokens_expiration` в API-сервере.
*   **Admin Kubeconfig:** Сертификат в `admin.conf` (используемый `kubectl`) также истекает через год. Его нужно обновлять вручную после ротации через `kubeadm`.

### Лучшие практики

| Рекомендация | Техническое обоснование |
| :--- | :--- |
| **Короткие сроки (Short-lived)** | Используйте сертификаты на 24-48 часов (через Vault), чтобы сделать процесс ротации регулярным и проверяемым ("rotation as a normal state"). |
| **Изоляция CA** | Не используйте Cluster CA для приложений. Это позволяет ротировать прикладные сертификаты без риска для инфраструктуры. |
| **Автоматические апгрейды** | Используйте инструменты типа **Kured** или операторы обслуживания для регулярного обновления кластера, что автоматически решает проблему ротации. |
| **Централизация в Vault** | Для Enterprise-сред используйте HashiCorp Vault как бэкенд для cert-manager, чтобы иметь единую точку аудита всех выпущенных сертификатов. |

### Связанные темы

* [Управление сертификатами через kubeadm](./certificate_management.md) — детальные команды и таблицы файлов.
* [Обновление кластера](./upgrading_clusters.md) — процедура `kubeadm upgrade`.
* [Cert-manager: Операции](../ToolsUtilities/cert_manager/Administration/operations.md) — мониторинг и поддержка контроллера.
* [TLS и mTLS в Kubernetes](../Security/tls_and_mtls_in_kubernetes.md) — концепции безопасности соединений.
