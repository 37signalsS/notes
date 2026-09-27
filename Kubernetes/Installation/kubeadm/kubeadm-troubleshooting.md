# Diagnostics и troubleshooting kubeadm

## Определения

**kubeadm init phase** — фазы инициализации кластера, которые можно запускать по отдельности для отладки. Каждая фаза выполняет атомарную операцию и может быть повторена при ошибке.

**kubeadm reset** — команда для полного сброса узла: остановка сервисов, удаление конфигураций, сертификатов и данных. Используется для повторной установки или удаления кластера.

**Static Pods** — поды, управляемые kubelet напрямую через манифесты в `/etc/kubernetes/manifests`. Компоненты Control Plane (apiserver, etcd, scheduler, controller-manager) запускаются как Static Pods.

**Kubelet logs** — логи агента kubelet, критичные для диагностики проблем с запуском подов, CRI и networking. Расположены в `journalctl -u kubelet`.

**crictl** — CLI-утилита для взаимодействия с CRI-совместимыми рантаймами (containerd). Используется для просмотра контейнеров, подов и образов вне Kubernetes.

**Preflight checks** — предварительные проверки системы перед запуском kubeadm: ядро, RAM, CPU, порты, swap, CRI. Запускаются автоматически или вручную.

**Bootstrap Token** — временный токен для аутентификации новых узлов при `kubeadm join`. Срок действия: 24 часа по умолчанию.

---

## Основные концепции

### Уровни диагностики

1. **Системный уровень:** ОС, ядро, сеть, disk I/O
2. **Уровень Runtime:** containerd, CRI, образы контейнеров
3. **Уровень Kubernetes:** kubelet, API-сервер, etcd, controller-manager, scheduler
4. **Уровень приложения:** поды, сервисы, конфигурация

### Источники логов

| Компонент | Команда для логов | Расположение |
| :--- | :--- | :--- |
| **kubelet** | `journalctl -u kubelet -f` | Системный лог |
| **containerd** | `journalctl -u containerd -f` | Системный лог |
| **API-сервер** | `kubectl logs -n kube-system kube-apiserver-<hostname>` | Static Pod |
| **etcd** | `kubectl logs -n kube-system etcd-<hostname>` | Static Pod |
| **controller-manager** | `kubectl logs -n kube-system kube-controller-manager-<hostname>` | Static Pod |
| **scheduler** | `kubectl logs -n kube-system kube-scheduler-<hostname>` | Static Pod |
| **kubeadm** | `kubeadm init phase <phase> --v=5` | Вывод команды |

### Уровни логирования (verbosity)

| Уровень | Описание |
| :--- | :--- |
| `--v=0` | Обычный (рекомендуется) |
| `--v=2` | Детальные Informationen о событиях |
| `--v=4` | Debug-уровень |
| `--v=6` | Trace-уровень (очень много) |
| `--v=8` | System-level trace |

---

## Практические сценарии

### 1. Сбор системной информации

Перед началом диагностики соберите базовую информацию:

```bash
#!/bin/bash
echo "=== СИСТЕМНАЯ ИНФОРМАЦИЯ ==="
echo "Дата: $(date)"
echo "Hostname: $(hostname)"
echo "OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2)"
echo "Kernel: $(uname -r)"
echo "CPU: $(nproc) cores"
echo "RAM: $(free -h | awk '/^Mem:/ {print $2}')"
echo "Disk: $(df -h / | awk 'NR==2 {print $2}')"

echo -e "\n=== СЕТЬ ==="
echo "IP адреса:"
ip -br addr show
echo "Маршрутизация:"
ip route show

echo -e "\n=== ПОРТЫ ==="
echo "Занятые порты (K8s):"
ss -tulpn | grep -E ':(6443|2379|2380|10250|10257|10259|7443)'

echo -e "\n=== SERVICЫ ==="
echo "containerd:"
systemctl status containerd --no-pager -l
echo "kubelet:"
systemctl status kubelet --no-pager -l

echo -e "\n=== CNI ИНТЕРФЕЙСЫ ==="
ip link show | grep -E ':(cni|flannel|calico|cilium|veth)'
```

### 2. Диагностика kubelet

#### kubelet не запускается

```bash
# Проверка статуса
sudo systemctl status kubelet
# → active (running) или failed

# Просмотр логов (последние 100 строк)
sudo journalctl -u kubelet -n 100 --no-pager

# Проверка конфигурации
cat /var/lib/kubelet/config.yaml

# Проверка kubeconfig
ls -la /etc/kubernetes/kubelet.conf

# Проверка socket containerd
ls -la /run/containerd/containerd.sock

# Тестирование CRI
sudo crictl info
sudo crictl ps -a
sudo crictl pods -a
```

#### Типичные ошибки kubelet

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Failed to connect to containerd` | containerd не запущен | `sudo systemctl start containerd` |
| `Failed to run kubelet` | Неверный конфиг | Проверьте `/var/lib/kubelet/config.yaml` |
| `Unable to register node` | Нет доступа к API | Проверьте `admin.conf` в `/etc/kubernetes/` |
| `ImagePullBackOff` | Нет доступа к реестру | Настройте прокси или mirror registry |
| `CrashLoopBackOff` | Ошибка в конфигурации пода | Проверьте `kubectl describe pod <name>` |

### 3. Диагностика kubeadm init

#### Запуск с увеличенным verbosity

```bash
# Запуск отдельной фазы с подробными логами
sudo kubeadm init phase preflight --v=5

# Запуск всех проверок без инициализации
sudo kubeadm init phase preflight --dry-run=client

# Полная инициализация с verbosity
sudo kubeadm init --v=5
```

#### Анализ ошибок kubeadm init

```bash
# Проверка портов
sudo kubeadm init phase preflight 2>&1 | grep -E "ERROR|WARN"

# Проверка CRI
sudo crictl info | jq .config.containerd

# Проверка версий
kubeadm version -o short
kubelet --version
containerd --version

# Проверка time синхронизации
timedatectl status
chronyc tracking
```

### 4. Диагностика etcd

#### Проверка здоровья etcd (stacked)

```bash
# Проверка static pod
kubectl get pods -n kube-system -l component=etcd -o wide

# Проверка логов
kubectl logs -n kube-system etcd-$(hostname) --tail=100

# Проверка здоровья через etcdctl
sudo ETCDCTL_API=3 etcdctl endpoint health \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# Статус кластера
sudo ETCDCTL_API=3 etcdctl endpoint status \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  --write-out=table

# Список участников
sudo ETCDCTL_API=3 etcdctl member list \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  --write-out=table
```

#### Проверка etcd (external)

```bash
# Проверка соединения с каждым узлом
for endpoint in https://etcd-1:2379 https://etcd-2:2379 https://etcd-3:2379; do
  echo "=== $endpoint ==="
  sudo ETCDCTL_API=3 etcdctl endpoint health \
    --endpoints=$endpoint \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/apiserver-etcd-client.crt \
    --key=/etc/kubernetes/pki/etcd/apiserver-etcd-client.key
done
```

### 5. Диагностика API-сервера

```bash
# Проверка static pod
kubectl get pods -n kube-system -l component=kube-apiserver -o wide

# Проверка логов
kubectl logs -n kube-system kube-apiserver-$(hostname) --tail=100

# Проверка здоровья
kubectl get --raw='/healthz?verbose'
kubectl get --raw='/readyz?verbose'

# Проверка метрик
kubectl get --raw='/metrics' | head -20

# Проверка авторизации
kubectl auth can-i list pods
kubectl auth can-i create deployments --as=system:serviceaccount:default:default
```

### 6. Диагностика сети

```bash
# Проверка CNI плагина
kubectl get pods -n kube-system -o wide | grep -E 'calico|cilium|flannel|weave'

# Проверка DNS
kubectl run dns-test --image=busybox --restart=Never -- sleep 3600
kubectl exec dns-test -- nslookup kubernetes.default
kubectl exec dns-test -- nslookup kube-dns.kube-system.svc.cluster.local
kubectl delete pod dns-test --grace-period=0 --force

# Проверка сетевой связности
kubectl run test1 --image=busybox --restart=Never -- sleep 3600
kubectl run test2 --image=nginx --restart=Never -- sleep 3600
kubectl wait --for=condition=Ready pod/test1 test2 --timeout=60s
kubectl exec test1 -- ping -c 3 $(kubectl get pod test2 -o jsonpath='{.status.podIP}')
kubectl delete pod test1 test2 --grace-period=0 --force

# Проверка правил iptables
sudo iptables -t nat -L -n | grep -E 'KUBE|kubernetes'
sudo iptables -t filter -L -n | grep -E 'KUBE|kubernetes'
```

### 7. Диагностика сертификатов

```bash
# Проверка сроков действия
sudo kubeadm certs check-expiration

# Проверка конкретного сертификата
openssl x509 -in /etc/kubernetes/pki/apiserver.crt -text -noout | grep -A2 "Validity"

# Проверка соответствия ключа и сертификата
openssl x509 -noout -modulus -in /etc/kubernetes/pki/apiserver.crt | md5sum
openssl rsa -noout -modulus -in /etc/kubernetes/pki/apiserver.key | md5sum
# → Должны совпадать

# Проверка CA
openssl verify -CAfile /etc/kubernetes/pki/ca.crt /etc/kubernetes/pki/apiserver.crt
```

### 8. Восстановление после сбоев

#### kubeadm reset и чистая установка

```bash
# 1. Остановка сервисов
sudo systemctl stop kubelet
sudo systemctl stop containerd

# 2. Сброс через kubeadm
sudo kubeadm reset --force

# 3. Ручная очистка (если kubeadm reset не помог)
sudo rm -rf /etc/kubernetes/ /var/lib/etcd/ /var/lib/kubelet/ /var/lib/cni/ /etc/cni/net.d/
sudo rm -rf /etc/containerd/config.toml
sudo rm -rf /etc/crictl.yaml
sudo rm -rf /etc/modules-load.d/k8s.conf
sudo rm -rf /etc/sysctl.d/k8s.conf
sudo rm -rf /etc/security/limits.d/k8s.conf

# 4. Очистка правил сети
sudo iptables -F && sudo iptables -t nat -F && sudo iptables -t mangle -F && sudo iptables -X
sudo ip link delete cni0 2>/dev/null
sudo ip link delete flannel.1 2>/dev/null
sudo ip link delete tunl0 2>/dev/null

# 5. Перезапуск сервисов
sudo systemctl daemon-reload
sudo systemctl start containerd
sudo systemctl start kubelet

# 6. Повторная инициализация
sudo kubeadm init --config kubeadm-init.yaml
```

#### Восстановление Control Plane

```bash
# 1. Проверка манифестов Static Pods
ls -la /etc/kubernetes/manifests/

# 2. Проверка наличия сертификатов
ls -la /etc/kubernetes/pki/

# 3. Восстановление kubeconfig
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# 4. Перезапуск kubelet
sudo systemctl restart kubelet

# 5. Проверка состояния
kubectl get nodes
kubectl get pods -n kube-system
```

### 9. Мониторинг в реальном времени

```bash
# Мониторинг подов
watch kubectl get pods -n kube-system

# Мониторинг узлов
watch kubectl get nodes

# Мониторинг событий
kubectl get events --sort-by='.lastTimestamp' -n kube-system -w

# Мониторинг логов API-сервера
kubectl logs -n kube-system kube-apiserver-$(hostname) -f

# Мониторинг etcd
kubectl logs -n kube-system etcd-$(hostname) -f
```

### 10. Скрипт полной диагностики

```bash
#!/bin/bash
echo "=== KUBeadm DIAGNOSTICS ==="

# 1. Системная информация
echo "--- System Info ---"
hostnamectl
uname -r
free -h
df -h /

# 2. Сервисы
echo "--- Services ---"
systemctl status containerd --no-pager -l
systemctl status kubelet --no-pager -l

# 3. Порты
echo "--- Ports ---"
ss -tulpn | grep -E ':(6443|2379|2380|10250|10257|10259)'

# 4. Версии
echo "--- Versions ---"
kubeadm version -o short
kubelet --version
containerd --version

# 5. Static Pods
echo "--- Static Pods ---"
kubectl get pods -n kube-system -o wide

# 6. Сертификаты
echo "--- Certificates ---"
sudo kubeadm certs check-expiration

# 7. etcd
echo "--- etcd Health ---"
sudo ETCDCTL_API=3 etcdctl endpoint health \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# 8. Сеть
echo "--- Network ---"
ip route show
iptables -t nat -L -n | head -20

# 9. DNS
echo "--- DNS Test ---"
kubectl run dns-test --image=busybox --restart=Never -- sleep 360 2>/dev/null
sleep 5
kubectl exec dns-test -- nslookup kubernetes.default 2>/dev/null || echo "DNS failed"
kubectl delete pod dns-test --grace-period=0 --force 2>/dev/null

# 10. Логи ошибок
echo "--- Recent Errors ---"
journalctl -u kubelet --since "1 hour ago" | grep -i error | tail -10
```

---

## Дополнительная информация

### Best Practices для диагностики

1. **Начинайте с базовой информации:** системные ресурсы, версии, порты.
2. **Проверяйте логи последовательно:** containerd → kubelet → API-сервер → etcd.
3. **Используйте `--v=5`** для детальных логов при отладке.
4. **Документируйте решения:** записывайте причины и решения для повторения.
5. **Регулярно проверяйте сертификаты:** `kubeadm certs check-expiration`.
6. **Тестируйте failover:** регулярно проверяйте отказоустойчивость.

### Инструменты

- **crictl:** Диагностика CRI-контейнеров.
- **etcdctl:** Диагностика etcd.
- **openssl:** Проверка сертификатов.
- **tcpdump:** Анализ сетевого трафика.
- **strace:** Трассировка системных вызовов.
- **perf:** Анализ производительности.

### Ссылки

- [Troubleshooting kubeadm](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/troubleshooting-kubeadm/)
- [Debug Running Pods](https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/)
- [Debug a StatefulSet](https://kubernetes.io/docs/tasks/debug/debug-application/debug-stateful-set/)
- [Logging Architecture](https://kubernetes.io/docs/concepts/cluster-administration/logging/)