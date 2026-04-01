# Управление сертификатами Kubernetes через kubeadm

## Определения

**kubeadm** — утилита для управления жизненным циклом сертификатов Control Plane в кластерах, развёрнутых через `kubeadm init`.

**CA (Certificate Authority)** — корневой центр сертификации, подписывающий все сертификаты кластера. Подробнее: [PKI Overview](../../Security/Concepts/pki_overview.md).

**mTLS** — взаимная аутентификация компонентов через сертификаты. Подробнее: [TLS и mTLS в Kubernetes](../Security/tls_and_mtls_in_kubernetes.md).

### Ключевые сертификаты Control Plane

| Сертификат | Назначение | Подписан |
| :--- | :--- | :--- |
| **ca.crt** (Root CA) | Подпись всех сертификатов K8s | Self-signed |
| **etcd/ca.crt** (etcd CA) | Подпись сертификатов etcd | Self-signed |
| **front-proxy-ca.crt** | Подпись сертификатов front-proxy | Self-signed |
| **apiserver.crt** | API Server для клиентов | ca |
| **apiserver-kubelet-client.crt** | API Server → kubelet | ca |
| **apiserver-etcd-client.crt** | API Server → etcd | etcd-ca |
| **etcd/server.crt** | etcd Server для клиентов | etcd-ca |
| **kubelet.crt** | Kubelet для API Server | ca |

## Основные концепции

### Срок действия сертификатов

| Тип сертификата | Срок действия | Обновляется через kubeadm |
| :--- | :--- | :--- |
| **Корневые CA** (`ca.crt`, `etcd/ca.crt`, `front-proxy-ca.crt`) | 10 лет | ❌ Нет |
| **Сертификаты компонентов** (`apiserver`, `kubelet-client`, `etcd-server`) | 1 год | ✅ Да |
| **Admin kubeconfig** (`admin.conf`) | 1 год | ✅ Да |

> **Важно:** Истечение сертификатов — частая причина отказа кластера. Компоненты Control Plane не смогут взаимодействовать, кластер перестанет функционировать.

### Требования для управления через kubeadm

Для управления сертификатами `etcd` через `kubeadm`:

* **Ручная установка:** `kubeadm init` по умолчанию управляет etcd.
* **Kubespray:** Требуется `etcd_kubeadm_enabled: true` в inventory.
* **Другие инструменты:** Проверить документацию инструмента.

### Настройка сроков действия

С версии `kubeadm.k8s.io/v1beta4` сроки настраиваются в конфигурации:

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
certificateValidityPeriod: 8760h      # leaf-сертификаты, по умолчанию 1 год
caCertificateValidityPeriod: 87600h   # CA-сертификаты, по умолчанию 10 лет
```

## Практические сценарии

Все команды выполняются на одном из узлов Control Plane.

### Проверка срока действия

```bash
# Проверка всех сертификатов
sudo kubeadm certs check-expiration
```

**Пример вывода:**

```
CERTIFICATE                EXPIRES                  RESIDUAL TIME   CERTIFICATE AUTHORITY   EXTERNALLY MANAGED
admin.conf                 Feb 27, 2027 10:00 UTC   364d            -                       no
apiserver                  Feb 27, 2027 10:00 UTC   364d            ca                      no
apiserver-etcd-client      Feb 27, 2027 10:00 UTC   364d            etcd-ca                 no
apiserver-kubelet-client   Feb 27, 2027 10:00 UTC   364d            ca                      no
...
etcd-server                Feb 27, 2027 10:00 UTC   364d            etcd-ca                 no
```

> **Примечание:** Корневые CA не отображаются, так как не управляются `kubeadm`.

### Обновление сертификатов

**Обновление всех сертификатов:**

```bash
sudo kubeadm certs renew all
```

**Обновление отдельного сертификата:**

```bash
# API Server
sudo kubeadm certs renew apiserver

# Kubelet client
sudo kubeadm certs renew apiserver-kubelet-client

# etcd server
sudo kubeadm certs renew etcd-server

# etcd client (API Server → etcd)
sudo kubeadm certs renew apiserver-etcd-client
```

> **Важно:** После обновления требуется перезапуск компонентов Control Plane.

### Применение новых сертификатов

После обновления требуется перезапуск компонентов Control Plane.

**Способ 1: Автоматический через kubelet (рекомендуется)**

Компоненты запущены как статические поды. Kubelet автоматически перезапустит их:

```bash
# Проверка статуса
kubectl get pods -n kube-system

# При необходимости — restart kubelet
sudo systemctl restart kubelet
```

**Способ 2: Ручной через манифесты**

```bash
# Создать временную директорию
mkdir /tmp/k8s-manifests-backup/

# Переместить манифесты
sudo mv /etc/kubernetes/manifests/*.yaml /tmp/k8s-manifests-backup/

# Подождать 15-20 секунд
sleep 20

# Вернуть манифесты
sudo mv /tmp/k8s-manifests-backup/*.yaml /etc/kubernetes/manifests/
```

### Troubleshooting

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **Сертификаты истекли** | `kubeadm certs check-expiration` | `kubeadm certs renew all` + restart |
| **etcd не подключается** | `kubectl get pods -n kube-system` | Проверить `apiserver-etcd-client` |
| **kubelet не авторизуется** | `journalctl -u kubelet` | Проверить `apiserver-kubelet-client` |
| **Cluster не отвечает** | `curl -k https://localhost:6443/healthz` | Проверить `apiserver` сертификат |
| **x509: certificate expired** | `openssl x509 -in <cert> -text -noout` | Обновить + перезапустить компоненты |

## Дополнительная информация

> **Примечание:** При обновлении кластера Kubernetes необходимо проверить и обновить сертификаты. Подробнее в разделе [Обновление кластера](upgrading_clusters.md).

### Best Practices

| Практика | Описание |
| :--- | :--- |
| **Мониторинг expiration** | Проверка за 30 дней до истечения |
| **Backup перед обновлением** | `cp -r /etc/kubernetes/pki /backup/pki-$(date +%F)` |
| **Тестирование в staging** | Сначала обновить на тестовом кластере |
| **Автоматизация** | CronJob для проверки + alerting |
| **Документирование** | Фиксация даты обновления и остаточного времени |

### Автоматизация проверки

**CronJob для ежедневной проверки (с доступом к хост-сертификатам):**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cert-expiration-check
  namespace: kube-system
  labels:
    app: cert-check
spec:
  schedule: "0 9 * * *"  # Ежедневно в 9:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: check
            image: bitnami/kubectl:1.32
            command:
            - /bin/sh
            - -c
            - |
              echo "=== Certificate Expiration Check ==="
              echo "Date: $(date)"
              echo ""
              # Проверка сертификатов через kubeadm (требует доступа к хосту)
              if [ -f /host/etc/kubernetes/pki/ca.crt ]; then
                echo "CA Certificate:"
                openssl x509 -in /host/etc/kubernetes/pki/ca.crt -noout -dates
                echo ""
                echo "API Server Certificate:"
                openssl x509 -in /host/etc/kubernetes/pki/apiserver.crt -noout -dates
              else
                echo "WARNING: Certificates not found on host path"
              fi
            volumeMounts:
            - name: kubernetes-pki
              mountPath: /host/etc/kubernetes/pki
              readOnly: true
          volumes:
          - name: kubernetes-pki
            hostPath:
              path: /etc/kubernetes/pki
              type: Directory
          restartPolicy: OnFailure
          nodeSelector:
            node-role.kubernetes.io/control-plane: ""
          tolerations:
          - key: node-role.kubernetes.io/control-plane
            operator: Exists
            effect: NoSchedule
```

> **Важно:** CronJob требует доступа к hostPath `/etc/kubernetes/pki` для чтения сертификатов. Альтернативно — использовать `kubeadm certs check-expiration` через DaemonSet с доступом к `/etc/kubernetes`.

### Ограничения kubeadm

* `kubeadm` **не управляет** сертификатами, подписанными внешним CA
* Ротация CA-сертификатов **не поддерживается** автоматически (требуется ручная ротация)
* Kubelet client certificate обновляется автоматически через `/var/lib/kubelet/pki/`
* Kubelet serving certificate по умолчанию self-signed (требуется `serverTLSBootstrap: true` для подписи через API)

### Связанные темы

* [kubeadm: Кластер инициализация](../Installation/kubeadm/cluster_initialization.md) — `--upload-certs` для HA
* [Обновление кластера](upgrading_clusters.md) — при обновлении проверка и обновление сертификатов
* [Kubespray: Cluster Management](../Installation/Kubespray/cluster_management.md)
* [PKI Overview](../../Security/Concepts/pki_overview.md) — теория PKI
* [TLS и mTLS в Kubernetes](../Security/tls_and_mtls_in_kubernetes.md) — теория TLS в K8s
* [cert-manager](../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) — автоматизация сертификатов в Kubernetes
