# Установка кластера Ceph: ceph-ansible

## Определения

**`ceph-ansible`** — официальный набор ролей Ansible для автоматизации развертывания и управления кластером Ceph. 

> **Статус проекта**: **Устарел (Legacy)**. Активная поддержка и добавление новых функций прекращены после выхода версии Ceph Octopus (15.x). Начиная с версии Pacific (16.x) и более новых (Quincy, Reef, Squid, Tentacle), основным инструментом развертывания является **cephadm**. Использование `ceph-ansible` рекомендуется исключительно для поддержки и обслуживания существующих (legacy) кластеров.

## Основные концепции

### Ключевые переменные конфигурации

Конфигурация `ceph-ansible` управляется через переменные в файлах директории `group_vars/`, в частности `all.yml` и `osds.yml`.

*   **Сетевые настройки**:
    *   `public_network`: Сеть для клиентского трафика и взаимодействия узлов MON.
    *   `cluster_network`: Изолированная сеть для внутреннего трафика (репликация OSD, восстановление данных, heartbeat).
    *   **Рекомендация**: Для production-сред использование отдельной физической сети с пропускной способностью 10+ Гбит/с для `cluster_network` является обязательным для предотвращения деградации производительности клиентов во время восстановления данных (backfill/recovery).

*   **Тип хранилища OSD (`osd_objectstore`)**:
    *   **BlueStore**: Современный (с версии Luminous) и рекомендуемый тип. Напрямую управляет блочным устройством без промежуточной файловой системы, что повышает производительность и исключает накладные расходы на POSIX-слой.
    *   **FileStore**: Устаревший вариант, использующий файловую систему (XFS) и отдельный журнал (Journal). Требует сложной настройки параметров монтирования и параметров XFS для достижения приемлемой производительности.

*   **Сценарий развертывания OSD (`osd_scenario`)**:
    *   `lvm`: Рекомендуемый сценарий. Использует `ceph-volume` для создания LVM-томов, что упрощает управление дисками.
    *   `collocated` / `non-collocated`: Устаревшие методы (заменены на `lvm`), где данные и журнал OSD располагались на одном или разных физических устройствах соответственно.

*   **Требования к операционной системе**:
    *   `ceph-ansible` наиболее стабильно работает на Ubuntu 18.04/20.04 и CentOS 7/8 (Stream).
    *   **Внимание**: CentOS 7/8 достигли EOL, что может вызвать проблемы с доступностью пакетов в стандартных репозиториях.

*   **Параметры кластера (`ceph_conf_overrides`)**:
    *   `osd_pool_default_size`: Фактор репликации (стандарт — 3 для обеспечения отказоустойчивости при выходе из строя двух узлов).
    *   `osd_pool_default_min_size`: Минимальное количество "живых" реплик для подтверждения записи (обычно 2 при `size=3`).
    *   `osd_pool_default_pg_num` / `osd_pool_default_pgp_num`: Количество Placement Groups. Важно: `pgp_num` должен всегда быть равен `pg_num`. Подробности расчета приведены в [ceph_placement_groups.md](ceph_placement_groups.md).

*   **Синхронизация времени (`ntp_service`)**:
    *   Ceph крайне чувствителен к рассинхронизации часов между узлами. Отклонение более 0.05 сек может привести к потере кворума мониторами (MON) и переходу кластера в состояние `HEALTH_WARN`. Рекомендуется использовать `chronyd`.

### Соответствие веток и версий Ceph

| Ветка ceph-ansible | Версия Ceph | Статус |
| :--- | :--- | :--- |
| `stable-3.2` | Nautilus (14.x) | EOL |
| `stable-4.0` | Nautilus (14.x) | EOL |
| `stable-5.0` | Octopus (15.x) | EOL |
| `stable-6.0` | Pacific (16.x) | Ограниченная поддержка |

### Пример конфигурации group_vars/all.yml

```yaml
# Источник пакетов
ceph_origin: repository
ceph_repository: community
ceph_stable_release: octopus

# Сетевые настройки
public_network: 172.21.0.0/24
cluster_network: 172.21.1.0/24

# Синхронизация времени
ntp_service: chronyd

# Тип хранилища и сценарий
osd_objectstore: bluestore
osd_scenario: lvm

# Параметры кластера
ceph_conf_overrides:
  global:
    osd_pool_default_size: 3
    osd_pool_default_min_size: 2
    osd_pool_default_pg_num: 32
    osd_pool_default_pgp_num: 32
    osd_journal_size: 1024  # Размер журнала в МБ (актуально для FileStore)
```

## Практические сценарии

### Развертывание кластера

#### 1. Подготовка Ansible Controller

```bash
# Клонирование репозитория
git clone https://github.com/ceph/ceph-ansible.git
# → Cloning into 'ceph-ansible'...

cd ceph-ansible

# Переключение на ветку для Octopus
git checkout stable-5.0
# → Switched to a new branch 'stable-5.0'

# Установка зависимостей (рекомендуется использовать venv для изоляции старых версий Ansible)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# → Successfully installed ansible-2.9.27 ...
```

#### 2. Настройка инвентаря (inventory.ini)

Для обеспечения высокой доступности (HA) в production-среде необходимо минимум 3 узла.

```ini
[mons]
ceph-node1 monitor_address=172.21.0.10
ceph-node2 monitor_address=172.21.0.11
ceph-node3 monitor_address=172.21.0.12

[osds]
ceph-node1
ceph-node2
ceph-node3

[mgrs]
ceph-node1
ceph-node2
ceph-node3
```

#### 3. Запуск развертывания

```bash
# Подготовка основного файла playbook
cp site.yml.sample site.yml

# Запуск установки
ansible-playbook -i inventory.ini site.yml \
  -u <user> -b --ask-become-pass --diff
# → PLAY RECAP *********************************************************************
#   ceph-node1 : ok=350 changed=50 unreachable=0 failed=0
#   ...
```

### Проверка состояния кластера

После завершения работы Ansible необходимо убедиться в корректности развертывания:

```bash
# Общий статус кластера
ceph -s
# → health: HEALTH_OK
#   services: mon: 3 daemons, mgr: 3 daemons, osd: 9 osds

# Состояние OSD в иерархии
ceph osd status
# → ID  HOST        USED  AVAIL  WR OPS  WR DATA  RD OPS  RD DATA  STATE
#   0   node1       10G   190G      0        0       0        0   exists,up

# Проверка кворума мониторов
ceph mon stat
# → e3: 3 mons at {node1=...,node2=...,node3=...}, quorum node1,node2,node3
```

## Дополнительная информация

*   [Обзор Ceph](ceph_overview.md) — фундаментальные компоненты и архитектура RADOS.
*   [Расчет Placement Groups](ceph_placement_groups.md) — подробная математика распределения данных.
*   [Документация cephadm](https://docs.ceph.com/en/latest/cephadm/) — актуальный метод установки для современных версий Ceph.
