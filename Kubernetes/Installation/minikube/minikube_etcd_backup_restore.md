# Minikube: бэкап и восстановление etcd

## Определения

**etcd** — распределённое KV-хранилище, являющееся «источником истины» для всех объектов Kubernetes (Pods, Services, Secrets, ConfigMaps и т.д.). В Minikube etcd работает как один узел внутри VM/контейнера. Подробнее: [etcd: Overview](../../../Concepts/etcd_overview.md).

**Снапшот (Snapshot)** — inconsistencies-снимок состояния etcd. Используется для бэкапа и восстановления. etcd поддерживает online-создание снапшотов через `etcdctl snapshot save`.

**Defragmentation** — процесс физического освобождения дискового пространства после удаления ключей. etcd хранит данные в B+ дереве; при удалении ключей освобождаются только ячейки, дефрагментация перестраивает файл.

**Wal (Write-Ahead Log)** — журнал предварительной записи, обеспечивающий durability при аварийных завершениях. При восстановлении из снапшота Wal воспроизводится.

---

## Базовые концепции

### Особенности etcd в Minikube

| Параметр | Standard K8s (kubeadm) | Minikube |
| :--- | :--- | :--- |
| **Расположение данных** | `/var/lib/etcd/` на master-узле | Внутри VM/контейнера Minikube |
| **Доступ к etcdctl** | Прямой (bash на master) | Через `minikube ssh` |
| **TLS** | Клиентский сертификат | Автоматически настроенный Minikube |
| **Режим работы** | Кластер (3+ узла) | Один узел (single-node) |
| **Бэкап стратегия** | Регулярные снапшоты + off-site | Ручной бэкап перед `minikube delete` |

### Когда нужен бэкап etcd в Minikube

- Перед `minikube delete` (если кластер восстанавливаемый).
- Перед миграцией данных между профилями Minikube.
- Для тестирования процедур восстановления (drill).
- Перед обновлением версии Kubernetes (если используется `--kubernetes-version`).

---

## Практические сценарии

### Шаг 1: Доступ к etcd из Minikube

```bash
# Вход в Minikube VM
minikube ssh

# Проверка, что etcd запущен
sudo crictl ps | grep etcd
# → etcd-amd64               ...   Running   ...

# ПроверкаPID etcd
ps aux | grep etcd
# → root  1234 ... etcd --advertise-client-urls=...
```

### Шаг 2: Установка etcdctl (если не установлен)

```bash
# etcdctl входит в состав Minikube image
minikube ssh "etcdctl version"
# → etcdctl version: 3.5.x
# → API version: 3.5

# Если etcdctl отсутствует:
minikube ssh "curl -L https://github.com/etcd-io/etcd/releases/download/v3.5.16/etcd-v3.5.16-linux-amd64.tar.gz -o /tmp/etcd.tar.gz && tar xzf /tmp/etcd.tar.gz -C /tmp && sudo mv /tmp/etcd-v3.5.16-linux-amd64/etcdctl /usr/local/bin/"
```

### Шаг 3: Создание снапшота (бэкап)

```bash
# Получение путей к TLS-сертификатам
minikube ssh "cat /etc/kubernetes/pki/etcd/ca.crt" > /tmp/etcd-ca.crt
minikube ssh "cat /etc/kubernetes/pki/etcd/server.crt" > /tmp/etcd-server.crt
minikube ssh "cat /etc/kubernetes/pki/etcd/server.key" > /tmp/etcd-server.key

# Создание снапшота (внутри Minikube)
minikube ssh "sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /tmp/etcd-snapshot-$(date +%Y%m%d).db"

# Проверка снапшота
minikube ssh "sudo ETCDCTL_API=3 etcdctl snapshot status /tmp/etcd-snapshot-$(date +%Y%m%d).db --write-out=table"
# → +---------+----------+------------+--------+
# | REVISION | TOTAL KEYS| TOTAL SIZE | HEALTH |
# +---------+----------+------------+--------+
# |    12345 |      567 |     2.1 MB |  OK   |
# +---------+----------+------------+--------+

# Копирование снапшота на хост
minikube cp minikube:/tmp/etcd-snapshot-$(date +%Y%m%d).db ~/etcd-backup/
```

### Шаг 4: Бэкап через Докер/Контейнер (альтернативный способ)

```bash
# Если Minikube использует Docker-драйвер
# Найти контейнер Minikube
docker ps | grep minikube
# → minikube   ...   Running

# Выполнить команду внутри контейнера
docker exec minikube sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /tmp/etcd-snapshot.db

# Копирование на хост
docker cp minikube:/tmp/etcd-snapshot.db ~/etcd-backup/
```

### Шаг 5: Восстановление из снапшота

> **Внимание:** Восстановление перезаписывает все данные etcd. Выполните `minikube stop` перед восстановлением.

```bash
# Остановка Minikube
minikube stop

# Запуск Minikube (для доступа к etcd)
minikube start

# Копирование снапшота обратно в Minikube
minikube cp ~/etcd-backup/etcd-snapshot-20260901.db /tmp/restore-snapshot.db

# Восстановление
minikube ssh "sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot restore /tmp/restore-snapshot.db \
  --data-dir=/var/etcd-restore \
  --name=minikube \
  --initial-cluster=minikube=https://127.0.0.1:2380 \
  --initial-advertise-peer-urls=https://127.0.0.1:2380"

# Перезапуск Minikube (etcd подхватит восстановленные данные)
minikube stop && minikube start

# Проверка
kubectl get pods -A
kubectl get svc -A
```

### Шаг 6: Полный скрипт бэкапа

```bash
#!/bin/bash
# minikube-etcd-backup.sh
# Регулярный бэкап etcd в Minikube

set -euo pipefail

BACKUP_DIR="${HOME}/minikube-etcd-backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SNAPSHOT_FILE="etcd-snapshot-${TIMESTAMP}.db"

mkdir -p "${BACKUP_DIR}"

echo "[*] Проверка состояния Minikube..."
if ! minikube status | grep -q "Running"; then
    echo "[!] Minikube не запущен. Запустите: minikube start"
    exit 1
fi

echo "[*] Создание снапшота etcd..."
minikube ssh "sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /tmp/${SNAPSHOT_FILE}"

echo "[*] Копирование на хост..."
minikube cp minikube:/tmp/${SNAPSHOT_FILE} "${BACKUP_DIR}/${SNAPSHOT_FILE}"

echo "[*] Проверка целостности снапшота..."
minikube ssh "sudo ETCDCTL_API=3 etcdctl snapshot status /tmp/${SNAPSHOT_FILE} --write-out=table"

echo "[*] Очистка временного файла в Minikube..."
minikube ssh "sudo rm /tmp/${SNAPSHOT_FILE}"

echo "[+] Бэкап сохранён: ${BACKUP_DIR}/${SNAPSHOT_FILE}"
ls -lh "${BACKUP_DIR}/${SNAPSHOT_FILE}"
```

```bash
chmod +x minikube-etcd-backup.sh
./minikube-etcd-backup.sh
```

### Диагностика

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `etcdctl: command not found` | etcdctl не установлен в Minikube image | Используйте альтернативный способ (Docker exec) или установите etcdctl |
| `connection refused` | etcd не запущен или неправильный endpoint | Проверьте: `minikube ssh "ps aux \| grep etcd"` |
| `certificate verify failed` | Неправильные пути к TLS-сертификатам | Проверьте: `minikube ssh "ls /etc/kubernetes/pki/etcd/"` |
| `snapshot is corrupt` | Повреждённый снапшот | Повторите создание снапшота; проверьте свободное место |

---

## Дополнительная информация

### См. также

- [etcd: Overview](../../../Concepts/etcd_overview.md) — архитектура и принципы работы
- [etcd: Practical Operations](../../../Concepts/etcd_operations.md) — дефрагментация, health check, resize
- [Minikube: Определения и концепции](./minikube_concepts.md) — жизненный цикл и хранение данных

### Полезные ссылки

- [etcd Snapshots — Official Docs](https://etcd.io/docs/v3.5/op-guide/maintenance/#snapshot-backup)
- [Minikube SSH — Official Docs](https://minikube.sigs.k8s.io/docs/commands/ssh/)
