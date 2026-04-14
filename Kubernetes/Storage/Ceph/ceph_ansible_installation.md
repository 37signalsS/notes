# Установка кластера Ceph: ceph-ansible

## Определения

**`ceph-ansible`** — набор ролей Ansible для автоматизации развертывания Ceph. **Устарел**: поддержка прекращена после Ceph Octopus (15.x). Не рекомендуется для новых развертываний.

> **⚠️ Важно**: ceph-ansible используется только для поддержки легаси-кластеров. Для новых развертываний используйте [cephadm](https://docs.ceph.com/en/latest/cephadm/). Данный файл содержит историческую информацию.
>
> **⚠️ EOL**: Ceph Nautilus (14.x) — EOL с июля 2021. Luminous (12.x) — EOL с 2020. Octopus (15.x) — EOL с 2023. Актуальные версии: Reef (18.x), Squid (19.x). Обзор всех версий — в [ceph_overview.md](ceph_overview.md).

## Основные концепции

### Ключевые переменные конфигурации

`ceph-ansible` управляется через переменные в `group_vars/all.yml`, определяющие параметры кластера.

* **Сетевые настройки**:
  * `public_network`: Сеть для клиентских подключений к Ceph
  * `cluster_network`: Сеть для внутреннего трафика (репликация OSD, heartbeat'ы)
  * **Рекомендация**: для production использовать отдельную физическую сеть 10+ Гбит/с под `cluster_network`

* **Тип хранилища OSD (`osd_objectstore`)**:
  * `bluestore`: Современный, рекомендуемый тип. Напрямую управляет диском
  * `filestore`: Устаревший вариант через файловую систему (XFS)

* **Сценарий развертывания OSD (`osd_scenario`)**:
  * `lvm`: Рекомендуемый. Автоматически находит диски и создает LVM-тома
  * `collocated` / `non-collocated`: Устаревшие сценарии, заменены на `lvm`

* **Параметры кластера (`ceph_conf_overrides`)**:
  * `osd_pool_default_size`: Фактор репликации (минимум 3 для отказоустойчивости)
  * `osd_pool_default_min_size`: Минимум "живых" реплик для записи (обычно 2 при size=3)
  * `osd_pool_default_pg_num` / `osd_pool_default_pgp_num`: Количество PG для равномерного распределения данных. `pgp_num` всегда равен `pg_num`. Расчет см. в [ceph_placement_groups.md](ceph_placement_groups.md)

* **Синхронизация времени (`ntp_service`)**: Ceph чувствителен к расхождению времени (>0.05 сек вызывает проблемы с кворумом). Автоматически настраивается через NTPD или Chrony.

### Пример конфигурации group_vars/all.yml

```yaml
# Источник пакетов
ceph_origin: repository
ceph_repository: community
ceph_stable_release: octopus  # ⚠️ EOL с 2023. Только для легаси. Актуальные: reef (18.x), squid (19.x)

# Сетевые настройки
public_network: 172.21.0.0/24
cluster_network: 172.21.0.0/24  # Для production выделить отдельную сеть 10+ Гбит/с

# Синхронизация времени
ntp_service: chronyd  # chronyd предпочтительнее ntpd

# Тип хранилища и сценарий
osd_objectstore: bluestore
osd_scenario: lvm
# devices: ['/dev/sdb', '/dev/sdc']  # Опционально: явное указание дисков

# Параметры кластера
ceph_conf_overrides:
  global:
    osd_pool_default_pg_num: 32
    osd_pool_default_pgp_num: 32
    osd_journal_size: 1024  # MB, корректировать под размер дисков
    osd_pool_default_size: 3
    osd_pool_default_min_size: 2
```

### Соответствие веток ceph-ansible и версий Ceph

| Ветка ceph-ansible | Версия Ceph | Статус |
|---------------------|-------------|--------|
| `stable-3.2` | Nautilus (14.x) | ❌ EOL |
| `stable-4.0` | Nautilus (14.x) | ❌ EOL |
| `stable-5.0` | Octopus (15.x) | ❌ EOL |
| `stable-6.0` | Pacific (16.x) | ❌ EOL |

## Практические сценарии

### Развертывание кластера через ceph-ansible

#### 1. Подготовка Ansible Controller

```bash
# Клонирование репозитория
git clone https://github.com/ceph/ceph-ansible.git
cd ceph-ansible

# Переключение на стабильную ветку (пример для Octopus)
git checkout stable-5.0  # Octopus (15.x) — EOL. Для Nautilus: stable-4.0

# Установка зависимостей (Debian/Ubuntu)
sudo apt update && sudo apt install -y ansible python3-netaddr
pip install -r requirements.txt
```

#### 2. Настройка инвентаря (inventory.ini)

```ini
[mons]
ceph-node1 monitor_address=172.21.0.10
ceph-node2 monitor_address=172.21.0.11
ceph-node3 monitor_address=172.21.0.12

[osds]
ceph-node1
ceph-node2
ceph-node3

[managers]
ceph-node1
ceph-node2
ceph-node3

[mdss]
ceph-node1
ceph-node2
ceph-node3
```

> **Рекомендация**: для production минимум 3 узла с MON + MGR + OSD на каждом. Компоненты и их назначение — в [ceph_overview.md](ceph_overview.md).

#### 3. Запуск развертывания

```bash
# Подготовка playbook (если отсутствует)
cp site.yml.sample site.yml

# Запуск
ansible-playbook -i inventory.ini site.yml \
  -u <username> -b --ask-become-pass --diff
```

После завершения кластер готов к работе. Проверка состояния:

```bash
ceph -s
ceph osd status
ceph mon stat
```

## Дополнительная информация

Современный метод развертывания — [cephadm](https://docs.ceph.com/en/latest/cephadm/). Расчет PG — [ceph_placement_groups.md](ceph_placement_groups.md). Компоненты кластера — [ceph_overview.md](ceph_overview.md).
