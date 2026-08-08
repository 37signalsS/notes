# Установка и поддержка Ceph через ceph-ansible

## Определения

**`ceph-ansible`** — официальный в прошлом набор ролей Ansible для автоматизации развертывания и управления кластером Ceph.

> **Статус проекта (Август 2026)**: **Legacy (Устарел)**. Проект находится в режиме ограниченной поддержки для критических исправлений. Начиная с версии Ceph Pacific (16.x) и более новых (**Squid**, **Tentacle**, **Umbrella**), основным инструментом является **cephadm**. Использование `ceph-ansible` в 2026 году рекомендуется исключительно для обслуживания существующих (legacy) кластеров и подготовки их к миграции.

## Основные концепции

### Ключевые переменные конфигурации

Конфигурация `ceph-ansible` управляется через переменные в файлах директории `group_vars/`, в частности `all.yml` и `osds.yml`.

*   **Сетевые настройки**:
    *   `public_network`: Сеть для клиентского трафика и взаимодействия узлов MON.
    *   `cluster_network`: Изолированная сеть для внутреннего трафика (репликация OSD, восстановление данных, heartbeat). В 2026 году стандартом является использование 25/40+ Гбит/с для этой сети.
*   **Тип хранилища OSD (`osd_objectstore`)**:
    *   **BlueStore**: Современный и рекомендуемый тип. Работает напрямую с блочным устройством.
    *   **FileStore**: **Устарел**. Использовал файловую систему (XFS) и журнал. Не рекомендуется для новых или обновляемых систем.
*   **Сценарий развертывания OSD (`osd_scenario`)**:
    *   `lvm`: Рекомендуемый сценарий. Использует `ceph-volume` для создания LVM-томов.
*   **Параметры кластера (`ceph_conf_overrides`)**:
    *   `osd_pool_default_size`: Фактор репликации (стандарт — 3).
    *   `osd_pool_default_min_size`: Мин. реплик для записи (обычно 2).
    *   `osd_pool_default_pg_num`: Количество Placement Groups. См. [Расчет PG](ceph_placement_groups.md).

### Соответствие веток и версий Ceph

| Ветка ceph-ansible | Версия Ceph | Статус (Август 2026) |
| :--- | :--- | :--- |
| `stable-5.0` | Octopus (15.x) | **End of Life** |
| `stable-6.0` | Pacific (16.x) | **Maintenance Only** |
| `stable-7.0` | Quincy (17.x) | **Legacy Support** |
| `stable-8.0` | Reef (18.x) | **Limited Support** |
| `stable-9.0` | Squid/Tentacle | **Experimental/Not recommended** |

### Пример конфигурации group_vars/all.yml

```yaml
# Источник пакетов
ceph_origin: repository
ceph_repository: community
ceph_stable_release: quincy # Последняя стабильно поддерживаемая ветка для ansible

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
    osd_pool_default_pg_num: 128
    osd_pool_default_pgp_num: 128
    mon_clock_drift_allowed: .05
```

## Практические сценарии

### Развертывание кластера

#### 1. Подготовка Ansible Controller

Для работы со старыми ветками требуются специфические версии Ansible (2.9–2.11).

```bash
# Клонирование репозитория
git clone https://github.com/ceph/ceph-ansible.git
cd ceph-ansible

# Переключение на стабильную ветку
git checkout stable-7.0

# Установка зависимостей в изолированном окружении
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# → Установка ansible-core 2.11.x и зависимостей
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

[mgrs]
ceph-node1
ceph-node2
ceph-node3

[clients]
k8s-master-1
```

#### 3. Запуск развертывания

```bash
# Копирование образца плейбука
cp site.yml.sample site.yml

# Запуск установки
ansible-playbook -i inventory.ini site.yml \
  -u <user> -b --ask-become-pass --diff
```

### Обслуживание и проверка

#### Проверка состояния кластера

После завершения работы Ansible выполните диагностику:

```bash
# Общий статус
ceph -s
# → health: HEALTH_OK
#   services: mon: 3 daemons, mgr: 3 daemons, osd: 9 osds

# Проверка OSD
ceph osd tree
# → Просмотр иерархии узлов и дисков

# Проверка кворума мониторов
ceph mon stat
```

#### Добавление нового OSD

В `ceph-ansible` для добавления диска на существующий узел:
1. Отредактируйте `group_vars/osds.yml` (если диски указаны явно) или убедитесь, что новые диски подпадают под правила автообнаружения.
2. Запустите плейбук с ограничением по тегам:
```bash
ansible-playbook -i inventory.ini site.yml --limit osds --tags osds
```

## Администрирование и Troubleshooting

### Традиционное управление (Systemd)

В отличие от `cephadm`, демоны здесь работают как обычные юниты ОС.

| Задача | Команда |
| :--- | :--- |
| **Логи** | `tail -f /var/log/ceph/ceph-osd.0.log` |
| **Статус службы** | `systemctl status ceph-osd@0` |
| **Перезапуск MON** | `systemctl restart ceph-mon@$(hostname)` |

### Типичные проблемы legacy-установок

*   **Рассинхронизация времени**: Если `ntp_service` не настроен или `chronyd` завис, MON выпадут из кворума.
*   **Права на Keyrings**: Ansible может иногда некорректно выставить владельца на `/etc/ceph/ceph.client.admin.keyring`. Проверьте, чтобы у пользователя `ceph` был доступ.

## Стратегия миграции на cephadm (Путь к 2026)

Для кластеров на `ceph-ansible` критически важно запланировать миграцию:

1.  **Обновление ОС**: Убедитесь, что узлы поддерживают контейнеризацию (Podman/Docker).
2.  **Обновление Ceph**: Доведите кластер до версии Pacific (16.2.x) через Ansible.
3.  **Adoption**: Выполните процедуру переноса управления:
    ```bash
    cephadm shell -- cephadm adopt --style legacy --name mon.ceph-node1
    ```
4.  **Полный переход**: После миграции всех демонов удалите пакеты `ceph-ansible`.

## Дополнительная информация

*   [Обзор Ceph](ceph_overview.md) — фундаментальные основы.
*   [Расчет Placement Groups](ceph_placement_groups.md) — математика PG.
*   [Документация cephadm](https://docs.ceph.com/en/latest/cephadm/) — для новых систем.
*   [Cephadm Adoption Guide](https://docs.ceph.com/en/latest/cephadm/adoption/) — инструкции по миграции.
