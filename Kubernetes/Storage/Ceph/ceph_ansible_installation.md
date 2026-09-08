# Установка и поддержка Ceph через ceph-ansible

Документ охватывает автоматизированное развертывание и сопровождение кластеров Ceph через `ceph-ansible`. Является основным справочником для поддержки legacy-кластеров и планирования миграции на `cephadm`.

---

## Определения

### Инструменты автоматизации

**`ceph-ansible`** — официальный в прошлом набор ролей Ansible для автоматизации развертывания и управления кластером Ceph. Обеспечивает идемпотентность операций, централизованное управление конфигурацией через `group_vars/` и повторное использование готовых плейбуков.

> **Статус проекта (Август 2026)**: **Legacy (Устарел)**. Проект находится в режиме ограниченной поддержки для критических исправлений. Начиная с версии Ceph Pacific (16.x) и более новых (**Squid**, **Tentacle**, **Umbrella**), основным инструментом является **cephadm**. Использование `ceph-ansible` в 2026 году рекомендуется исключительно для обслуживания существующих (legacy) кластеров и подготовки их к миграции.

**Ansible Controller (Control Node)** — машина, с которой запускается `ansible-playbook`. Не требует установки Ceph-клиента на самом контроллере (достаточно пакета `ceph-common` для управления после развертывания). Контроллер не входит в кластер Ceph и не хранит данные.

**Playbook** — YAML-файл с описанием последовательности задач (tasks) для развертывания или изменения состояния кластера. `ceph-ansible` предоставляет несколько плейбуков для различных сценариев.

### Конфигурация Ansible

**Inventory (Инвентарь)** — INI-файл, описывающий хосты кластера и их принадлежность к группам (mons, osds, mgrs, mds, rgws). Каждая группа映射ируется на набор плейбуков `ceph-ansible`.

**group_vars/** — директория, содержащая YAML-файлы переменных для групп из инвентаря. Основные файлы: `all.yml` (общие настройки), `mons.yml`, `osds.yml`, `mgrs.yml`, `mds.yml`.

**extra_vars** — переменные, передаваемые через `-e "key=value"` при запуске плейбука. Переопределяют значения из `group_vars/`. Используются для разовых настроек или переопределения без редактирования файлов.

### Компоненты хранилища OSD

**BlueStore** — современный и рекомендуемый бэкенд для OSD. Работает напрямую с блочным устройством ( whole disk или LV), минуя файловую систему. Поддерживает SSD/NVMe и HDD. Использует RocksDB для метаданных и блочное устройство для данных.

**FileStore** — устаревший бэкенд OSD, использовавший XFS/ext4 и отдельный journal. **Не рекомендуется** для новых установок. Требует отдельного journal-устройства (или tmpfs), что усложняет конфигурацию.

**`ceph-volume`** — утилита для создания LVM-томов, управляемых `ceph-ansible`. Поддерживает три сценария provisioning: `lvm` (управляемый через `ceph-volume lvm`), `simple` (простая настройка через systemd), `raw` (прямое использование дисков).

**LVM (Logical Volume Manager)** — система управления логическими томами. В контексте Ceph используется для создания OSD из отдельных дисков, разделов или LV- групп. Преимущество: возможность gestión дисков без переформатирования.

**Drive Group** — описание группы дисков для OSD в `cephadm`. В `ceph-ansible` аналогом являются переменные `devices` или `dedicated_devices` в `osds.yml`. Drive Groups позволяют гибко назначать role (data, wal, db) на физические устройства.

### Сетевые компоненты

**Public Network (`public_network`)** — сеть для клиентского трафика и взаимодействия мониторов. Доступна всем компонентам кластера. Рекомендуется выделять отдельную подсеть для Ceph.

**Cluster Network (`cluster_network`)** — изолированная сеть для внутреннего трафика: репликация OSD, восстановление данных (recovery/backfill), heartbeat. Не доступна клиентам. Стандарт 2026: 25/40+ Гбит/с.

**Monitor Address (`monitor_address`)** — IP-адрес монитора для общения с другими компонентами. Указывается в инвентаре для каждого хоста. Должен быть доступен из cluster_network.

---

## Основные концепции

### Архитектура кластера Ceph

Кластер Ceph состоит из следующих компонентов, каждый из которых развертывается отдельным плейбуком:

| Компонент | Роль | Минимум | Рекомендация |
|-----------|------|---------|--------------|
| **MON** | Мониторы: отслеживают состояние кластера, карту OSD/PG | 3 (нечётное) | 3-5 (нечётное, для кворума) |
| **MGR** | Менеджеры: метрики, dashboard, orchestrator | 2 (активный + standby) | 2-3 (на MON-хостах или отдельно) |
| **OSD** | Хранение данных: управление дисками | 3 (min_size=2) | От 6 (лучше 12+) |
| **MDS** | Метаданные CephFS (только для CephFS) | 0 (не обязателен) | 1-2 (для CephFS) |
| **RGW** | S3/Swift API (объектное хранилище) | 0 (не обязателен) | 2+ (для HA) |
| **Dashboard** | Веб-интерфейс управления | Встроен в MGR | Встроен в MGR |

**Минимальный кластер** (лаборатория): 3 MON + 3 OSD (на отдельных дисках) + 1 MGR. Этого достаточно для работы RADOS и RBD.

**Рекомендуемый кластер** (production): 3 MON + 9+ OSD (на 3+ хостах) + 2 MGR + 1 MDS (если нужен CephFS).

### Версионирование и совместимость

| Ветка ceph-ansible | Версия Ceph | Статус (Август 2026) | Совместимость |
| :--- | :--- | :--- | :--- |
| `stable-5.0` | Octopus (15.x) | **End of Life** | Ansible 2.9 |
| `stable-6.0` | Pacific (16.x) | **Maintenance Only** | Ansible 2.9-2.11 |
| `stable-7.0` | Quincy (17.x) | **Legacy Support** | Ansible 2.11-2.12 |
| `stable-8.0` | Reef (18.x) | **Limited Support** | Ansible 2.12+ |
| `stable-9.0` | Squid/Tentacle | **Experimental** | Ansible 2.14+ (не рекомендуется) |

> **Важно:** начиная с Squid (19.x), `cephadm` является единственным поддерживаемым способом развертывания. `ceph-ansible` для Squid/Tentacle находится в экспериментальном статусе и НЕ рекомендуется для production.

### Структура переменных и конфигурации

Порядок переопределения переменных (от низшего к высшему приоритету):

1. `group_vars/all.yml` — общие настройки для всех хостов
2. `group_vars/<group>.yml` — настройки для конкретной группы (mons, osds, mgrs)
3. `host_vars/<hostname>.yml` — настройки для конкретного хоста
4. `extra_vars` (`-e "key=value"`) — переопределяют все вышеперечисленные
5. `ceph_conf_overrides` — параметры, записываемые в `[ceph.conf]` на каждом узле

**Примечание по `ceph_conf_overrides`:** параметры из этого словаря записываются в `/etc/ceph/ceph.conf` на каждом хосте. Некоторые параметры применяются динамически без рестарта, другие требуют перезапуска демона. См. [Централизованное управление конфигурацией](./Administration/operations.md#10-централизованное-управление-конфигурацией).

### Конфигурация OSD: сценарии provisioning

| Сценарий | Описание | Рекомендация |
|----------|----------|--------------|
| `lvm` | Использует `ceph-volume lvm` для создания LV-томов на дисках | **Рекомендуется**. Гибкое управление, поддержка WAL/DB. |
| `simple` | Прямая настройка через systemd (без LVM) | Только для тестовых сред. Не поддерживает WAL/DB. |
| `raw` | Использование raw-дисков без LVM | Только для bare-metal с простой конфигурацией. |

**Для production** рекомендуется сценарий `lvm` с выделенными дисками для WAL и DB (если используются NVMe).

### Требования к инфраструктуре

#### Аппаратные требования

| Компонент | Минимум | Рекомендация |
|-----------|---------|--------------|
| **CPU** | 4 ядра | 8+ ядер (для OSD на HDD) |
| **RAM** | 4 ГБ на OSD | 8 ГБ на OSD (BlueStore: ~1 МБ/PG) |
| **Сеть** | 1 Гбит/с | 10/25/40 Гбит/с (cluster_network) |
| **Диски OSD** | 1 HDD/SSD | Dedicated NVMe для WAL/DB |
| **Диски MON** | SSD/NVMe (маленький) | SSD для метаданных мониторов |
| **NTP** | Обязательно | chronyd (синхронизация критична для кворума) |

#### Программные требования

| Компонент | Версия | Примечание |
|-----------|--------|------------|
| **Ansible** | 2.9-2.14 | Зависит от ветки ceph-ansible |
| **Python** | 3.8+ | На контроллере и целевых хостах |
| **Podman/Docker** | Для cephadm (миграция) | Не требуется для ceph-ansible |
| **LVM2** | Для osd_scenario=lvm | Обязателен для provisioning OSD |
| **chrony/ntpd** | Любая стабильная | Синхронизация времени критична |
| **SSH** | Доступ root/sudo | На всех целевых хостах |

#### Сетевые требования

- **Public Network** — доступен для клиентов и мониторов. НЕ должен включать IP-адреса, используемые для cluster_network.
- **Cluster Network** — изолирована от клиентов. Используется для replication, recovery, heartbeat.
- **DNS** — резолвинг hostname -> IP обязателен. Проверка: `getent hosts <hostname>`.
- **Firewall** — открытые порты см. в таблице ниже.

| Порт | Протокол | Назначение |
|------|----------|------------|
| 6789 | TCP | MON (peer communication) |
| 3300 | TCP | MON (электорат, monmap) |
| 6800-7300 | TCP | OSD (data, heartbeat, replication) |
| 8765 | TCP | Dashboard (web) |
| 8443 | TCP | Dashboard (HTTPS) |
| 9283 | TCP | Prometheus (metrics) |

### Ключевые переменные конфигурации

```yaml
# ═══════════════════════════════════════════════════
# group_vars/all.yml — общие настройки
# ═══════════════════════════════════════════════════

# Источник пакетов
ceph_origin: repository
ceph_repository: community
ceph_stable_release: quincy  # ← последняя стабильная для ansible

# Сетевые настройки
public_network: 172.21.0.0/24
cluster_network: 172.21.1.0/24

# Синхронизация времени (КРИТИЧНО для кворума)
ntp_service: chronyd

# Тип хранилища и сценарий provisioning OSD
osd_objectstore: bluestore
osd_scenario: lvm

# Мониторы: auto discovery через inventory
mon_group_name: mons

# Параметры кластера (записываются в ceph.conf)
ceph_conf_overrides:
  global:
    osd_pool_default_size: 3         # ← фактор репликации
    osd_pool_default_min_size: 2     # ← мин. реплик для записи
    osd_pool_default_pg_num: 128     # ← см. Расчет PG
    osd_pool_default_pgp_num: 128
    mon_clock_drift_allowed: 0.05    # ← допустимый дрейф времени
  mon:
    mon_osd_down_out_interval: 600   # ← секунд до вывода OSD (10 мин)
  osd:
    osd_max_backfills: 1             # ← лимит параллельного backfill
    osd_recovery_max_active: 2       # ← макс. активных recovery
    osd_op_threads: 8                # ← потоки операций OSD
```

```yaml
# ═══════════════════════════════════════════════════
# group_vars/osds.yml — настройки OSD
# ═══════════════════════════════════════════════════

# Автообнаружение дисков (все чистые диски)
devices:
  - /dev/sda
  - /dev/sdb
  - /dev/sdc

# WAL/DB на выделенных NVMe (опционально)
# dedicated_devices:
#   - /dev/nvme0n1  # будет разделена между OSD на sda, sdb, sdc

# Количество OSD на хосте (для развертывания)
# osds_per_host: 3

# Флаги безопасности
osd_auto_discovery: true
```

### Пример инвентаря (inventory.ini)

```ini
# ═══════════════════════════════════════════════════
# inventory.ini
# ═══════════════════════════════════════════════════

[mons]
ceph-mon1  monitor_address=172.21.0.10
ceph-mon2  monitor_address=172.21.0.11
ceph-mon3  monitor_address=172.21.0.12

[osds]
ceph-osd1
ceph-osd2
ceph-osd3

[mgrs]
ceph-mon1  # MGR на MON-хостах — допустимо для малых кластеров
ceph-mon2

[mds]
ceph-mon1  # MDS нужен только для CephFS
```

> **Примечание:** `ceph-ansible` использует группы `mons`, `osds`, `mgrs`, `mds`, `rgws` для определения, какие плейбуки применять к каким хостам. Если MDS/MGR размещаются на MON-хостах — укажите их в соответствующих группах.

---

## Практические сценарии

### 1. Развертывание кластера (с нуля)

#### 1.1 Подготовка Ansible Controller

```bash
# Клонирование репозитория
git clone https://github.com/ceph/ceph-ansible.git
cd ceph-ansible

# Переключение на стабильную ветку (последняя для ansible)
git checkout stable-7.0

# Создание изолированного окружения Python
python3 -m venv .venv
source .venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt
# → Установка ansible-core 2.11.x и зависимостей

# Проверка версии
ansible --version
# → ansible-core 2.11.x (или совместимая версия)
```

**Проверка версий (важно!):**

| Ветка ceph-ansible | Требуемая версия Ansible |
|---------------------|--------------------------|
| `stable-7.0` | ansible-core 2.11-2.12 |
| `stable-8.0` | ansible-core 2.12-2.14 |
| `stable-9.0` | ansible-core 2.14+ |

Если установлена несовместимая версия Ansible — `ansible-playbook` выдаст ошибку на этапе ` gather_facts`. Решение: создать отдельное venv с нужной версией.

#### 1.2 Подготовка целевых хостов

На **каждом** целевом хосте (MON, OSD, MGR):

```bash
# 1. Установка Python3 и LVM2
apt-get update && apt-get install -y python3 lvm2 chrony
# или для RHEL/CentOS:
# dnf install -y python3 lvm2 chrony

# 2. Настройка NTP (критично для кворума MON)
systemctl enable --now chronyd
chronyc sources
# → Should show * or . for synchronized source

# 3. Проверка hostname resolution
getent hosts ceph-mon1
# → 172.21.0.10 ceph-mon1

# 4. Создание пользователя ansible (опционально, можно использовать root)
useradd -m -s /bin/bash ansible
echo "ansible ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ansible
```

#### 1.3 Проверка связности (preflight)

```bash
# С контроллера: проверка доступности всех хостов
ansible all -i inventory.ini -m ping -u root
# → ceph-mon1: SUCCESS => {"changed": false, "ping": "pong"}
# → ceph-osd1: SUCCESS => ...

# Проверка SSH-доступа
ansible all -i inventory.ini -m shell -a "hostname" -u root

# Проверка Python3
ansible all -i inventory.ini -m shell -a "python3 --version" -u root

# Проверка NTP
ansible all -i inventory.ini -m shell -a "chronyc tracking | grep 'Leap status'" -u root

# Проверка LVM2 (для osd_scenario=lvm)
ansible osds -i inventory.ini -m shell -a "vgdisplay 2>/dev/null | head -5 || echo 'LVM not configured'" -u root
```

#### 1.4 Настройка group_vars

```bash
# Копирование образцов переменных
cp group_vars/all.yml.sample group_vars/all.yml
cp group_vars/osds.yml.sample group_vars/osds.yml
cp group_vars/mgrs.yml.sample group_vars/mgrs.yml
# (при необходимости: cp group_vars/mds.yml.sample group_vars/mds.yml)

# Редактирование основных настроек
vim group_vars/all.yml   # ← public_network, cluster_network, ceph_stable_release
vim group_vars/osds.yml  # ← devices, osd_scenario
```

#### 1.5 Запуск развертывания

```bash
# Копирование образца плейбука
cp site.yml.sample site.yml

# Просмотр сухого запуска (check mode)
ansible-playbook -i inventory.ini site.yml \
  -u root --check --diff

# Фактическое развертывание
ansible-playbook -i inventory.ini site.yml \
  -u root -b --ask-become-pass --diff

# Развертывание с дополнительными переменными
ansible-playbook -i inventory.ini site.yml \
  -u root -b --ask-become-pass --diff \
  -e "ceph_stable_release=reef" \
  -e "osd_pool_default_size=3"
```

**Время выполнения:**
- 3 OSD: ~5-10 минут
- 9 OSD: ~15-30 минут
- 27+ OSD: ~30-60 минут (зависит от скорости дисков и сети)

#### 1.6 Пост-установочная валидация

```bash
# Общий статус кластера
ceph -s
# → health: HEALTH_OK
#   services: mon: 3 daemons, mgr: 3 daemons, osd: 9 osds

# Проверка OSD
ceph osd tree
# → id  weight  type name  status  reweight  pri-affinity
#   -1  27.000  root default
#   -3  9.000       host ceph-osd1
#   0  3.000            osd.0  up  1.00000  1.00000

# Проверка кворума мониторов
ceph mon stat
# → e3: 3 mons at {ceph-mon1=172.21.0.10:6789/0,...}, election epoch 10, leader 0 ceph-mon1

# Проверка пулов
ceph osd pool ls detail
# → pool 1 'rbd' ... replicated size 3 min_size 2 ...

# Проверка PG
ceph pg stat
# → X pgs: Y active+clean, Z active+undersized
```

### 2. Обслуживание кластера

#### 2.1 Проверка здоровья и текущего состояния

```bash
# Ежедневный чек-лист
ceph -s                                    # → health, services, OSD, PG
ceph health detail                         # → конкретные предупреждения
ceph osd tree                              # → иерархия OSD
ceph pg stat                               # → активные PG
ceph osd perf                              # → latency OSD (ops/sec)
```

#### 2.2 Добавление нового OSD

В `ceph-ansible` для добавления диска на существующий узел:

```bash
# 1. Убедитесь, что новый диск подключен и виден
ansible ceph-osd4 -i inventory.ini -m shell -a "lsblk -o NAME,SIZE,TYPE" -u root

# 2. Добавьте узел в инвентарь (если новый хост)
echo "ceph-osd4" >> inventory.ini

# 3. Запустите плейбук с ограничением по тегам
ansible-playbook -i inventory.ini site.yml \
  --limit ceph-osd4 \
  --tags osds \
  -u root -b

# 4. Проверьте появление OSD
ceph osd tree
# → новый OSD должен быть up/in
```

**Важно:** при добавлении OSD на новый хостбед подключить его ко **всем** нужным группам в инвентаре (mons, osds, mgrs и т.д.).

#### 2.3 Добавление нового монитора

```bash
# 1. Подготовка хоста (python3, chrony, SSH, sudo)
# 2. Добавление в инвентарь
#    [mons]
#    ceph-mon4  monitor_address=172.21.0.13

# 3. Запуск плейбука с ограничением
ansible-playbook -i inventory.ini site.yml \
  --limit ceph-mon4 \
  --tags mons \
  -u root -b

# 4. Проверка кворума
ceph mon stat
# → e4: 4 mons at {...}, election epoch ...
```

#### 2.4 Удаление OSD (безопасное)

```bash
# 1. Убедитесь, что кластер здоров
ceph -s  # → HEALTH_OK

# 2. Установите флаги обслуживания
ceph osd set noout
ceph osd set noscrub

# 3. Проверьте, можно ли безопасно удалить OSD
ceph osd safe-to-destroy <osd_id>
# → OSD <osd_id> is safe to destroy

# 4. Остановите OSD
systemctl stop ceph-osd@<osd_id>

# 5. Выполните запись в инвентаре (убедите OSD удалён из devices)
#    и запустите плейбук
ansible-playbook -i inventory.ini site.yml --tags osds -u root -b

# 6. Снимите флаги
ceph osd unset noout
ceph osd unset noscrub

# 7. Проверьте балансировку
ceph -s  # → PG rebalancing
```

#### 2.5 Обновление кластера

```bash
# 1. Обновите репозиторий ceph-ansible
cd ceph-ansible
git pull

# 2. Проверьте целевую версию в group_vars/all.yml
grep ceph_stable_release group_vars/all.yml

# 3. Запустите плейбук (идемпотентно)
ansible-playbook -i inventory.ini site.yml -u root -b --diff

# 4. Проверьте версию после обновления
ceph versions
# → all: 18.2.0-1 (ref)

# 5. Проверьте здоровье
ceph -s  # → HEALTH_OK
```

> **Рекомендация:** Обновляйте по одному узлу за раз (лимитируйте через `--limit`), чтобы минимизировать влияние на производительность.

### 3. Предотвращение типичных ошибок

#### 3.1 Pre-flight проверки перед запуском

```bash
# Проверка резолвинга hostname
for host in ceph-mon1 ceph-mon2 ceph-mon3 ceph-osd1 ceph-osd2 ceph-osd3; do
  echo -n "$host: "
  getent hosts $host | head -1 || echo "NOT RESOLVED"
done

# Проверка SSH-доступа
for host in ceph-mon1 ceph-mon2 ceph-mon3; do
  echo -n "$host: "
  ssh root@$host "hostname" 2>/dev/null || echo "SSH FAILED"
done

# Проверка NTP
for host in ceph-mon1 ceph-mon2 ceph-mon3; do
  echo -n "$host: "
  ssh root@$host "chronyc tracking 2>/dev/null | grep 'Leap status'" || echo "NTP NOT SYNCED"
done

# Проверка LVM2
ansible osds -i inventory.ini -m shell -a "which lvm 2>/dev/null || echo 'LVM2 NOT INSTALLED'" -u root

# Проверка Python3
ansible all -i inventory.ini -m shell -a "python3 -c 'import json; print(\"OK\")'" -u root
```

#### 3.2 Проверка прав после развертывания

```bash
# Проверка владельца keyring
ls -la /etc/ceph/ceph.client.admin.keyring
# → -rw------- 1 ceph ceph ...  (permissions 0600, owner ceph)

# Если права некорректны:
chown ceph:ceph /etc/ceph/ceph.client.admin.keyring
chmod 0600 /etc/ceph/ceph.client.admin.keyring
```

#### 3.3 Проверка NTP после запуска

```bash
# На каждом MON-хосте
chronyc tracking
# → Leap status : Normal (synchronized)
# → System time : 0.000001234 seconds fast of NTP

# Если синхронизация потеряна:
systemctl restart chronyd
chronyc makestep  # → принудительная синхронизация
```

### 4. Сетевая конфигурация

#### 4.1 Разделение сетей

```bash
# Проверка, что public и cluster сети разделены
ip addr show | grep -E "172.21\.[01]\."

# Проверка доступности между OSD и MON
ping -c 3 172.21.0.10  # MON
ping -c 3 172.21.1.10  # OSD (cluster network)

# Проверка, что cluster network НЕ доступна клиентам
ping -c 3 172.21.1.10  # с клиента — должен быть UNREACHABLE
```

#### 4.2 Firewall (iptables/firewalld)

```bash
# Открытие портов для Ceph (на каждом хосте)
for port in 6789 3300 6800-7300 8765 8443 9283; do
  iptables -A INPUT -p tcp --dport $port -j ACCEPT
done

# Сохранение правил
iptables-save > /etc/iptables/rules.v4
```

### 5. Диагностика и Troubleshooting

#### 5.1 Логи и мониторинг

```bash
# Просмотр логов по демону
tail -f /var/log/ceph/ceph-osd.0.log
tail -f /var/log/ceph/ceph-mon.$(hostname).log

# Поиск ошибок в логах
grep -i "error\|fail\|warn" /var/log/ceph/ceph-osd.0.log | tail -50

# Проверка systemd статуса
systemctl status ceph-osd@0
systemctl status ceph-mon@$(hostname)

# Перезапуск конкретного демона
systemctl restart ceph-osd@0

# Просмотр всех логов Ceph
ls -la /var/log/ceph/
```

#### 5.2 Типичные проблемы

| Проблема | Симптомы | Причины | Решение |
|----------|----------|---------|---------|
| **MON не в кворуме** | `ceph -s`: "no mon quorum" | NTP рассинхронизирован, порт 6789 закрыт, MON down | `chronyc makestep`, проверить firewall, проверить `systemctl status ceph-mon@*` |
| **OSD down** | `ceph osd tree`: osd.N down | Диск failed, сеть недоступна, процесс упал | Проверить `systemctl status ceph-osd@N`, `dmesg`, SMART |
| **Keyring permission denied** | `ceph auth` не работает | Владелец keyring = root | `chown ceph:ceph /etc/ceph/ceph.client.admin.keyring` |
| **Slow Ops** | `ceph osd perf`: latency > 100ms | Диск медленный, сеть перегружена, scrub | Проверить `iostat`, `ceph pg stat`, `noscrub` |
| **PG stuck peering** | `ceph pg dump`: PG в peering > 10 мин | OSD down, конфликт версий | Проверить OSD, `ceph pg <pg_id> query` |
| **HEALTH_WARN POOL_APP_NOT_ENABLED** | `ceph -s`: warning | Пул не привязан к приложению | `ceph osd pool application enable <pool> rbd` |
| **Clock Skew** | `ceph health detail`: clock skew | NTP не работает | Настроить chrony на всех MON |

#### 5.3 Экстренные операции

```bash
# Временное поднятие порогов (если кластер заблокирован)
ceph osd set-full-ratio 0.97   # ← ОСТОРОЖНО! Вернуть после освобождения места
ceph osd set-nearfull-ratio 0.90

# Очистка застрявшего PG
ceph pg repair <pg_id>         # ← только если уверены в целостности

# Просмотр текущих флагов
ceph osd dump | grep flags
```

### 6. Архивирование и резервное копирование

```bash
# Резервное копирование ceph.conf
cp /etc/ceph/ceph.conf /backup/ceph.conf.$(date +%Y%m%d)

# Резервное копирование keyring
cp /etc/ceph/ceph.client.admin.keyring /backup/

# Резервное копирование всех ключей Ceph
ceph auth list > /backup/ceph_auth_$(date +%Y%m%d).txt

# Резервное копирование мониторного store (на каждом MON)
tar czf /backup/mon_store_$(date +%Y%m%d).tar.gz /var/lib/ceph/mon/

# Полное резервное копирование конфигурации ceph-ansible
tar czf /backup/ceph_ansible_$(date +%Y%m%d).tar.gz \
  group_vars/ inventory.ini site.yml
```

> **Важно:** после обновления или миграции на `cephadm` скопируйте backup в безопасное место. Потеря keyring и mon_store требует полного восстановления кластера (см. [Операции Ceph](./Administration/operations.md)).

---

## Стратегия миграции на cephadm (Путь к 2026)

Для кластеров на `ceph-ansible` критически важно запланировать миграцию. Ниже описана полная процедура с prerequisite, пошаговыми действиями и rollback.

### Pre-migration checklist

| Проверка | Команда | Ожидаемый результат |
|----------|---------|---------------------|
| Версия Ceph | `ceph versions` | Pacific 16.2.x или выше |
| Кластер здоров | `ceph -s` | HEALTH_OK |
| NTP синхронизирован | `chronyc tracking` | Leap status: Normal |
| SSH доступен | `ssh root@<host> hostname` | Возвращает hostname |
| Podman/Docker установлен | `podman --version` или `docker --version` | Версия >= 3.0 (podman) / >= 20.10 (docker) |
| Нет забытых флагов | `ceph osd dump \| grep flags` | flags: none (или только plan maintenance) |
| MGR dashboard работает | `ceph mgr services` | dashboard: http://... |

### Процедура миграции

#### Шаг 1: Обновление ОС и установка Podman

```bash
# На каждом хосте кластера
apt-get update && apt-get upgrade -y  # или dnf update
apt-get install -y podman  # или dnf install podman

# Проверка
podman --version
```

#### Шаг 2: Обновление Ceph до Pacific (16.2.x)

```bash
# На Ansible Controller
cd ceph-ansible
git checkout stable-6.0  # → Pacific

# Обновление group_vars
vim group_vars/all.yml
# → ceph_stable_release: pacific

# Запуск обновления
ansible-playbook -i inventory.ini site.yml -u root -b --diff --limit osds
ansible-playbook -i inventory.ini site.yml -u root -b --diff --limit mons
ansible-playbook -i inventory.ini site.yml -u root -b --diff --limit mgrs

# Проверка
ceph versions
# → all: 16.2.x (pacific)
```

#### Шаг 3: Установка cephadm на всех хостах

```bash
# На каждом хосте
apt-get install -y cephadm  # или
# bash -c 'curl --silent --remote-name --location https://download.ceph.com/keys/release.asc'
# apt-key add release.asc
# echo "deb https://download.ceph.com/debian-pacific/ $(lsb_release -sc) main" > /etc/apt/sources.list.d/ceph.list
# apt-get update && apt-get install cephadm
```

#### Шаг 4: Adoption (миграция демонов)

```bash
# Миграция MON (по одному, начиная с не-лидеров)
cephadm shell -- cephadm adopt --style legacy --name mon.ceph-mon2
cephadm shell -- cephadm adopt --style legacy --name mon.ceph-mon3
cephadm shell -- cephadm adopt --style legacy --name mon.ceph-mon1  # ← лидер последним

# Миграция MGR
cephadm shell -- cephadm adopt --style legacy --name mgr.ceph-mon1

# Миграция OSD (по одному)
cephadm shell -- cephadm adopt --style legacy --name osd.0
cephadm shell -- cephadm adopt --style legacy --name osd.1
# ... повторить для всех OSD

# Проверка после каждого шага
ceph orch ps
ceph -s
```

#### Шаг 5: Очистка после миграции

```bash
# Удаление systemd-юнитов ceph-ansible (на каждом хосте)
systemctl disable ceph-mon@* ceph-osd@* ceph-mgr@*
rm /etc/systemd/system/ceph-*.service 2>/dev/null
systemctl daemon-reload

# Удаление ceph-ansible (на контроллере)
rm -rf /path/to/ceph-ansible

# Финальная проверка
ceph orch status  # → should show enabled
ceph orch ps      # → all daemons managed by cephadm
ceph -s           # → HEALTH_OK
```

#### Rollback (откат)

Если Adoption не удался на отдельном демоне:

```bash
# Остановка нового демона
cephadm shell -- cephadm rm-daemon --name <daemon-name>

# Перезапуск старого демона через systemd
systemctl start ceph-<daemon-type>@<daemon-id>

# Проверка
ceph -s
```

> **Важно:** Rollback возможен только до тех пор, пока НЕ выполнен `ceph daemon rm-daemon` для всех демонов одного типа. После удаления всех MON/MGR через cephadm откат на systemd невозможен без полного восстановления.

---

## Дополнительная информация

### Рекомендации для разных сценариев

| Сценарий | Инструмент | Версия Ceph | Примечание |
|----------|-----------|-------------|------------|
| Лаборатория/Dev | ceph-ansible | Quincy (17.x) | Быстрое развертывание, legacy |
| Production (новый) | **cephadm** | Squid (19.x)+ | Единственный поддерживаемый путь |
| Production (legacy) | ceph-ansible | Pacific-Quincy | Планируйте миграцию на cephadm |
| Миграция | cephadm adopt | Pacific (16.2.x) | Пошаговая процедура выше |

### См. также

- [Обзор Ceph](ceph_overview.md) — фундаментальные основы архитектуры.
- [Расчет Placement Groups](ceph_placement_groups.md) — математика PG и autoscaling.
- [Администрирование Ceph](./Administration/index.md) — навигация и архитектура.
- [Операции Ceph](./Administration/operations.md) — практические команды управления кластером.
- [Документация cephadm](https://docs.ceph.com/en/latest/cephadm/) — для новых систем.
- [Cephadm Adoption Guide](https://docs.ceph.com/en/latest/cephadm/adoption/) — инструкции по миграции.
