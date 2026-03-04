# Управление узлами кластера

## 1. Определения

| Термин | Описание |
| :--- | :--- |
| **Bootstrap Token** | Временный токен для присоединения узлов к кластеру (действует 24 часа по умолчанию). |
| **Certificate Key** | Ключ для безопасной передачи сертификатов control-plane при присоединении новых master-узлов. |
| **Drain** | Операция безопасного удаления узлов: eviction подов, mark unschedulable. |
| **Cordon** | Mark узла как unschedulable (без eviction подов). |
| **Uncordon** | Снятие ограничения cordons, узел снова доступен для планирования. |

## 2. Основные концепции

### 2.1. Токены kubeadm

| Тип токена | Срок действия | Назначение |
| :--- | :--- | :--- |
| **Bootstrap Token** | 24 часа | Присоединение worker и control-plane узлов. |
| **Certificate Key** | 2 часа | Передача сертификатов CA новым control-plane узлам. |

### 2.2. Типы узлов

| Тип узла | Описание | Особенности удаления |
| :--- | :--- | :--- |
| **Worker Node** | Запускает пользовательские поды | Простое удаление через `kubeadm reset`. |
| **Control-Plane Node** | Запускает компоненты Control Plane + etcd | Требуется удаление из etcd кластера. |

> **Важно:** В кластере должно быть **нечётное количество control-plane узлов** (1, 3, 5) для обеспечения кворума etcd.

## 3. Практические сценарии

### 3.1. Добавление узлов

#### Добавление Worker-узла

**Шаг 1: Генерация команды join (на master)**

```bash
# Создать новый токен и вывести полную команду
sudo kubeadm token create --print-join-command
```

**Шаг 2: Выполнение команды join (на worker)**

```bash
# Пример команды
sudo kubeadm join <vip-or-master-ip>:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>
```

**Проверка:**

```bash
kubectl get nodes
# Статус должен быть Ready через 1-2 минуты
```

#### Добавление Control-Plane-узла

**Сценарий: Токен действителен**

Используйте команду `kubeadm join` с флагом `--control-plane` из вывода `kubeadm init`.

**Сценарий: Токен истёк**

**Шаг 1: Создание нового bootstrap-токена (на существующем master)**

```bash
sudo kubeadm token create
# Вывод: <token> (например, abcdef.0123456789abcdef)
```

**Шаг 2: Получение хеша CA-сертификата**

```bash
openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | \
  openssl rsa -pubin -outform der 2>/dev/null | \
  openssl dgst -sha256 -hex | sed 's/^.* //'
# Вывод: <hash> (64-символьная строка)
```

**Шаг 3: Загрузка сертификатов в кластер**

```bash
sudo kubeadm init phase upload-certs --upload-certs
# Вывод: <certificate-key> (64-символьная строка, действителен 2 часа)
```

**Шаг 4: Формирование команды join (на новом control-plane)**

```bash
sudo kubeadm join <vip-or-master-ip>:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <certificate-key>
```

> **Важно:** Команда с `--certificate-key` действительна только 2 часа.

### 3.2. Удаление узлов

#### Удаление Worker-узла (штатное)

**Шаг 1: Drain узла (на master)**

```bash
# Evict поды и mark unschedulable
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
```

**Шаг 2: Удаление из кластера**

```bash
kubectl delete node <node-name>
```

**Шаг 3: Сброс состояния (на удаляемом узле)**

```bash
sudo kubeadm reset
```

#### Удаление Control-Plane-узла (штатное)

**Шаг 1: Drain узла**

```bash
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
```

**Шаг 2: Удаление из кластера**

```bash
kubectl delete node <node-name>
```

**Шаг 3: Сброс состояния (на удаляемом узле)**

```bash
# Эта команда корректно удаляет узел из etcd
sudo kubeadm reset
```

#### Удаление Control-Plane-узла (аварийное)

> **Сценарий:** Узел потерян, `kubeadm reset` выполнить невозможно.

**Шаг 1: Удаление объекта Node**

```bash
kubectl delete node <lost-node-name>
```

**Шаг 2: Удаление участника из etcd**

```bash
# Найти рабочий etcd под
kubectl get pods -n kube-system | grep etcd

# Получить список участников
kubectl exec -n kube-system etcd-<master-name> -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  member list

# Удалить потерянный узел (используйте ID из предыдущей команды)
kubectl exec -n kube-system etcd-<master-name> -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  member remove <member-id>
```

### 3.3. Обслуживание узлов

#### Вывод узла в обслуживание

```bash
# Запретить планирование новых подов
kubectl cordon <node-name>

# Безопасно удалить существующие поды
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
```

#### Возврат узла в строй

```bash
# Разрешить планирование
kubectl uncordon <node-name>
```

#### Перезапуск подов после обновления

```bash
# Перезапуск CoreDNS (после добавления control-plane)
kubectl rollout restart deployment coredns -n kube-system

# Перезапуск kube-proxy (после обновления узлов)
kubectl rollout restart daemonset kube-proxy -n kube-system
```

### 3.4. Troubleshooting

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **Node NotReady** | `kubectl describe node <name>` | Проверить kubelet, сеть, CNI |
| **Pod Pending** | `kubectl describe pod <name>` | Проверить ресурсы, taints, affinity |
| **Token expired** | `kubeadm token list` | `kubeadm token create --print-join-command` |
| **etcd кворум потерян** | `etcdctl endpoint health` | Восстановить из backup, добавить узел |
| **Node не удаляется** | `kubectl get events --sort-by='.lastTimestamp'` | Force delete: `kubectl delete node <name> --force --grace-period=0` |

## 4. Дополнительная информация

### 4.1. Связанные темы

*   [Быстрый старт с kubeadm](./kubeadm_quickstart.md)
*   [Управление сертификатами](../../Operations/certificate_management.md)
*   [etcd обслуживание](../../Concepts/etcd_overview.md)
*   [Troubleshooting кластера](../../Troubleshooting/cluster_troubleshooting.md)

### 4.2. Best Practices

| Практика | Описание |
| :--- | :--- |
| **Регулярный backup etcd** | `etcdctl snapshot save` перед изменениями |
| **Мониторинг токенов** | Проверка срока действия перед добавлением узлов |
| **Плановое обслуживание** | Использование `cordon/drain` перед обновлением |
| **Нечётное число control-plane** | Избегание потери кворума etcd |
