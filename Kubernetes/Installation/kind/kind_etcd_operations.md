# kind — операции с etcd

## Определения

**etcd** — распределённое KV-хранилище, являющееся единственным источником правды (source of truth) для всех объектов Kubernetes (Pod, Service, ConfigMap, Secret и др.). Все изменения в кластере проходят через etcd.

**etcdctl** — CLI-клиент для взаимодействия с etcd (gRPC-протокол). Используется для создания снапшотов, проверки здоровья, дефрагментации и восстановления.

**Snapshot (снапшот)** — полная копия базы данных etcd в определённый момент времени. Единственный механизм backup, гарантирующий возможность восстановления кластера.

**Compaction** — процесс удаления устаревших версий ключей из etcd для освобождения места.

**Defrag** — процесс физического сжатия файла базы данных etcd после compaction.

---

## Основные концепции

### Особенности etcd в kind

В kind etcd работает как **static pod** внутри control-plane узла (Docker-контейнера). Это означает:

- etcd доступен только изнутри control-plane узла
- Для выполнения команд `etcdctl` необходимо подключиться к узлу через `docker exec`
- Клиентские сертификаты etcd хранятся внутри узла в `/etc/kubernetes/pki/etcd/`
- kind не предоставляет внешний доступ к etcd (в отличие от production-кластеров с внешним etcd)

### Где находится etcd в kind

| Компонент | Путь в узле kind | Описание |
|:---|:---|:---|
| **Данные etcd** | `/var/lib/etcd/` | Файл `member/snap/db` — основная БД |
| **Сертификаты** | `/etc/kubernetes/pki/etcd/` | `ca.crt`, `server.crt`, `server.key`, `peer.crt`, `peer.key` |
| **Конфигурация** | `/etc/kubernetes/manifests/etcd.yaml` | Static pod манифест |
| **Логи** | `journalctl -u etcd` или `crictl logs` | Системные логи etcd |

### Когда нужны операции с etcd в kind

| Сценарий | Операция | Зачем |
|:---|:---|:---|
| Тестирование backup/restore | `snapshot save/restore` | Проверить процедуру восстановления |
| Диагностика проблем с API | `endpoint health`, `member list` | Выяснить, почему API-сервер не отвечает |
| Тестирование compaction/defrag | `compact`, `defrag` | Проверить освобождение места |
| Тестирование масштабирования | `member add/remove` | Проверить добавление/удаление узлов etcd |

---

## Практические сценарии

### Создание кластера для тестирования

```bash
kind create cluster --name etcd-test
```

### Сценарий 1: Подключение к etcd внутри узла kind

```bash
# Определение имени control-plane контейнера
docker ps --filter "label=io.x-k8s.kind.cluster=etcd-test" --format "{{.Names}}"
# → etcd-test-control-plane

# Подключение к узлу
docker exec -it etcd-test-control-plane bash

# Внутри узла: настройка переменных для etcdctl
export ENDPOINTS=https://127.0.0.1:2379
export CA=/etc/kubernetes/pki/etcd/ca.crt
export CERT=/etc/kubernetes/pki/etcd/server.crt
export KEY=/etc/kubernetes/pki/etcd/server.key

# Проверка здоровья etcd
ETCDCTL_API=3 etcdctl endpoint health \
  --endpoints=$ENDPOINTS \
  --cacert=$CA \
  --cert=$CERT \
  --key=$KEY
# → https://127.0.0.1:2379 is healthy: committed proposal took 1.333422ms

# Информация о кластере etcd
ETCDCTL_API=3 etcdctl endpoint status \
  --endpoints=$ENDPOINTS \
  --cacert=$CA \
  --cert=$CERT \
  --key=$KEY \
  --write-out=table
# → ENDPOINT         ID            VERSION   DB SIZE   IN USE   STATUS   DB SIZE IN USE   VERSION
# → 127.0.0.1:2379   8e9e05f54...   3.5.12    5.2 MB    2.1 MB   leader   40.0%            3.5.12
```

### Сценарий 2: Создание и проверка снапшота

```bash
# Создание директории для бэкапов на хосте
mkdir -p /tmp/etcd-backup

# Копирование снапшота из узла на хост
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl snapshot save /tmp/snapshot.db \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key
'
# → Snapshot saved at /tmp/snapshot.db

# Копирование снапшота на хост
docker cp etcd-test-control-plane:/tmp/snapshot.db /tmp/etcd-backup/snapshot-$(date +%Y%m%d).db

# Проверка статуса снапшота
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl snapshot status /tmp/snapshot.db --write-out=table
'
# → +---------+----------+------------+--------+
# → | REVISION | DB SIZE  | DB IN USE  | STATUS |
# → +---------+----------+------------+--------+
# → |  12345  | 5242880  | 2097152    | ok     |
# → +---------+----------+------------+--------+
```

### Сценарий 3: Compaction и defrag

```bash
# Проверка текущего размера БД
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl endpoint status \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key \
    --write-out=json | jq ".[0].Status.dbSize"
'
# → 5242880

# Compaction: удаление устаревших версий
docker exec etcd-test-control-plane sh -c '
  REV=$(ETCDCTL_API=3 etcdctl endpoint status \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key \
    --write-out=json | jq ".[0].Status.header.revision")
  ETCDCTL_API=3 etcdctl compact $REV \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key
'
# → compacted revision 12345

# Defrag: физическое сжатие файла БД
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl defrag \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key
'
# → Defragmented endpoint https://127.0.0.1:2379
# → freed 1048576 bytes

# Проверка размера после defrag
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl endpoint status \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key \
    --write-out=json | jq ".[0].Status.dbSize"
'
# → 4194304 (уменьшился)
```

### Сценарий 4: Listing ключей в etcd

```bash
# Просмотр всех ключей (включая служебные)
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl get / --prefix --keys-only \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key | head -20
'
# → /registry/
# → /registry/apiregistration.k8s.io/apiservices/v1.
# → /registry/apiregistration.k8s.io/apiservices/v1.admissionregistration.k8s.io
# → ...

# Подсчёт количества объектов
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl get /registry --prefix --keys-only \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key | wc -l
'
# → 1234

# Просмотр ключей определённого типа
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl get /registry/pods --prefix --keys-only \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key
'
# → /registry/pods/default/
# → /registry/pods/default/my-pod
# → /registry/pods/kube-system/
# → /registry/pods/kube-system/coredns-xxx
```

### Сценарий 5: Проверка alarm list

```bash
# Проверка alarm (предупреждений etcd)
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl alarm list \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key
'
# → (пусто если всё в порядке)

# Типичные alarm:
# → NOSPACE —quota exceeded (БД заполнена)
# → CORRUPT —данные повреждены

# Сброс alarm (после решения проблемы)
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl alarm disarm \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key
'
```

### Сценарий 6: Восстановление из снапшота (эмуляция)

```bash
# 1. Создание снапшота
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl snapshot save /tmp/backup.db \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key
'

# 2. Восстановление в отдельную директорию (без остановки etcd)
docker exec etcd-test-control-plane sh -c '
  ETCDCTL_API=3 etcdctl snapshot restore /tmp/backup.db \
    --data-dir=/var/lib/etcd-restored \
    --name etcd-test-control-plane \
    --initial-cluster "etcd-test-control-plane=https://127.0.0.1:2380" \
    --initial-advertise-peer-urls "https://127.0.0.1:2380" \
    --listen-peer-urls "https://127.0.0.1:2380"
'
# → member 8e9e05f54f240d12 restored from snapshot db

# 3. Проверка восстановленных данных
docker exec etcd-test-control-plane sh -c '
  ls -la /var/lib/etcd-restored/member/snap/
'
# → -rw------- 1 root root 5242880 ... db

# 4. Для реального восстановления: остановить etcd, заменить /var/lib/etcd, запустить etcd
# (ВНИМАНИЕ: это разрушит текущий кластер!)
```

---

## Дополнительная информация

### Ссылки

- [kind — определения и концепции](./kind_concepts.md) — архитектура и внутреннее устройство узлов
- [etcd: обзор и концепции](../../Concepts/etcd_overview.md) — полная теория etcd
- [etcd: операции](../../Concepts/etcd_operations.md) — detailed обзор etcdctl команд
- [etcd: альтернативы и безопасность](../../Concepts/etcd_alternatives_and_security.md) — Kine, шифрование
- [Backup стратегии](../../Operations/backup-strategies.md) — общие стратегии backup в Kubernetes
- [Официальная документация etcdctl](https://etcd.io/docs/v3.5/op-guide/)
