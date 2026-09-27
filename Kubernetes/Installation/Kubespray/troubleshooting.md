# Kubespray: Устранение неполадок

## Определения

**Troubleshooting (Устранение неполадок)** — процесс диагностики и решения проблем, возникающих при развертывании, обновлении и эксплуатации кластера Kubernetes с использованием Kubespray.

**Диагностический путь** — последовательность проверок для идентификации корневой причины проблемы: от сетевой связности до состояния компонентов Kubernetes.

**Симптом** — внешнее проявление проблемы (например, узел в статусе `NotReady`, под в `CrashLoopBackOff`).

**Корневая причина (Root Cause)** — истинный источник проблемы, часто скрытый за рядом симптомов.

**Idempotency (Идемпотентность)** — свойство Ansible-плейбуков Kubespray, при котором повторный запуск не приводит к нежелательным изменениям, если система уже соответствует целевому состоянию.

---

## Основные концепции

### Методология диагностики

При возникновении ошибки в Kubespray следуйте последовательности:

1. **Проверьте логи Ansible:** Увеличьте детализацию (`-vvv`) для поиска конкретной ошибки.
2. **Проверьте 상태 узла:** Убедитесь, что узел доступен по SSH и выполняет команды.
3. **Проверьте компоненты Kubernetes:** kubelet, containerd, API-сервер, etcd.
4. **Проверьте сеть:** Связность между узлами, DNS, firewall.
5. **Проверьте ресурсы:** Диск, память, CPU на проблемных узлах.

### Типичные зоны отказа

| Зона | Компонент | Симптомы |
| :--- | :--- | :--- |
| **Сеть** | SSH, firewall, DNS | `UNREACHABLE!`, `connection refused`, `no such host` |
| **Узел** | kubelet, containerd | `NotReady`, `CrashLoopBackOff`, `ImagePullBackOff` |
| **API-сервер** | kube-apiserver | `The connection to the server was refused`, `Unauthorized` |
| **etcd** | etcd | `etcd cluster is unavailable`, `leader changed` |
| **CNI** | Calico/Cilium/Flannel | Поды в `ContainerCreating`, `NetworkPlugin cni failed` |
| **Диск** | kubelet, etcd | `DiskPressure`, `no space left on device` |

### Команды быстрой диагностики

```bash
# Статус узлов
kubectl get nodes -o wide

# Системные поды
kubectl get pods -n kube-system -o wide

# Логи kubelet
sudo journalctl -u kubelet -f --no-pager | tail -50

# Статус containerd
sudo systemctl status containerd
sudo crictl ps -a

# Проверка etcd
kubectl exec -n kube-system etcd-master-1 -- etcdctl endpoint health --cluster

# Проверка API-сервера
curl -sk https://localhost:6443/healthz

# Проверка связности
ansible -i inventory/mycluster/hosts.yaml all -m ping
```

---

## Практические сценарии

### 1. Ошибки Ansible при запуске плейбуков

#### Ошибка: `UNREACHABLE! Failed to connect to the host via ssh`

**Причина:** Нет SSH-доступа к целевому узлу.

**Решение:**

```bash
# Проверка SSH-подключения
ssh -i ~/.ssh/id_kubespray user@<ip-адрес> "hostname"

# Проверка SSH-ключей
ssh-add -l

# Проверка прав на SSH-ключ
chmod 600 ~/.ssh/id_kubespray

# Проверка firewall
sudo ufw status
# Или для iptables:
sudo iptables -L INPUT -v | grep 22
```

#### Ошибка: `Missing sudo password`

**Причина:** Не настроен беспарольный sudo для пользователя Ansible.

**Решение:**

```bash
# На целевом узле
echo "user ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/user
sudo chmod 440 /etc/sudoers.d/user

# Проверка
ssh user@<ip-адрес> "sudo whoami"
# → root
```

#### Ошибка: `the role 'xxx' was not found`

**Причина:** Несовместимая версия Kubespray и Ansible.

**Решение:**

```bash
# Проверьте версию Kubespray
git log --oneline -1

# Установите правильные зависимости
pip install -r requirements.txt

# Проверьте версию Ansible
ansible --version
```

### 2. Проблемы с узлами Kubernetes

#### Узел в статусе `NotReady`

**Диагностика:**

```bash
# Проверка логов kubelet
ssh <узел> "sudo journalctl -u kubelet -f --no-pager | tail -20"

# Проверка статуса kubelet
ssh <узел> "sudo systemctl status kubelet"

# Проверка containerd
ssh <узел> "sudo systemctl status containerd"

# Проверка конфигурации kubelet
ssh <узел> "sudo cat /var/lib/kubelet/config.yaml"
```

**Типичные причины и решения:**

| Причина | Симптом | Решение |
| :--- | :--- | :--- |
| CNI не установлен | `NetworkPlugin cni failed` | Проверьте CNI: `kubectl get pods -n kube-system -l k8s-app=calico-node` |
| containerd не запущен | `failed to connect to containerd` | `sudo systemctl restart containerd` |
| Сертификаты истекли | `x509: certificate has expired` | `sudo kubeadm certs renew all` |
| Нет места на диске | `DiskPressure` | Очистите диск: `sudo crictl rmi --prune` |

#### Под в `CrashLoopBackOff`

**Диагностика:**

```bash
# Проверка логов пода
kubectl logs <pod-name> --previous

# Проверка описания пода
kubectl describe pod <pod-name>

# Проверка событий
kubectl get events -n <namespace> --sort-by='.lastTimestamp'
```

**Типичные причины:**

| Причина | Пример лога | Решение |
| :--- | :--- | :--- |
| Ошибка приложения | `panic: runtime error` | Исправьте код приложения |
| Не хватает памяти | `OOMKilled` | Увеличьте `resources.limits.memory` |
| Ошибка конфигурации | `unable to load config` | Проверьте ConfigMap/Secret |
| Проблема с сетью | `dial tcp: connection refused` | Проверьте сервис и endpoints |

#### Под в `ImagePullBackOff`

**Диагностика:**

```bash
# Проверка событий
kubectl describe pod <pod-name> | grep -A 5 Events

# Проверка доступности реестра
crictl pull <образ>

# Проверка credentials
kubectl get secret -n <namespace> <secret-name> -o yaml
```

**Решение:**

```bash
# Проверьте имя образа и тег
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].image}'

# Проверьте доступность реестра
curl -v https://registry.k8s.io/v2/

# Если используется приватный реестр
kubectl create secret docker-registry regcred \
  --docker-server=<server> \
  --docker-username=<user> \
  --docker-password=<pass> \
  -n <namespace>
```

### 3. Проблемы с сетью

#### Поды не могут связаться по DNS

**Диагностика:**

```bash
# Проверка подов CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Проверка логов CoreDNS
kubectl logs -n kube-system -l k8s-app=kube-dns

# Тест DNS из пода
kubectl run dns-test --image=busybox:1.37 --rm -it --restart=Never -- nslookup kubernetes.default
```

**Решение:**

```bash
# Перезапуск CoreDNS
kubectl -n kube-system rollout restart deployment coredns

# Проверка Service ClusterIP для CoreDNS
kubectl -n kube-system get svc kube-dns

# Проверка /etc/resolv.conf в поде
kubectl exec -it <pod-name> -- cat /etc/resolv.conf
```

#### Поды не могут связаться между узлами

**Диагностика:**

```bash
# Проверка CNI-плагина
kubectl get pods -n kube-system -l k8s-app=calico-node

# Проверка NetworkPolicy
kubectl get networkpolicy -A

# Тест связности между подами
kubectl run test-net --image=busybox:1.37 --rm -it --restart=Never -- sh
# Внутри пода:
wget -qO- --timeout=5 http://<IP_другого_под>
```

**Решение:**

```bash
# Проверьте MTU (особенно для VXLAN)
ip link show

# Проверьте firewall
sudo iptables -L -v | grep -i "drop\|reject"

# Проверьте CNI конфигурацию
ls /etc/cni/net.d/
```

### 4. Проблемы с etcd

#### etcd потерял кворум

**Симптомы:** API-сервер не отвечает, поды в `Pending`.

**Диагностика:**

```bash
# Проверка здоровья etcd
kubectl exec -n kube-system etcd-master-1 -- etcdctl endpoint health --cluster

# Проверка статуса
kubectl exec -n kube-system etcd-master-1 -- etcdctl endpoint status --cluster -w table

# Проверка членов
kubectl exec -n kube-system etcd-master-1 -- etcdctl member list -w table
```

**Решение:**

```bash
# Если есть бэкап, восстановите из снапшота
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-<дата>.db \
  --data-dir=/var/lib/etcd-restored \
  --name=<etcd-member-name> \
  --initial-cluster=<etcd-member1>=https://<ip1>:2380,... \
  --initial-advertise-peer-urls=https://<ip>:2380

# Если бэкапа нет, пересоздайте кластер
ansible-playbook -i inventory/mycluster/hosts.yaml reset.yml
ansible-playbook -i inventory/mycluster/hosts.yaml cluster.yml
```

### 5. Проблемы с обновлением

#### Обновление зависает на Control Plane

**Причина:** etcd не отвечает или сертификаты истекли.

**Решение:**

```bash
# Проверьте etcd
kubectl exec -n kube-system etcd-master-1 -- etcdctl endpoint health --cluster

# Обновите сертификаты вручную
sudo kubeadm certs renew all

# Перезапустите компоненты
sudo systemctl restart kube-apiserver etcd

# Повторите обновление
ansible-playbook -i inventory/mycluster/hosts.yaml --become upgrade-cluster.yml
```

#### Worker не переходит в `Ready` после обновления

**Причина:** kubelet не смог подключиться к API.

**Решение:**

```bash
# Проверьте логи kubelet на worker
ssh <worker> "sudo journalctl -u kubelet -f"

# Проверьте сертификаты kubelet
ssh <worker> "sudo kubeadm certs check-expiration"

# Если сертификаты истекли
ssh <worker> "sudo kubeadm certs renew kubelet"

# Перезапустите kubelet
ssh <worker> "sudo systemctl restart kubelet"
```

### 6. Проблемы с ресурсами

#### Дисковое давление (DiskPressure)

**Симптомы:** Узел в статусе `NotReady`, поды не запускаются.

**Диагностика:**

```bash
# Проверка места на диске
ssh <узел> "df -h / /var/lib/kubelet /var/lib/etcd"

# Проверка размера образов
ssh <узел> "sudo crictl images"

# Проверка логов kubelet
ssh <узел> "sudo journalctl -u kubelet -f | grep -i disk"
```

**Решение:**

```bash
# Очистка неиспользуемых образов
ssh <узел> "sudo crictl rmi --prune"

# Очистка логов
ssh <узел> "sudo journalctl --vacuum-time=72h"

# Очистка старых подов
ssh <узел> "sudo crictl pods --state=notready | awk '{print \$1}' | xargs -r sudo crictl rmp"
```

#### Давление памяти (MemoryPressure)

**Симптомы:** Поды в `OOMKilled`, узел не принимает новые поды.

**Диагностика:**

```bash
# Проверка использования памяти
kubectl top nodes
kubectl top pods -A --sort-by=memory

# Проверка лимитов
kubectl get pods -A -o custom-columns=NAME:.metadata.name,MEMORY_REQ:.spec.containers[*].resources.requests.memory,MEMORY_LIM:.spec.containers[*].resources.limits.memory
```

**Решение:**

```bash
# Увеличьте лимиты для критичных подов
kubectl patch deployment <deployment> -p '{"spec":{"template":{"spec":{"containers":[{"name":"<container>","resources":{"limits":{"memory":"512Mi"}}}]}}}}'

# Оптимизируйте потребление памяти приложением
# Используйте Vertical Pod Autoscaler для автоматической настройки
```

### 7. Проблемы с обновлением Kubespray

#### Версии Kubespray и Kubernetes несовместимы

**Причина:** Используется неверная ветка Kubespray для целевой версии Kubernetes.

**Решение:**

```bash
# Проверьте матрицу совместимости
# https://github.com/kubernetes-sigs/kubespray#supported-provisions

# Используйте правильную ветку
git checkout branch-2.31  # Для K8s v1.33-v1.35

# Обновите зависимости
pip install -r requirements.txt
```

#### Ошибки при обновлении версии Kubernetes

**Симптомы:** `upgrade-cluster.yml` падает с ошибкой.

**Решение:**

```bash
# Проверьте, что обновление возможно только на одну минорную версию
# Например, v1.34 → v1.35, но НЕ v1.33 → v1.35

# Проверьте состояние кластера
kubectl get nodes
kubectl exec -n kube-system etcd-master-1 -- etcdctl endpoint health --cluster

# Создайте бэкап etcd перед повторной попыткой
sudo ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-pre-upgrade-$(date +%Y%m%d).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key

# Повторите обновление
ansible-playbook -i inventory/mycluster/hosts.yaml --become upgrade-cluster.yml
```

### 8. Проблемы с HA (Высокая доступность)

#### VIP не назначается на узел

**Причина:** Заблокирован VRRP (proto 112) в firewall или multicast не работает.

**Решение:**

```bash
# Разрешить VRRP в firewall
sudo iptables -A INPUT -p 112 -j ACCEPT
sudo iptables -A OUTPUT -p 112 -j ACCEPT

# Или используйте unicast для Keepalived
# В group_vars/all/all.yml:
keepalived_unicast_peers:
  - 192.168.1.11
  - 192.168.1.12
```

#### Split-brain (VIP на нескольких узлах)

**Причина:** Конфликт `virtual_router_id` или multicast не доставляет VRRP-пакеты.

**Диагностика:**

```bash
# Проверка ARP-таблиц
arp -n | grep <VIP>

# Проверка VRRP-трафика
tcpdump -i any proto 112 -c 20

# Проверка конфигурации Keepalived
cat /etc/keepalived/keepalived.conf | grep -E "virtual_router_id|priority|state"
```

**Решение:**

```bash
# Убедитесь, что virtual_router_id уникален в подсети
# Используйте разные ID для разных групп Keepalived

# Проверьте firewall для VRRP
sudo iptables -L INPUT -v | grep 112
```

---

## Дополнительная информация

### Чек-лист перед запуском плейбука

- [ ] SSH-доступ настроен и работает со всех узлов
- [ ] Беспарольный sudo настроен
- [ ] Python 3.10+ установлен на целевых узлах
- [ ] Версии Kubespray и Ansible совместимы
- [ ] Все узлы доступны по сети (ping)
- [ ] Firewall не блокирует необходимые порты
- [ ] Достаточно места на диске (минимум 10 ГБ)
- [ ] NTP-сервис работает (chrony или systemd-timesyncd)
- [ ] SWAP отключен на всех узлах
- [ ] Инвентарь содержит корректные IP-адреса

### Полезные ссылки

- [Обзор Kubespray](./overview.md) — базовые принципы.
- [Установка кластера](./kubespray_install/basic_concepts.md) — пошаговое руководство.
- [Управление кластером](./cluster_management.md) — масштабирование и обновление.
- [HA через Kubespray](./HA/index.md) — настройка отказоустойчивости.
- [Offline установка](./offline_installation/offline_definitions.md) — развертывание в изолированных сетях.
- [Troubleshooting offline](./offline_installation/troubleshooting.md) — решение проблем в offline-режиме.

### Внешние ресурсы

- [Kubespray Documentation](https://kubespray.io/) — официальная документация.
- [Kubernetes Troubleshooting Guide](https://kubernetes.io/docs/tasks/debug/debug-cluster/) — официальное руководство по диагностике.
- [Ansible Troubleshooting](https://docs.ansible.com/ansible/latest/network/user_guide/troubleshooting.html) — решение проблем Ansible.