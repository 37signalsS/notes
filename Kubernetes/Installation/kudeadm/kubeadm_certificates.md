# Управление сертификатами в kubeadm

> **Примечание:** Это файл содержит только kubeadm-специфичную информацию. Полное руководство по управлению сертификатами Kubernetes см. в [Управление сертификатами кластера](../../Operations/certificate_management.md) (SSoT).

## 1. Определения

| Термин | Описание |
| :--- | :--- |
| **CA (Certificate Authority)** | Корневой центр сертификации, подписывающий все сертификаты кластера. |
| **kubeadm-managed certificates** | Сертификаты, управляемые через `kubeadm certs` (срок действия 1 год). |
| **Long-lived CA** | Корневые CA сертификаты (срок действия 10 лет, не обновляются через `kubeadm`). |

## 2. Основные концепции

### 2.1. Типы сертификатов

| Тип | Срок действия | Управляется kubeadm |
| :--- | :--- | :--- |
| **Корневые CA** (`ca.crt`, `etcd/ca.crt`, `front-proxy-ca.crt`) | 10 лет | ❌ Нет |
| **Сертификаты компонентов** (`apiserver`, `kubelet-client`, `etcd-server`) | 1 год | ✅ Да |
| **Admin kubeconfig** (`admin.conf`) | 1 год | ✅ Да |

### 2.2. Требования для управления etcd-сертификатами

Для управления сертификатами `etcd` через `kubeadm`, кластер должен быть развёрнут с опцией управления etcd через kubeadm:

*   **При ручной установке:** `kubeadm init` по умолчанию управляет etcd.
*   **При использовании Kubespray:** `etcd_kubeadm_enabled: true` в inventory.

## 3. Практические сценарии

### 3.1. Проверка срока действия

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

> **Важно:** Сертификаты CA (`ca.crt`, `etcd/ca.crt`) не отображаются, так как не управляются `kubeadm`.

### 3.2. Обновление сертификатов

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
```

### 3.3. Применение новых сертификатов

После обновления требуется перезапуск компонентов Control Plane.

**Способ 1: Перезапуск через kubelet (рекомендуется)**

Компоненты Control Plane запущены как статические поды. Kubelet автоматически перезапустит их после обновления сертификатов.

```bash
# Проверка статуса подов
kubectl get pods -n kube-system

# При необходимости — ручной restart kubelet
sudo systemctl restart kubelet
```

**Способ 2: Ручной перезапуск через манифесты**

```bash
# Создать временную директорию
mkdir /tmp/k8s-manifests-backup/

# Переместить манифесты
sudo mv /etc/kubernetes/manifests/*.yaml /tmp/k8s-manifests-backup/

# Подождать 15-20 секунд (kubelet остановит поды)
sleep 20

# Вернуть манифесты
sudo mv /tmp/k8s-manifests-backup/*.yaml /etc/kubernetes/manifests/
```

### 3.4. Автоматизация ротации

**CronJob для автоматической проверки:**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cert-expiration-check
  namespace: kube-system
spec:
  schedule: "0 9 * * *"  # Ежедневно в 9:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: check
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              echo "Checking certificate expiration..."
              # Проверка выполняется на узле через hostPath
          restartPolicy: OnFailure
```

> **Примечание:** Полная автоматизация требует доступа к хост-файлам `/etc/kubernetes/pki`.

## 4. Дополнительная информация

### 4.1. Связанные темы

*   [Управление сертификатами кластера (SSoT)](../../Operations/certificate_management.md)
*   [Kubespray установка](../Kubespray/installation.md)
*   [etcd обслуживание](../../Concepts/etcd_overview.md)

### 4.2. Troubleshooting

| Проблема | Решение |
| :--- | :--- |
| **Сертификаты истекли** | `kubeadm certs renew all` + перезапуск компонентов |
| **etcd не подключается** | Проверить `apiserver-etcd-client` сертификат |
| **kubelet не авторизуется** | Проверить `apiserver-kubelet-client` |
| **Cluster не отвечает** | Проверить `apiserver` сертификат |

### 4.3. Best Practices

| Практика | Описание |
| :--- | :--- |
| **Мониторинг expiration** | Проверка за 30 дней до истечения |
| **Backup перед обновлением** | `cp -r /etc/kubernetes/pki /backup/pki-$(date +%F)` |
| **Тестирование в staging** | Сначала обновить на тестовом кластере |
| **Документирование** | Фиксация даты обновления и остаточного времени |
