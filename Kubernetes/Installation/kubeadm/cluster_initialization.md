# Инициализация кластера через kubeadm

## Определения

**kubeadm init** — команда для инициализации первого узла Control Plane и создания управляющих компонентов кластера.

**kubeadm join** — команда для присоединения новых узлов (как мастеров, так и воркеров) к существующему кластеру.

**Control Plane Endpoint** — стабильная точка входа (Virtual IP (VIP), DNS-имя или адрес балансировщика) для доступа к API-серверу.

**pod-network-cidr** — диапазон IP-адресов, выделяемый для сети подов. Должен быть уникальным в рамках инфраструктуры.

**service-cidr** — диапазон IP-адресов для внутренних сервисов Kubernetes (ClusterIP).

**CRI (Container Runtime Interface)** — интерфейс взаимодействия Kubernetes со средой выполнения контейнеров (например, containerd).

**CNI (Container Network Interface)** — интерфейс сетевых плагинов, обеспечивающих связность между подами.

---

## Основные концепции

### Процесс и этапы инициализации

Инициализация кластера — это последовательный процесс, который начинается на первом мастере и расширяется на другие узлы.

**Последовательность действий:**

1. Выполнение `kubeadm init` на первом узле Control Plane.
2. Настройка `kubeconfig` для управления кластером через `kubectl`.
3. Установка CNI-плагина (без него узлы останутся в статусе `NotReady`).
4. Присоединение дополнительных мастеров через `kubeadm join --control-plane`.
5. Присоединение рабочих узлов (Worker Nodes) через `kubeadm join`.

**Внутренние этапы `kubeadm init`:**

- **Pre-flight checks** — проверка соответствия системы требованиям (CPU, RAM, swap, порты).
- **Certs generation** — создание TLS-сертификатов для API-сервера, etcd и других компонентов.
- **Kubeconfig generation** — создание конфигурационных файлов для компонентов и администратора.
- **Control plane preparation** — генерация манифестов статических подов (`/etc/kubernetes/manifests`).
- **etcd initialization** — запуск локального хранилища конфигурации.
- **Wait control plane** — ожидание запуска и готовности всех компонентов.
- **Post-init** — создание RBAC-ролей и деплой аддонов (CoreDNS, kube-proxy).

### Ключевые параметры (флаги) инициализации

| Флаг | Назначение | Пример |
| :--- | :--- | :--- |
| `--control-plane-endpoint` | Адрес балансировщика/VIP для HA-кластера | `k8s-api.example.com:6443` |
| `--upload-certs` | Автоматическая загрузка сертификатов для других мастеров | — |
| `--pod-network-cidr` | Сеть для подов (зависит от CNI) | `10.244.0.0/16` |
| `--service-cidr` | Сеть для сервисов | `10.96.0.0/12` |
| `--apiserver-advertise-address` | IP, на котором API-сервер будет доступен другим узлам | `192.168.1.10` |
| `--cri-socket` | Путь к сокету Runtime | `unix:///run/containerd/containerd.sock` |
| `--kubernetes-version` | Выбор конкретной версии Kubernetes | `v1.36.0` |

### Планирование сетевых диапазонов (CIDR)

Диапазоны не должны пересекаться с физической сетью узлов.

| Параметр | Рекомендуемые значения | Примечание |
| :--- | :--- | :--- |
| **Pod CIDR** | `10.244.0.0/16`, `172.16.0.0/16` | Должен совпадать с настройками CNI (Calico/Flannel) |
| **Service CIDR** | `10.96.0.0/12`, `10.10.0.0/16` | По умолчанию `10.96.0.0/12` |

> **Важно:** Изменение этих диапазонов после создания кластера требует полной переустановки или крайне сложной ручной перенастройки.

---

## Практические сценарии

### Инициализация первого мастера (HA-подготовка)

```bash
sudo kubeadm init \
  --control-plane-endpoint "192.168.1.100:7443" \
  --pod-network-cidr=10.244.0.0/16 \
  --upload-certs \
  --cri-socket=unix:///run/containerd/containerd.sock
```

**После выполнения:**

1. Сохраните вывод команды `join` (токен и хэш).
2. Сохраните `certificate-key` для добавления других мастеров.

### Настройка доступа kubectl

```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# Проверка
kubectl get nodes
```

### Присоединение дополнительных узлов

**Control Plane (другие мастера):**

```bash
sudo kubeadm join 192.168.1.100:7443 --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane --certificate-key <key>
```

**Worker Nodes (рабочие узлы):**

```bash
sudo kubeadm join 192.168.1.100:7443 --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>
```

### Установка сетевого плагина (CNI Calico)

Без CNI узлы будут в статусе `NotReady`.

```bash
# Скачивание манифеста
curl -L https://raw.githubusercontent.com/projectcalico/calico/v3.32.1/manifests/calico.yaml -o calico.yaml

# Проверка/замена CIDR (должен совпадать с --pod-network-cidr)
sed -i 's|192.168.0.0/16|10.244.0.0/16|g' calico.yaml

# Применение
kubectl apply -f calico.yaml
```

---

## Дополнительная информация

### Диагностика и отладка

Для анализа причин неудачной инициализации используйте следующие команды:

```bash
# Просмотр логов kubelet
sudo journalctl -u kubelet -f

# Проверка состояния контейнеров Control Plane
sudo crictl ps -a

# Просмотр логов конкретного компонента (например, API Server)
sudo crictl logs $(sudo crictl ps --name kube-apiserver -q)
```

**Типичные ошибки:**

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `preflight` error | Swap включен | `sudo swapoff -a` и удаление из `/etc/fstab` |
| `etcd cluster unhealthy` | Проблемы с сетью или диском | Проверить задержки (latency) и права на `/var/lib/etcd` |
| `token expired` | Прошло более 24 часов | Создать новый: `kubeadm token create --print-join-command` |
| `certificate-key` lost | Ключ не сохранен | Пересоздать: `kubeadm init phase upload-certs --upload-certs` |
| `CRI runtime` not found | Неверный путь к сокету | Указать явно через `--cri-socket` |

### Очистка и сброс узла

Если инициализация завершилась с ошибкой и нужно начать заново:

```bash
# Полный сброс конфигурации
sudo kubeadm reset --force

# Ручная очистка остатков
sudo rm -rf /etc/kubernetes/ /var/lib/etcd/ /var/lib/kubelet/ /var/lib/cni/ /etc/cni/net.d/
sudo iptables -F && sudo iptables -t nat -F && sudo iptables -t mangle -F && sudo iptables -X
```

### См. также

- **[Полное руководство по установке](./kubeadm_installation_guide.md)** — подготовка системы и установка пакетов.
- **[Настройка High Availability](./ha_concepts.md)** — балансировка и Virtual IP (VIP).
- **[Управление сертификатами](../../Operations/certificate_management.md)** — ротация и продление.
