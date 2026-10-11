# Развертывание Ceph через cephadm

Руководство по установке и первоначальному конфигурированию кластера Ceph средствами `cephadm` для не-облачных (self-hosted) сред. Документ описывает процедуру от подготовки хостов до запуска первых демонов и подключения хранилищ, актуальную для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

> **Границы документа:** тонкая настройка уже запущенного кластера, управление пулами, аварийное восстановление и обновление версий описаны в [Операциях Ceph](./Administration/operations.md); интеграция с Kubernetes — в [PV/PVC Scenarios](../pv_and_pvc_scenarios.md) и [Ceph в Kubernetes](../pv_and_pvc_scenarios.md).

## Определения

**cephadm** — официальный инструмент развертывания и жизненного цикла кластера Ceph, запускающий демонов в контейнерах и управляющий ими через systemd. В 2026 году `cephadm` является единственным поддерживаемым способом установки и обновления Ceph.

**Bootstrap** — первоначальная инициализация кластера: создание первого MON и MGR, генерация ключей, настройка публичной/приватной сети и Dashboard.

**FSID** (File System Identifier) — уникальный идентификатор кластера, генерируемый при bootstrap. Используется для управления экземпляром через `cephadm cluster-*` команды.

**Service Specification** — YAML-описание желаемого состояния сервиса (размещение, количество экземпляров, параметры). Применяется через `ceph orch apply`.

**Drive Group / OSDSpec** — декларативное описание политики создания OSD на основе меток хостов и свойств дисков (rotational, device class).

## Базовые концепции

### Архитектура развертывания

```
┌─────────────────────────────────────────────────────────────┐
│  Admin-узел (bootstrap)                                    │
│  - cephadm + ceph-common                                   │
│  - SSH-ключ для распространения на хосты                    │
│  - /etc/ceph/ceph.conf (глобальный)                        │
└───────────────────────┬─────────────────────────────────────┘
                        │
     ┌──────────────────┼──────────────────┐
     │                  │                  │
     ▼                  ▼                  ▼
  host-a              host-b             host-c
  MON + MGR + OSD    MON + MGR + OSD   MON + MGR + OSD
```

**Минимальная конфигурация для запуска:**
- 3 узла (для кворума MON)
- ОС: Linux (Debian/Ubuntu/RHEL/Rocky)
- Docker или Podman (зависит от дистрибутива; `cephadm` сам определяет доступный)
- SSH-доступ с root/sudo с admin-узла на все хосты кластера

### Сети

Ceph использует две логические сети:

| Сеть | Назначение | Рекомендации |
|------|-----------|--------------|
| **Public** | Клиентский трафик, мониторы, MGR, Dashboard | Отдельный VLAN/interfacе, маршрутизируемая с клиентскими подсетями |
| **Cluster** | Репликация OSD→OSD, ребалансировка, backfill | Выделенный интерфейс (10/25/40/100 Гбит/с), минимальная задержка |

Для небольших кластеров допускается одна объединенная сеть, но для production это анти-паттерн: репликация конкурирует за полосу с клиентским I/O.

### Версии и кодовые имена

| Версия | Кодовое имя | Статус (2026) |
|--------|-------------|---------------|
| 21.x | Umbrella | Stable / Latest |
| 20.x | Tentacle | Maintenance |
| 19.x | Squid | End of Life (сентябрь 2026) |
| 18.x | Reef | End of Life |

Для новых инсталляций в конце 2026 года используйте **Umbrella (21.x)**.

## Практические сценарии

### 1. Подготовка admin-узла

#### 1.1 Установка cephadm

```bash
# Debian/Ubuntu
curl -fsSL https://download.ceph.com/keys/release.asc | sudo gpg --dearmor -o /usr/share/keyrings/ceph-release-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ceph-release-archive-keyring.gpg] https://download.ceph.com/debian-umbrella $(lsb_release -sc) main" | sudo tee /etc/apt/sources.list.d/ceph.list
sudo apt update && sudo apt install -y cephadm

# RHEL/Rocky/Alma
curl -fsSL https://download.ceph.com/keys/release.asc | sudo gpg --dearmor -o /usr/share/keyrings/ceph-release-archive-keyring.gpg
sudo tee /etc/yum.repos.d/ceph.repo <<EOF
[ceph-base]
name=Ceph Base Repository
baseurl=https://download.ceph.com/rpm-umbrella/el9/\$basearch
enabled=1
gpgcheck=1
gpgkey=/usr/share/keyrings/ceph-release-archive-keyring.gpg
EOF
sudo dnf install -y cephadm
```

#### 1.2 Распространение SSH-ключа

```bash
# Генерация ключа (если еще нет)
ssh-keygen -t ed25519 -C "cephadm@admin" -f ~/.ssh/cephadm

# Распространение на все хосты кластера
for host in host-a host-b host-c; do
  ssh-copy-id -i ~/.ssh/cephadm.pub root@$host
done

# Проверка
for host in host-a host-b host-c; do
  ssh -i ~/.ssh/cephadm root@$host "hostname && systemctl is-active systemd-timesyncd"
done
```

> **Требование к хостам:** fully-qualified hostname (FQDN), резолвится со всех узлов; NTP синхронизирован (критично для кворума MON).

### 2. Bootstrap кластера

```bash
# Минимальный bootstrap с тремя MON
sudo cephadm bootstrap \
  --mon-ip <ip-host-a> \
  --allow-ssh-from-host <subnet> \
  --cluster-network <cluster-subnet> \
  --ssh-user root \
  --ssh-private-key ~/.ssh/cephadm \
  --initial-dashboard-user admin \
  --initial-dashboard-password <secure-password>
```

**Ключевые параметры:**

| Параметр | Значение | Примечание |
|----------|----------|------------|
| `--mon-ip` | IP первого MON | Используется для первого контакта |
| `--cluster-network` | Подсеть для replication | Ускоряет backfill/recovery |
| `--allow-ssh-from-host` | Доверенная подсеть | Ограничивает управляющий доступ |
| `--ssh-private-key` | Путь к приватному ключу | Если не `~/.ssh/id_*` |
| `--initial-dashboard-user` | Логин Dashboard | По умолчанию `admin` |
| `--initial-dashboard-password` | Пароль Dashboard | Генерируйте сложный |

После успешного bootstrap:

```bash
# Проверка состояния
ceph status
# → health: HEALTH_OK
# → mon: 3 daemons, quorum host-a,host-b,host-c
# → mgr: xxxx(active), yyyy(standby)

# Доступ к Dashboard
# https://<ip-host-a>:8443
# Логин: admin / Пароль: <указанный>
```

### 3. Добавление хостов

```bash
# Добавление хоста с labels
ceph orch host add host-d --labels=osd_hdd
ceph orch host add host-e --labels=osd_nvme

# Проверка
ceph orch host ls
# → NAME   ADDR              LABELS  STATUS
# → host-d 192.168.1.10      osd_hdd
# → host-e 192.168.1.11      osd_nvme

# Регистрация SSH-ключа для нового хоста
ceph cephadm check-host host-d
# → если есть предупреждения — исправить SSH/домен
```

### 4. Развертывание OSD

#### 4.1 Автоматическое развертывание на всех свободных дисках

```bash
# Dry-run: посмотреть, что будет создано
ceph orch apply osd --all-available-devices --dry-run

# Фактическое создание
ceph orch apply osd --all-available-devices

# Мониторинг
ceph orch ps --daemon-type osd
ceph osd tree
```

#### 4.2 Drive Group: точечное размещение по классам

```yaml
# spec-hdd.yaml
service_type: osd
service_id: hdd_osds
placement:
  label: osd_hdd
data_devices:
  rotational: 1
db_devices:
  rotational: 0
  size: "200G:"
wal_devices:
  rotational: 0
  size: "50G:"
```

```yaml
# spec-nvme.yaml
service_type: osd
service_id: nvme_osds
placement:
  label: osd_nvme
data_devices:
  rotational: 0
  size: "500G:"
```

```bash
# Применение
ceph orch apply -i spec-hdd.yaml
ceph orch apply -i spec-nvme.yaml
```

> **Важно:** при указании `db_devices`/`wal_devices` Ceph создает LVM на этих устройствах для shared metadata. Убедитесь, что устройства достаточно большие и не содержат данных.

### 5. Развертывание сервисов

#### 5.1 MON и MGR (дополнительные)

```bash
# Декларативное размещение MON (3 штуки на разных хостах)
ceph orch apply mon --placement="3 host-a host-b host-c"

# MGR: минимум 2
ceph orch apply mgr --placement="2 host-a host-b"
```

#### 5.2 RGW (S3-шлюз)

```yaml
# spec-rgw.yaml
service_type: rgw
service_id: rgw.s3
placement:
  count: 3
spec:
  rgw_frontend_port: 80
```

```bash
ceph orch apply -i spec-rgw.yaml
```

#### 5.3 MDS для CephFS

```bash
# Создание файловой системы (пools создаются автоматически в новых версиях)
ceph fs new cephfs cephfs_metadata cephfs_data --force

# Развертывание MDS через placement
ceph orch apply mds cephfs --placement="3 host-a host-b host-c"
```

### 6. Первичная настройка

#### 6.1 Сети

```bash
# Проверка текущей конфигурации
ceph config get mon public_network
ceph config get mon cluster_network

# Установка (если bootstrap не задал автоматически)
ceph config set mon public_network 10.0.0.0/24
ceph config set mon cluster_network 10.0.1.0/24
```

#### 6.2 Классы устройств и CRUSH правила

```bash
# Автоматическое определение классов
ceph osd crush class ls

# Ручная привязка OSD к классу (если auto-detection не сработал)
ceph osd crush set-device-class hdd osd.0 osd.1 osd.2
ceph osd crush set-device-class ssd osd.3 osd.4
ceph osd crush set-device-class nvme osd.5 osd.6

# Правило для HDD
ceph osd crush rule create-replicated hdd_rule default host hdd
ceph osd pool set <pool-name> crush_rule hdd_rule
```

### 7. Верификация кластера

```bash
# Общая картина
ceph status
# → health: HEALTH_OK
# → services: mon: 3/3, mgr: xxxx(active), yyyy(standby)
# → osd: 12/12 up, 12/12 in

# Детальная проверка OSD
ceph osd tree
# → ID  CLASS  WEIGHT   TYPE NAME          STATUS
# → 0   hdd    1.0       host host-a
# → 1   hdd    1.0           osd.1            up  1.00

# Проверка пулов
ceph osd pool ls detail
ceph osd pool autoscale-status

# Проверка конфигурации
ceph config dump | less

# Проверка Dashboard
curl -k https://<mon-ip>:8443/api/health
```

### 8. Ад-hoc операции (одноразовые задачи)

#### 8.1 Вход в shell контейнера демона

```bash
# Shell внутри контейнера демона
cephadm shell -- ceph -s
cephadm shell -- ceph osd tree

# Shell на конкретном хосте
cephadm shell --host host-a -- df -h
```

#### 8.2 Логи оркестратора

```bash
# Логи в реальном времени
ceph orch log watch

# Последние 100 строк
ceph orch log tail -n 100
```

#### 8.3 Просмотр статуса сервисов

```bash
# Все сервисы
ceph orch ls

# Детализация по демонам
ceph orch ps --service_type osd
ceph orch ps --hostname host-a
```

### 9. Версия кластера и обновление

```bash
# Текущие версии демонов
ceph versions

# Доступные целевые версии для апгрейда
ceph orch upgrade ls

# Старт апгрейда (одна мажорная версия за раз!)
ceph orch upgrade start --ceph-version 21.2.1

# Статус апгрейда
ceph orch upgrade status
```

Подробное руководство по обновлению — в [Операциях Ceph](./Administration/operations.md#11-обновление-версий-кластера-cephadm-upgrade).

### 10. Бэкап состояния кластера

```bash
DATE=$(date +%F)
ceph config dump -f json-pretty        > ceph-config-${DATE}.json
ceph auth export -o ceph-auth-${DATE}.export
ceph -s -f json-pretty                 > ceph-status-${DATE}.json
ceph mon dump -f json-pretty           > ceph-monmap-${DATE}.json
ceph osd getcrushmap -o ceph-crushmap-${DATE}.bin
ceph orch ls --export -o ceph-specs-${DATE}.yaml
```

Храните бэкапы офлайн от кластера.

## Дополнительная информация

### См. также

- [Обзор Ceph](./ceph_overview.md) — архитектура, компоненты, интерфейсы
- [Операции Ceph](./Administration/operations.md) — управление хостами, OSD, MON, MGR, аварийные процедуры
- [Мониторинг Ceph](./Administration/monitoring.md) — Prometheus, метрики, алертинг
- [Расчет Placement Groups](./ceph_placement_groups.md) — математика PG и автоскейлинг
- [Ceph в Kubernetes](../pv_and_pvc_scenarios.md) — Rook-Ceph и CSI
- [Бенчмаркинг](./ceph_benchmarks.md) — тестирование производительности

### Официальные ресурсы

- [Cephadm Installation Guide](https://docs.ceph.com/en/latest/cephadm/install/) — установка cephadm
- [Cephadm Bootstrap](https://docs.ceph.com/en/latest/cephadm/install/#bootstrapping) — процедура bootstrap
- [Cephadm Host Management](https://docs.ceph.com/en/latest/cephadm/host-management/) — добавление, drain, maintenance хостов
- [Cephadm OSD Service](https://docs.ceph.com/en/latest/cephadm/services/osd/) — Drive Group и OSD-спецификации
