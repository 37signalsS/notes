# Ansible: Модули управления хранилищем и дисками

## Определения

**Модули управления хранилищем** — это группа специализированных декларативных инструментов Ansible (из `ansible.builtin` и `community.general`), предназначенных для автоматизации разметки дисков, создания логических томов, управления RAID-массивами и файловыми системами на управляемых хостах.

**LVM (Logical Volume Manager)** — уровень абстракции над физическими дисками, позволяющий создавать гибкие логические тома (LV) внутри групп томов (VG) на основе физических томов (PV). Ansible управляет LVM через модули `community.general.lvg`, `community.general.lvol`.

**RAID (Redundant Array of Independent Disks)** — технология объединения нескольких дисков для повышения надежности или производительности. Ansible управляет RAID через `community.general.mdadm`.

**ZFS / Btrfs** — современные файловые системы с встроенными возможностями управления пулами, снапшотами и проверкой целостности данных. Ansible управляет ими через `community.general.zfs` и `community.general.btrfs`.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля (например, `community.general.lvol`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен и обеспечения предсказуемости выполнения.

**LUKS (Linux Unified Key Setup)** — стандарт шифрования блочных устройств в Linux. Ansible управляет LUKS через модуль `community.crypto.luks_device` (или через `command`/`shell` для `cryptsetup`). Шифрование применяется к блочному устройству до создания PV/LV или поверх LV.

**Thin provisioning (тонкое выделение)** — режим LVM, при котором логические тома выделяют пространство из общего пула по мере необходимости. Ansible управляет thin pool через `community.general.lvol` с параметром `thin: true`.

**Snapshot** — моментальный снимок состояния тома или файловой системы. В LVM snapshots создаются как специальные LV; в Btrfs/ZFS — как нативные subvolumes/datasets.

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **ansible-core** | 2.18+ | 2.21.3 |
| **community.general** | 6.0+ | 13.3.0 |
| **Python** (target) | 3.9+ | 3.12+ |
| **lvm2** (целевые хосты) | 2.03+ | 2.03.42 |
| **mdadm** (целевые хосты) | 4.0+ | 4.6 |
| **sudo** (целевые хосты) | 1.8+ | Актуальная LTS |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.3]

ansible all -m ping
# → pong: web01
# → pong: db01
```

## Основные концепции

### Иерархия управления хранилищем

```
Физический диск (/dev/sda, /dev/nvme0n1)
    ↓
Разметка (parted) → Партиция (/dev/sda1)
    ↓
Физический том (PV) → Группа томов (VG) → Логический том (LV)
    ↓
Файловая система (XFS, ext4, Btrfs, ZFS)
    ↓
Точка монтирования (/var/lib/data)
```

### Модули управления хранилищем

1.  **`community.general.parted`**: Управление таблицей разделов диска (GPT, MBR). Создание, удаление, изменение размера разделов. Поддерживает `label` (gpt/msdos), `unit`, `align`, `flags` (boot, esp, raid, lvm).
2.  **`ansible.builtin.filesystem`**: Создание файловых систем на устройствах. Поддерживает `fstype` (xfs, ext4, btrfs, zfs, vfat), `dev`, `force` (для пересоздания), `resizefs` (онлайн-ресайз).
3.  **`community.general.lvg`**: Управление группами томов LVM. Создание, расширение, удаление VG. Поддерживает `vg`, `pv`, `pesize`, `force`. В `community.general` 13.x мигрирован на `CmdRunner`, что улучшило обработку ошибок LVM2.
4.  **`community.general.lvol`**: Управление логическими томами LVM. Создание, расширение, удаление LV. Поддерживает `vg`, `lv`, `size`, `shrink` (с осторожностью), `thin` pool.
5.  **`community.general.mdadm`**: Управление RAID-массивами. Создание, удаление, мониторинг RAID 0/1/5/6/10. Поддерживает `devices`, `level`, `state` (present/absent), `force`.
6.  **`community.general.zfs`**: Управление пулами ZFS, snapshot, dataset. Поддерживает `zpool`, `state`, `force`, `delegate`.
7.  **`community.general.btrfs`**: Управление пулами Btrfs, subvolumes, snapshot. Поддерживает `device`, `mount`, `subvolume`, `state`.
8.  **`community.crypto.luks_device`**: Управление LUKS-контейнерами (инициализация, открытие, закрытие). Требует `community.crypto` >= 2.0. Все операции с паролями требуют `no_log: true`.
9.  **`ansible.builtin.mount`**: Монтирование файловых систем и управление `/etc/fstab`. Поддерживает `state` (mounted/unmounted/present/absent), `opts`, `fstab` запись.

### Привилегированный доступ (become)

Все операции с хранилищем требуют root-доступа. Используйте `become: yes`.

```yaml
- name: "Создание LVM-тома"
  community.general.lvol:
    vg: vg_data
    lv: lv_pg_data
    size: +200G
  become: yes
```

### Идемпотентность и состояние

Модули управления хранилищем следуют принципу идемпотентности:
- **Создание**: `state: present` — том/раздел будет создан только если отсутствует.
- **Удаление**: `state: absent` — том/раздел будет удален только если существует.
- **Изменение размера**: Параметр `size` с префиксом `+` или `-` позволяет расширять/сжимать том идемпотентно.

### Идемпотентность и режимы диагностики

| Модуль | check_mode | diff_mode | Идемпотентность |
| :--- | :--- | :--- | :--- |
| `community.general.parted` | full | full | Да |
| `ansible.builtin.filesystem` | full | full | Да (при `resizefs: yes` показывает изменение размера) |
| `community.general.lvg` | full | full | Да |
| `community.general.lvol` | full | full | Да (расширение LV показывает changed, shrink требует осторожности) |
| `community.general.mdadm` | full | partial | Да |
| `community.general.zfs` | full | full | Да |
| `community.general.btrfs` | full | full | Да |

### Модель выполнения: контроллер vs управляемый хост

Все модули управления хранилищем выполняют операции **на управляемом хосте**:
- Утилиты `parted`, `lvm`, `mdadm`, `mkfs`, `cryptsetup` должны быть установлены на целевом хосте.
- Операции создания разделов, форматирования, монтирования — локальны для каждого хоста.
- При работе с внешними RAID-контроллерами или shared storage убедитесь, что устройство видно на целевом хосте (например, через multipath).

### Безопасность хранения

| Риск | Мера | Модуль/инструмент |
| :--- | :--- | :--- |
| Физический доступ к диску | Шифрование LUKS | `community.crypto.luks_device`, `cryptsetup` |
| Неавторизованный mount | `noauto` в fstab, `x-systemd.automount` | `ansible.builtin.mount` |
| Утечка метаданных LVM | Отключение автоматической активации VG | `vgchange --setautoactivation ignore` |

## Практические сценарии

### Сценарий 1: Полная подготовка диска и создание LVM

Создание партиции, PV, VG, LV и файловой системы XFS.

```yaml
- name: "Создание партиции /dev/sdb1"
  community.general.parted:
    device: /dev/sdb
    number: 1
    state: present
    label: gpt
    part_type: primary
    fs_type: xfs
    size: "100%"

- name: "Создание PV на /dev/sdb1"
  community.general.lvg:
    vg: vg_data
    pv: /dev/sdb1
    force: yes

- name: "Создание VG vg_data"
  community.general.lvg:
    vg: vg_data
    pv: /dev/sdb1
    pesize: 4M

- name: "Создание LV lv_pg_data 200G"
  community.general.lvol:
    vg: vg_data
    lv: lv_pg_data
    size: 200G

- name: "Создание XFS на /dev/vg_data/lv_pg_data"
  ansible.builtin.filesystem:
    fstype: xfs
    dev: /dev/vg_data/lv_pg_data
    force: no

- name: "Монтирование /var/lib/pgdata"
  ansible.builtin.mount:
    path: /var/lib/pgdata
    src: /dev/vg_data/lv_pg_data
    fstype: xfs
    state: mounted
    opts: defaults,noatime
```

### Сценарий 2: Расширение LVM-тома и файловой системы

Онлайн-расширение логического тома и файловой системы XFS.

```yaml
- name: "Расширение LV на +100G"
  community.general.lvol:
    vg: vg_data
    lv: lv_pg_data
    size: +100G
  register: lv_expand

- name: "Расширение XFS"
  ansible.builtin.filesystem:
    fstype: xfs
    dev: /dev/vg_data/lv_pg_data
    resizefs: yes
  when: lv_expand.changed
```

### Сценарий 3: Создание RAID-массива mdadm

Создание RAID 10 на 4 дисках для базы данных.

```yaml
- name: "Создание RAID 10"
  community.general.mdadm:
    name: /dev/md0
    devices: "{{ raid_devices }}"
    level: raid10
    state: present
    force: yes
  vars:
    raid_devices:
      - /dev/sdc
      - /dev/sdd
      - /dev/sde
      - /dev/sdf

- name: "Создание XFS на /dev/md0"
  ansible.builtin.filesystem:
    fstype: xfs
    dev: /dev/md0

- name: "Монтирование /data"
  ansible.builtin.mount:
    path: /data
    src: /dev/md0
    fstype: xfs
    state: mounted
```

### Сценарий 4: Управление ZFS пулом и snapshot

Создание ZFS пула и snapshot для бэкапа.

```yaml
- name: "Создание ZFS пула"
  community.general.zfs:
    name: tank/data
    state: present
    extra_zfs_properties:
      compression: lz4
      atime: off

- name: "Создание snapshot"
  community.general.zfs:
    name: tank/data@backup-2026-09-24
    state: present

- name: "Удаление старого snapshot"
  community.general.zfs:
    name: tank/data@backup-2026-09-23
    state: absent
```

### Сценарий 5: Управление Btrfs subvolume

Создание subvolume и snapshot.

```yaml
- name: "Создание Btrfs subvolume"
  community.general.btrfs:
    device: /dev/sdb1
    mount: /mnt/btrfs
    subvolume: home
    state: present

- name: "Создание snapshot subvolume"
  community.general.btrfs:
    device: /dev/sdb1
    mount: /mnt/btrfs
    subvolume: home
    snapshot: home-snapshot-2026-09-24
    state: present
```

### Сценарий 6: Шифрование LV через LUKS

Создание зашифрованного логического тома с автоматическим открытием при загрузке ( crypttab + systemd ).

> **Важно:** `community.crypto.luks_device` требует `community.crypto` >= 2.0. В среде без коллекции используйте `ansible.builtin.command` с `cryptsetup`.

```yaml
- name: "Создание зашифрованного LV"
  hosts: db_servers
  become: true
  vars:
    luks_name: luks_pgdata
    luks_device: /dev/vg_data/lv_pgdata
    mount_point: /var/lib/pgdata
    luks_pass: "{{ vault_luks_pass }}"
  tasks:
    - name: "Создание LV для шифрования"
      community.general.lvol:
        vg: vg_data
        lv: lv_pgdata
        size: 200G

    - name: "Инициализация LUKS"
      community.crypto.luks_device:
        device: "{{ luks_device }}"
        password: "{{ luks_pass }}"
        state: present
      no_log: true

    - name: "Открытие LUKS-контейнера"
      community.crypto.luks_device:
        device: "{{ luks_device }}"
        password: "{{ luks_pass }}"
        name: "{{ luks_name }}"
        state: opened
      no_log: true

    - name: "Создание XFS на открытом маппере"
      ansible.builtin.filesystem:
        fstype: xfs
        dev: "/dev/mapper/{{ luks_name }}"
        force: no

    - name: "Добавление в /etc/crypttab"
      ansible.builtin.lineinfile:
        path: /etc/crypttab
        regexp: "^{{ luks_name }}"
        line: "{{ luks_name }} {{ luks_device }} {{ luks_pass }} luks"
      no_log: true

    - name: "Монтирование зашифрованного тома"
      ansible.builtin.mount:
        path: "{{ mount_point }}"
        src: "/dev/mapper/{{ luks_name }}"
        fstype: xfs
        state: mounted
        opts: defaults,noatime
```

**SRE-рекомендации:**
- Храните `luks_pass` в `ansible-vault`, не в plain inventory.
- Для production используйте ключевой файл (TKEY) вместо пароля, храня его на токене (smartcard/YubiKey).
- Резервное копирование заголовка LUKS (`cryptsetup luksHeaderBackup`) — отдельная задача в Disaster Recovery плейбуке.

### Сценарий 7: Thin provisioning pool и мониторинг переполнения

Создание thin pool и LV с отслеживанием использования.

```yaml
- name: "Создание thin pool"
  community.general.lvol:
    vg: vg_data
    lv: thin_pool
    size: 500G
    thin: true
    poolmetadatasize: 4G

- name: "Создание thin LV из пула"
  community.general.lvol:
    vg: vg_data
    lv: thin_lv_app
    thin: true
    pool: thin_pool
    size: 100G
    state: present

- name: "Проверка использования thin pool"
  ansible.builtin.command: lvs --noheadings --units g -o lv_name,data_percent,metadata_percent vg_data/thin_pool
  register: thin_usage
  changed_when: false
  failed_when: thin_usage.rc != 0
```

**SRE-рекомендации:**
- Thin pool исчерпается раньше за счёт `data_percent` > 100% (overprovisioning). Мониторьте `data_percent` и алертите при > 80%.
- `poolmetadatasize` должен быть не менее 1% от размера пула, но не менее 4G. При большом количестве LV увеличьте до 8-16G.
- Избегайте `force: yes` при расширении thin pool — это может привести к невосстановимой потере данных при переполнении.

### Сценарий 8: Дисковый I/O мониторинг и алертинг (SRE)

Сбор метрик дискового пространства и I/O через `ansible.builtin.stat` и `ansible.builtin.shell` для интеграции с Prometheus.

```yaml
- name: "Сбор метрик дискового пространства"
  ansible.builtin.stat:
    path: "{{ item.mount }}"
    get_attributes: no
  loop: "{{ filesystems }}"
  register: fs_stats

- name: "Расчёт процента использования"
  ansible.builtin.set_fact:
    fs_usage: >-
      {{
        fs_usage | default([]) + [
          {
            'mount': item.item.mount,
            'total_gb': (item.stat.size / 1024 / 1024 / 1024) | round(1),
            'used_percent': ((item.stat.size - item.stat.blocks_available * 1024) / item.stat.size * 100) | round(1)
          }
        ]
      }}
  loop: "{{ fs_stats.results }}"

- name: "Сбор метрик I/O"
  ansible.builtin.command: iostat -dx 1 2 | tail -n +4
  register: iostat
  changed_when: false
  failed_when: false

- name: "Отчёт по дискам"
  ansible.builtin.debug:
    msg: |
      Mount: {{ item.mount }}, Usage: {{ item.used_percent }}%
  loop: "{{ fs_usage }}"
  when: item.used_percent > warning_threshold | default(80)
```

Создание зашифрованного логического тома с автоматическим открытием при загрузке ( crypttab + systemd ).

> **Важно:** `community.crypto.luks_device` требует `community.crypto` >= 2.0. В среде без коллекции используйте `ansible.builtin.command` с `cryptsetup`.

```yaml
- name: "Создание зашифрованного LV"
  hosts: db_servers
  become: true
  vars:
    luks_name: luks_pgdata
    luks_device: /dev/vg_data/lv_pgdata
    mount_point: /var/lib/pgdata
    luks_pass: "{{ vault_luks_pass }}"
  tasks:
    - name: "Создание LV для шифрования"
      community.general.lvol:
        vg: vg_data
        lv: lv_pgdata
        size: 200G

    - name: "Инициализация LUKS"
      community.crypto.luks_device:
        device: "{{ luks_device }}"
        password: "{{ luks_pass }}"
        state: present
      no_log: true

    - name: "Открытие LUKS-контейнера"
      community.crypto.luks_device:
        device: "{{ luks_device }}"
        password: "{{ luks_pass }}"
        name: "{{ luks_name }}"
        state: opened
      no_log: true

    - name: "Создание XFS на открытом маппере"
      ansible.builtin.filesystem:
        fstype: xfs
        dev: "/dev/mapper/{{ luks_name }}"
        force: no

    - name: "Добавление в /etc/crypttab"
      ansible.builtin.lineinfile:
        path: /etc/crypttab
        regexp: "^{{ luks_name }}"
        line: "{{ luks_name }} {{ luks_device }} {{ luks_pass }} luks"
      no_log: true

    - name: "Монтирование зашифрованного тома"
      ansible.builtin.mount:
        path: "{{ mount_point }}"
        src: "/dev/mapper/{{ luks_name }}"
        fstype: xfs
        state: mounted
        opts: defaults,noatime
```

**SRE-рекомендации:**
- Храните `luks_pass` в `ansible-vault`, не в plain inventory.
- Для production используйте ключевой файл (TKEY) вместо пароля, храня его на токене (smartcard/YubiKey).
- Резервное копирование заголовка LUKS (`cryptsetup luksHeaderBackup`) — отдельная задача в Disaster Recovery плейбуке.

### Сценарий 9: Настройка квот дискового пространства (XFS/ ext4)

Включение пользовательских и групповых квот на XFS через `usrquota`/`grpquota` и `setquota`.

```yaml
- name: "Настройка квот XFS"
  hosts: storage_servers
  become: true
  vars:
    quota_mountpoint: "/mnt/data"
    quota_users:
      - name: appuser
        hard: "10G"
        soft: "8G"
      - name: dbuser
        hard: "50G"
        soft: "40G"
    quota_groups:
      - name: developers
        hard: "100G"
        soft: "80G"
  tasks:
    - name: "Установка утилит квот и xfsprogs"
      ansible.builtin.package:
        name:
          - quota
          - xfsprogs
        state: present

    - name: "Добавление квот в параметры монтирования"
      ansible.builtin.mount:
        path: "{{ quota_mountpoint }}"
        src: "/dev/sdb1"
        fstype: xfs
        state: present
        opts: "defaults,noatime,usrquota,grpquota"
      register: fstab_quota

    - name: "Перемонтирование с квотами"
      ansible.builtin.command: mount -o remount,usrquota,grpquota {{ quota_mountpoint }}
      when: fstab_quota.changed

    - name: "Инициализация квот"
      ansible.builtin.command: quotacheck -ugm {{ quota_mountpoint }}
      register: quotacheck
      changed_when: "'Checked' in quotacheck.stdout"

    - name: "Включение квот"
      ansible.builtin.command: quotaon -ug {{ quota_mountpoint }}
      register: quotaon
      changed_when: "'turned on' in quotaon.stdout"

    - name: "Установка квот для пользователей"
      ansible.builtin.command: >
        setquota -u {{ item.name }} {{ item.soft | regex_replace('[G|M|K]', '') }} {{ item.hard | regex_replace('[G|M|K]', '') }} 0 0 {{ quota_mountpoint }}
      loop: "{{ quota_users }}"
      register: user_quota
      changed_when: user_quota.rc == 0

    - name: "Установка квот для групп"
      ansible.builtin.command: >
        setquota -g {{ item.name }} {{ item.soft | regex_replace('[G|M|K]', '') }} {{ item.hard | regex_replace('[G|M|K]', '') }} 0 0 {{ quota_mountpoint }}
      loop: "{{ quota_groups }}"
      register: group_quota
      changed_when: group_quota.rc == 0

    - name: "Проверка квот"
      ansible.builtin.command: repquota -ug {{ quota_mountpoint }}
      register: repquota
      changed_when: false
```

**SRE-рекомендации:**
- Используйте `quotaon` с `-v` для диагностики; `quotacheck` может занимать минуты на больших ФС — планируйте maintenance window.
- Для XFS `usrquota`/`grpquota` поддерживаются начиная с 4.5; более старые ядра требуют `prjquota` для проектов.
- Project quotas (XFS) позволяют ограничивать каталоги, а не только uid/gid — используйте для контейнерных workloads.

## Операции и команды

### Управление партициями (parted)

| Операция | Команда |
| :--- | :--- |
| Создание GPT | `parted /dev/sda mklabel gpt` |
| Создание партиции | `parted /dev/sda mkpart primary xfs 1GiB 100%` |
| Установка флага boot | `parted /dev/sda set 1 boot on` |
| Установка флага esp | `parted /dev/sda set 1 esp on` |
| Установка флага raid | `parted /dev/sda set 1 raid on` |
| Установка флага lvm | `parted /dev/sda set 1 lvm on` |
| Удаление партиции | `parted /dev/sda rm 1` |

### Управление LVM

| Операция | Команда |
| :--- | :--- |
| Создание PV | `pvcreate /dev/sdb1` |
| Создание VG | `vgcreate vg_data /dev/sdb1` |
| Создание LV | `lvcreate -L 200G -n lv_pg_data vg_data` |
| Создание thin pool | `lvcreate -L 500G -n thin_pool --type thin-pool vg_data` |
| Создание thin LV | `lvcreate -V 100G -n thin_lv_app --thin vg_data/thin_pool` |
| Расширение LV | `lvextend -L +100G /dev/vg_data/lv_pg_data` |
| Удаление LV | `lvremove /dev/vg_data/lv_pg_data` |
| Резервное копирование метаданных VG | `vgcfgbackup /etc/lvm/backup` |

### Управление RAID

| Операция | Команда |
| :--- | :--- |
| Создание RAID 10 | `mdadm --create /dev/md0 --level=10 --raid-devices=4 /dev/sd{c,d,e,f}` |
| Проверка статуса | `cat /proc/mdstat` |
| Сохранение конфига | `mdadm --detail --scan >> /etc/mdadm.conf` |
| Добавление hot spare | `mdadm --add /dev/md0 /dev/sdx` |
| Замена отказавшего диска | `mdadm --replace /dev/sda1 --with /dev/sdx1 /dev/md0` |

### Управление LUKS

| Операция | Команда |
| :--- | :--- |
| Инициализация LUKS | `cryptsetup luksFormat /dev/vg_data/lv_pgdata` |
| Открытие контейнера | `cryptsetup open /dev/vg_data/lv_pgdata luks_pgdata` |
| Закрытие контейнера | `cryptsetup close luks_pgdata` |
| Резерв заголовка | `cryptsetup luksHeaderBackup /dev/vg_data/lv_pgdata --header-backup-file /root/luks_header.backup` |
| Проверка статуса | `cryptsetup status luks_pgdata` |

## Устранение неполадок

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Device or resource busy` | Том смонтирован или используется | Размонтируйте том: `umount /var/lib/pgdata` |
| `Volume group "vg_data" not found` | VG не существует или не активирована | Проверьте `vgdisplay`, активируйте: `vgchange -a y vg_data` |
| `Logical volume not found` | LV не существует или не активирована | Проверьте `lvdisplay`, активируйте: `lvchange -a y /dev/vg_data/lv_pg_data` |
| `Filesystem is already mounted` | ФС смонтирована в другом месте | Проверьте `mount | grep xfs`, размонтируйте |
| `RAID array is degraded` | Отказал диск в RAID-массиве | Проверьте `cat /proc/mdstat`, замените диск |
| `No space left on device` | LV или VG исчерпан | Расширьте LV или VG: `lvextend`, `vgextend` |
| `thin pool data percent > 100` | Переполнение thin pool | Остановите запись, расширьте pool или удалите старые снапшоты |
| `LUKS device not found` | Контейнер закрыт или заголовок поврежден | Проверьте `cryptsetup status`, восстановите заголовок из бэкапа |
| `cryptsetup: device is busy` | Маппер используется смонтированной ФС | Размонтируйте, закройте контейнер: `cryptsetup close` |
| `Incorrect passphrase` | Неверный пароль LUKS | Используйте `--try-passphrase` для диагностики, восстановите из заголовка |

### Диагностические команды

```bash
# Проверка физических томов
pvdisplay
# → PV /dev/sdb1   VG vg_data   PV Size 100.00 GB

# Проверка групп томов
vgdisplay vg_data
# → VG Name: vg_data
# → VG Size: 100.00 GB

# Проверка логических томов
lvdisplay /dev/vg_data/lv_pg_data
# → LV Path: /dev/vg_data/lv_pg_data
# → LV Size: 200.00 GB

# Проверка thin pool
lvs --noheadings --units g -o lv_name,data_percent,metadata_percent vg_data/thin_pool
# → thin_pool  45.2  1.1

# Проверка RAID
cat /proc/mdstat
# → md0: active raid1 sda1[0] sdb1[1]

# Проверка LUKS
cryptsetup status luks_pgdata
# → type: LUKS1
# → cipher: aes-xts-plain64
# → keysize: 512 bits

# Проверка ZFS
zpool list
# → NAME    SIZE  ALLOC  FREE
# → tank    1.9T  500G  1.4T

zfs list
# → NAME      USED  AVAIL  REFER  MOUNTPOINT
# → tank/data  500G  1.4T   500G  /tank/data
```

## Рекомендации и оптимизация

### Выбор файловой системы

| Файловая система | Когда использовать | Особенности |
| :--- | :--- | :--- |
| **XFS** | БД, медиа, большие файлы | Высокая производительность при параллельном I/O, не поддерживает уменьшение |
| **ext4** | Универсальная, legacy | Надежность, поддержка уменьшения, максимальная совместимость |
| **Btrfs** | Snapshot-стратегии, контейнеры | Встроенные snapshot, checksums, compression. Зрелость в продакшене растет |
| **ZFS** | Критичные данные, бэкапы | End-to-end checksumming, snapshot, replication. Высокое потребление RAM |

### Оптимизация LVM

- **Размер PE (Physical Extend)**: Используйте 4M для стандартных сценариев, 8M-16M для больших томов (>1TB).
- **Thin provisioning**: Используйте `thin` pool для гибкого управления пространством, но контролируйте `data_percent` и `metadata_percent`.
- **Stripes**: Для RAID 0/5/6 создавайте LV с `-i 2` (stripes) для повышения производительности.
- **Метаданные VG**: Резервное копирование метаданных (`vgcfgbackup`) — обязательная задача в плейбуке настройки storage.

### Оптимизация RAID

- **RAID 10**: Предпочтителен для баз данных (баланс производительности и отказоустойчивости).
- **RAID 5/6**: Требуют длительного rebuild, подходит для архивов.
- **RAID 1**: Для критичных системных разделов.
- **Hot spare**: Добавляйте запасные диски (`mdadm --add /dev/md0 /dev/sdx`) для автоматической замены отказавшего.

### Безопасность

- **Шифрование**: Используйте `dm-crypt` (LUKS) для шифрования томов. Создавайте LV поверх зашифрованного контейнера.
- **Permissions**: Устанавливайте `mode: '0600'` на точках монтирования с чувствительными данными.
- **SELinux**: После создания ФС на новых разделах проверяйте контексты: `restorecon -R /var/lib/pgdata`.
- **LUKS заголовок**: Резервное копирование заголовка (`cryptsetup luksHeaderBackup`) отдельно от данных — без заголовка данные не восстановить.

### Мониторинг

- **Дисковое пространство**: Используйте `node_exporter` textfile collector или `ansible.builtin.stat` для отслеживания.
- **SMART**: Настраивайте `smartd` для алертов при отказе дисков.
- **RAID**: Мониторьте `/proc/mdstat` и `mdadm --monitor` для уведомлений о деградации массива.
- **LVM thin pool**: Мониторьте `data_percent` и `metadata_percent`; алертите при > 80%.
- **I/O latency**: `iostat -dx 1` или `node_exporter` metrics `node_disk_io_time_weighted_seconds_total` для SLO.

### Производительность и масштабирование

- **Очереди I/O**: Для NVMe используйте `nr_requests=1024` и `nomerges=0` в udev rules; для HDD — `scheduler=mq-deadline`.
- **Флаги монтирования**: `noatime` или `relatime` для снижения записи; `discard` для SSD (или `fstrim.timer`).
- **XFS inode64**: Для файловых систем > 1TB используйте `mkfs.xfs -i inode64`, иначе ограничение 2^31 inodes.
- **Асинхронность**: При массовой настройке storage (>50 хостов) используйте `async` + `poll` для долгих операций `mkfs` и `cryptsetup`.
- **delegate_to**: Для shared storage (SAN/NAS) централизуйте форматирование через `delegate_to` на storage-шлюзе, чтобы избежать конфликтов.

### Эксплуатация

- **Ротация по порогу, а не по дате**: для снапшотов (Btrfs/ZFS/LVM) используйте возраст и размер, а не только календарь.
- **Бэкап метаданных**: `vgcfgbackup`, `mdadm --detail --scan`, `cryptsetup luksHeaderBackup` — включите в disaster recovery playbook.
- **Тестирование восстановления**: раз в квартал восстанавливайте VG/LV metadata на изолированном стенде.
- **Документация**: храните схему storage (VG→LV→mountpoint→owner) в wiki/ITSM; Ansible playbook — не замена документации, а её исполнение.

## Дополнительная информация

- **[Автоматизация LVM через Ansible](../../Linux/FileSystems/LVM/operations/lvm_ansible_automation.md)** — роли, инвентарь и проверки для LVM (расширенный пример).
- **[Управление файловыми системами и хранилищем через Ansible](../examples/ansible_filesystem_storage_management.md)** — квоты, Btrfs таймеры, сценарии parted.
- **[Официальная документация `community.general`](https://docs.ansible.com/ansible/latest/collections/community/general/index.html)** (анг.) — модули `parted`, `lvg`, `lvol`, `mdadm`, `zfs`, `btrfs`.
