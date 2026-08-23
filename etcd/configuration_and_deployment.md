# Конфигурация и развертывание etcd

**etcd** в production почти никогда не запускается через флаги напрямую. Используется YAML-конфиг или environment variables, а также systemd-юнит для управления жизненным циклом. Правильная конфигурация критична для стабильности кластера.

## Определения

| Термин | Описание |
| :--- | :--- |
| **etcd.conf.yml** | YAML-файл конфигурации, объединяющий все параметры. Приоритетнее флагов командной строки. |
| **Static Pod** | Под, управляемый kubelet напрямую (в `/etc/kubernetes/manifests`). Стандартный способ запуска etcd в K8s. |
| **systemd unit** | Юнит для запуска etcd как systemd-сервиса (bare metal, VMs). |
| **data-dir** | Директория с данными: `member/snap/` (снапшоты), `member/wal/` (WAL), `db` (BoltDB). |
| **initial-cluster** | Список всех членов первичного кластера в формате `name=peerURL`. |
| **initial-cluster-state** | `new` для нового кластера, `existing` для добавления к существующему. |
| **initial-cluster-token** | Идентификатор кластера, предотвращающий случайное слияние при восстановлении из снапшота. |

---

## Основные концепции

### Структура конфигурационного файла

```yaml
# /etc/etcd/etcd.conf.yml
name: node1
data-dir: /var/lib/etcd

# Raft
listen-peer-urls: https://10.0.1.10:2380
initial-advertise-peer-urls: https://10.0.1.10:2380
initial-cluster: node1=https://10.0.1.10:2380,node2=https://10.0.1.11:2380,node3=https://10.0.1.12:2380
initial-cluster-state: existing
initial-cluster-token: etcd-cluster-1

# Client
listen-client-urls: https://10.0.1.10:2379
advertise-client-urls: https://10.0.1.10:2379

# TLS
peer-trusted-ca-file: /etc/etcd/pki/ca.crt
peer-cert-file: /etc/etcd/pki/peer.crt
peer-key-file: /etc/etcd/pki/peer.key
client-trusted-ca-file: /etc/etcd/pki/ca.crt
client-cert-file: /etc/etcd/pki/server.crt
client-key-file: /etc/etcd/pki/server.key

# Performance
auto-compaction-retention: 5m
quota-backend-bytes: 8589934592  # 8 GB
snapshot-count: 10000
heartbeat-interval: 100
election-timeout: 1000

# Logging
log-level: info
logger: zap
```

**Merge с флагами:** Флаги командной строки имеют приоритет над конфигом. Рекомендуется использовать только конфиг, чтобы избежать расхождений.

### Запуск через systemd (bare metal / VM)

```ini
# /etc/systemd/system/etcd.service
[Unit]
Description=etcd key-value store
After=network.target

[Service]
Type=notify
Environment=ETCD_CONF=/etc/etcd/etcd.conf.yml
ExecStart=/usr/bin/etcd --config-file ${ETCD_CONF}
Restart=always
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

**Важно:**
- `LimitNOFILE` должен быть ≥ 65536 (по умолчанию часто 1024).
- `RestartSec=5s` предотвращает слишком частые перезапуски при сбоях.
- `Type=notify` — etcd отправляет sd_notify, systemd знает о статусе.

### Запуск как Static Pod (Kubernetes)

```yaml
# /etc/kubernetes/manifests/etcd.yaml
apiVersion: v1
kind: Pod
metadata:
  name: etcd
  namespace: kube-system
spec:
  containers:
  - name: etcd
    image: registry.k8s.io/etcd:3.7.1
    command:
    - etcd
    - --config-file=/etc/etcd/etcd.conf.yml
    volumeMounts:
    - name: etcd-data
      mountPath: /var/lib/etcd
    - name: etcd-conf
      mountPath: /etc/etcd
    - name: pki
      mountPath: /etc/kubernetes/pki/etcd
      readOnly: true
  volumes:
  - name: etcd-data
    hostPath:
      path: /var/lib/etcd
  - name: etcd-conf
    hostPath:
      path: /etc/etcd
  - name: pki
    hostPath:
      path: /etc/kubernetes/pki/etcd
```

**Важно:** При изменении конфигурации Static Pod kubelet автоматически перезапустит etcd. Это может вызвать кратковременную недоступность кластера (если перезапускается лидер). Используйте `--config-file`, чтобы избежать перезапуска при изменении env-переменных.

---

## Практические сценарии

### Безопасное изменение конфигурации

1. **Изменение без перезапуска (если поддерживается):** Некоторые параметры (например, `--quota-backend-bytes`) можно изменить через etcdctl maintenance, но большинство требует перезапуска.
2. **Перезапуск с минимальным влиянием:**
   ```bash
   # 1. Передать лидерство на другой узел
   etcdctl move-leader <OTHER_MEMBER_ID>

   # 2. Перезапустить etcd
   systemctl restart etcd

   # 3. Проверить здоровье
   etcdctl endpoint health --cluster
   ```

### Проверка конфигурации

```bash
# Проверить действующие параметры etcd (v3.7+)
etcdctl --endpoints=https://127.0.0.1:2379 get /db/config -w json
# Некоторые параметры хранятся в /db/config

# Проверить, что конфиг загружен корректно
journalctl -u etcd -n 50 | grep "config"
# → loaded configuration from /etc/etcd/etcd.conf.yml
```

### Разделение директорий для WAL и данных

Для минимизации задержек `fdatasync` размещайте WAL и данные на отдельных дисках:

```bash
# Структура
/var/lib/etcd/wal → NVMe disk 1 (dedicated)
/var/lib/etcd/member → NVMe disk 2 (dedicated)
```

Или через символические ссылки (если `--data-dir` одна):

```bash
mv /var/lib/etcd/member/wal /var/lib/etcd/wal
ln -s /var/lib/etcd/wal /var/lib/etcd/member/wal
```

**Валидация:**
```bash
# Проверить, что WAL на отдельном диске
df -h /var/lib/etcd/wal
# → /dev/nvme1n1p1
```

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `etcd: data-dir already exists` | Директория не пуста при `--initial-cluster-state new` | Используйте `existing` или очистите директорию |
| `etcdserver: public adress ... not in --initial-cluster` | Конфликт peer URL | Проверьте `--initial-cluster` и `--name` |
| `failed to find member` | Неверный `--initial-cluster` | Убедитесь, что все `name=peerURL` корректны |
| `no such file or directory: /etc/etcd/etcd.conf.yml` | Указан неверный путь | Проверьте `--config-file` или `ETCD_CONF` |
| `context deadline exceeded` при старте | WAL поврежден или диск недоступен | Проверьте `etcdutl wal verify`, `df -h`, `dmesg` |

---

## Best Practices

- **Используйте `--config-file`:** Все параметры в одном YAML. Избегайте флагов в systemd-юните.
- **`LimitNOFILE=65536`:** Обязательно для production. Проверьте: `cat /proc/$(pgrep etcd)/limits | grep "open files"`.
- **Отдельный диск для data-dir:** Никогда не размещайте `data-dir` на общем диске с ОС или другими сервисами.
- **`initial-cluster-token`:** Всегда используйте уникальный токен. Восстановление из снапшота с общим токеном может слить кластеры.
- **Не храните пароли в конфиге:** Используйте environment variables или секреты (Kubernetes Secrets, Vault).
- **Hot-reload:** Большинство параметров не поддерживают hot-reload. Планируйте изменения в окно обслуживания.

---

## Edge Cases

- **Смена `--name`:** Невозможно без полного восстановления из снапшота. `--name` является частью identity в Raft.
- **Смена `--listen-peer-urls`:** Требует обновления `--initial-cluster` на ВСЕХ узлах.
- **Восстановление на другую архитектуру:** Снапшоты несовместимы (amd64 → arm64). Используйте логический backup (`etcdctl get --prefix`).
- **Static Pod и `hostPath`:** Убедитесь, что `hostPath` существует на всех control plane узлах, иначе Pod не запустится.

---

## См. также

* **[Прокси-режим и масштабирование](./proxy_mode.md)** — прокси для read-heavy нагрузок.
* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — пути записи и чтения.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — развёртывание и бэкап кластера.
