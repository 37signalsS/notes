# Управление файловыми системами и хранилищем через Ansible

> **Основной SSoT:** **[Ansible/Modules/ansible_storage_and_disk_management_modules.md](../Modules/ansible_storage_and_disk_management_modules.md)**. Здесь хранятся полные определения, версии модулей, параметры и базовые сценарии parted/LVM/RAID/ZFS/Btrfs/LUKS/thin provisioning.
> **Кроссплатформенный контекст:** **[Ansible/CrossPlatform/ansible_cross_platform_system_config.md](../CrossPlatform/ansible_cross_platform_system_config.md)** — монтирование на Linux/BSD/Solaris/Windows/macOS.

## Определения

**Filesystem management (управление ФС)** — автоматизация разметки дисков, создания файловых систем, монтирования и управления LVM/RAID/ZFS/Btrfs через декларативные модули Ansible.

**Blast radius (радиус поражения)** — множество хостов или томов, затронутых при сбое storage-операции. В контексте Ansible это обычно scope плейбука (`--limit`, `serial`, tags).

**MTTR (Mean Time To Repair)** — среднее время восстановления storage после сбоя. Ansible снижает MTTR за счёт идемпотентных операций, предварительной валидации и автоматизированных recovery-сценариев.

**Thin provisioning overcommit** — режим, при котором суммарный размер thin LV превышает физический размер thin pool. Риск: `data_percent` > 100 % приводит к остановке записи и потенциальной потере данных.

**Snapshot rotation (ротация снапшотов)** — политика удаления старых снапшотов по порогу возраста/размера, а не по фиксированному расписанию. Предотвращает исчерпание pool.

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

### Привилегированный доступ

Все операции с блочными устройствами и монтированием требуют `become: yes`. Убедитесь, что на управляемых хостах настроен `sudo` без пароля для пользователя Ansible или используется `--become` с сохранённым ключом.

### Идемпотентность

Модули управления хранилищем идемпотентны по умолчанию:
- `state: present` — создаёт ресурс только если он отсутствует.
- `state: absent` — удаляет ресурс только если он существует.
- `size: +100G` — расширяет том только если текущий размер меньше целевого.

### Модель выполнения

Все модули выполняют операции **на управляемом хосте**:
- Утилиты `parted`, `lvm`, `mdadm`, `mkfs`, `cryptsetup` должны быть установлены на целевом хосте.
- При работе с shared storage (SAN/NAS) убедитесь, что блочное устройство видно на целевом хосте (multipath, zoning).

## Практические сценарии

### Сценарий 1: Pre-flight аудит дискового пространства (blast radius minimization)

Перед любой storage-операцией выполните идемпотентный аудит: проверьте свободное место, статус RAID, LVM и ZFS. Это снижает риск каскадного сбоя и позволяет принять решение об отказе операции.

```yaml
- name: Pre-flight storage audit
  hosts: storage_servers
  gather_facts: yes
  tasks:
    - name: Свободное место на корневой ФС
      ansible.builtin.stat:
        path: /
      register: root_fs

    - name: Проверка статуса RAID
      ansible.builtin.command: cat /proc/mdstat
      register: mdstat
      changed_when: false
      failed_when: mdstat.rc != 0

    - name: Проверка статуса LVM VG
      ansible.builtin.command: vgdisplay -c
      register: vgdisplay
      changed_when: false

    - name: Проверка статуса ZFS pool
      ansible.builtin.command: zpool list -H
      register: zpool_list
      changed_when: false
      failed_when: false

    - name: Отчёт по storage health
      ansible.builtin.debug:
        msg: |
          Host: {{ inventory_hostname }}
          Root FS free: {{ (root_fs.stat.size - root_fs.stat.blocks_available * 1024) / 1024 / 1024 / 1024 | round(1) }} GB
          RAID: {{ mdstat.stdout | regex_search('md[0-9]+.*?[a-z]+', multiline=True) }}
          VGs: {{ vgdisplay.stdout_lines | length }}
          ZFS pools: {{ zpool_list.stdout_lines | length }}
```

**SRE-рекомендации:**
- Встройте pre-flight audit в `pre_tasks` плейбука. Если audit падает — операция не выполняется.
- Для production установите порог: если свободного места < 15 %, операция отменяется с явным сообщением.
- Используйте `check_mode` для dry-run оценки изменений.

### Сценарий 2: Расширение LV в maintenance window с approval gate

Автоматизация расширения storage с ограничением по хостам (`serial`), approval- gate через `pause` и валидацией результата. Подходит для scheduled change management.

```yaml
- name: Расширение LV в maintenance window
  hosts: db_servers
  serial: 1
  vars:
    target_vg: vg_data
    target_lv: lv_pgdata
    expand_size: +50G
  tasks:
    - name: Approval gate
      ansible.builtin.pause:
        prompt: |
          Approve LV expansion on {{ inventory_hostname }}?
          VG: {{ target_vg }}, LV: {{ target_lv }}, Size: {{ expand_size }}
      when: ansible_facts['distribution'] != 'Windows'

    - name: Проверка свободного места в VG
      ansible.builtin.command: vgdisplay {{ target_vg }} --units g --noheadings | awk '{print $NF}'
      register: vg_free
      changed_when: false

    - name: Проверка, что VG имеет достаточно места
      ansible.builtin.assert:
        that:
          - vg_free.stdout is regex("^\\d+\\.\\d+")
          - vg_free.stdout | float > 50
        fail_msg: "VG {{ target_vg }} has less than 50 GB free. Abort."
        success_msg: "VG {{ target_vg }} has {{ vg_free.stdout }} GB free. Proceeding."

    - name: Расширение LV
      community.general.lvol:
        vg: "{{ target_vg }}"
        lv: "{{ target_lv }}"
        size: "{{ expand_size }}"
      register: lv_expand

    - name: Расширение XFS
      ansible.builtin.filesystem:
        fstype: xfs
        dev: "/dev/{{ target_vg }}/{{ target_lv }}"
        resizefs: yes
      when: lv_expand.changed

    - name: Валидация нового размера
      ansible.builtin.command: lvdisplay -c /dev/{{ target_vg }}/{{ target_lv }} | cut -d: -f6
      register: lv_size_after
      changed_when: false
      when: lv_expand.changed
```

**SRE-рекомендации:**
- `serial: 1` гарантирует, что операция выполняется на одном хосте за раз. Для больших кластеров используйте `serial: "30%"`.
- `ansible.builtin.pause` с `prompt` — простейший approval gate. Для enterprise используйте `ansible.builtin.wait_for` + вебхук approval или callback-плагин.
- Никогда не расширяйте production LV без проверки свободного места в VG и health RAID/ZFS.

### Сценарий 3: Автоматический disaster recovery backup метаданных LVM/RAID/ZFS

Метаданные LVM, RAID и ZFS — критичные данные для восстановления после отказа. Автоматизируйте их бэкап в один файл на каждом хосте и выгрузку в центральное хранилище.

```yaml
- name: DR backup metadata storage
  hosts: storage_servers
  become: yes
  vars:
    backup_dir: /var/backups/storage-meta
  tasks:
    - name: Создание директории для бэкапов
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: '0700'

    - name: Бэкап метаданных VG
      ansible.builtin.command: vgcfgbackup -f {{ backup_dir }}/vg_{{ item }}.cfg {{ item }}
      loop: "{{ lvm_vgs }}"
      register: vg_backup
      changed_when: "'backed up' in vg_backup.stdout | default('')"

    - name: Экспорт конфигурации mdadm
      ansible.builtin.command: mdadm --detail --scan > {{ backup_dir }}/mdadm.conf
      register: mdadm_backup
      changed_when: false

    - name: Бэкап заголовка LUKS (если есть)
      ansible.builtin.command: >
        cryptsetup luksHeaderBackup {{ item }}
        --header-backup-file {{ backup_dir }}/luks_{{ item | basename }}.bak
      loop: "{{ luks_devices | default([]) }}"
      register: luks_backup
      no_log: yes
      changed_when: luks_backup.rc == 0

    - name: Экспорт конфигурации ZFS
      ansible.builtin.command: zpool export -a && zpool import
      register: zpool_status
      changed_when: false
      failed_when: false

    - name: Архивирование метаданных
      ansible.builtin.command: tar -C {{ backup_dir }} -czf {{ backup_dir }}/storage-meta-{{ ansible_date_time.date }}.tar.gz .
      register: archive_result
      changed_when: archive_result.rc == 0

    - name: Ротация бэкапов (хранить 30 дней)
      ansible.builtin.command: find {{ backup_dir }} -name 'storage-meta-*.tar.gz' -mtime +30 -delete
      changed_when: false
```

**SRE-рекомендации:**
- Храните бэкапы метаданных отдельно от данных. При отказе диска заголовок LUKS без бэкапа не восстановить.
- Тестируйте восстановление: раз в квартал разворачивайте isolated стенд, восстанавливайте VG metadata и монтируйте LV.
- Включите задачу в disaster recovery runbook.

### Сценарий 4: Мониторинг thin pool и алертинг при переполнении

Thin pool исчерпается раньше за счёт overprovisioning. Автоматизируйте сбор `data_percent` и алертинг при пороге 80 %.

```yaml
- name: Thin pool monitoring
  hosts: storage_servers
  gather_facts: no
  vars:
    thin_pools:
      - vg_data/thin_pool
      - vg_logs/thin_pool
    warning_threshold: 80
    critical_threshold: 95
  tasks:
    - name: Сбор метрик thin pool
      ansible.builtin.command: lvs --noheadings --units g -o lv_name,data_percent,metadata_percent {{ item }}
      loop: "{{ thin_pools }}"
      register: thin_metrics
      changed_when: false

    - name: Парсинг метрик
      ansible.builtin.set_fact:
        thin_alerts: >-
          {{
            thin_alerts | default([]) + [{
              'pool': item.item,
              'data_percent': (item.stdout | regex_search('^(\\S+)\\s+([0-9.]+)', '\\2') | float),
              'metadata_percent': (item.stdout | regex_search('^(\\S+)\\s+[0-9.]+\\s+([0-9.]+)', '\\2') | float)
            }]
          }}
      loop: "{{ thin_metrics.results }}"

    - name: Алерт при превышении порога
      ansible.builtin.debug:
        msg: "CRITICAL: {{ item.pool }} data_percent={{ item.data_percent }}%"
      loop: "{{ thin_alerts }}"
      when: item.data_percent > critical_threshold

    - name: Предупреждение при приближении к порогу
      ansible.builtin.debug:
        msg: "WARNING: {{ item.pool }} data_percent={{ item.data_percent }}%"
      loop: "{{ thin_alerts }}"
      when: item.data_percent > warning_threshold and item.data_percent <= critical_threshold
```

**SRE-рекомендации:**
- `poolmetadatasize` должен быть не менее 1 % от размера pool, но не менее 4G. При большом количестве LV увеличьте до 8–16G.
- Избегайте `force: yes` при расширении thin pool — при переполнении это может привести к невосстановимой потере данных.
- Интегрируйте сбор метрик в `ansible.builtin.stat` или callback-плагин для отправки в Prometheus.

### Сценарий 5: Отказоустойчивый mount с fallback и noauto

Настройка точки монтирования с fallback-опцией при недоступности устройства. Используется на shared storage и для канареечного деплоя.

```yaml
- name: Отказоустойчивый mount с fallback
  hosts: app_servers
  become: yes
  vars:
    mount_path: /var/lib/app
    mount_src: /dev/vg_data/lv_app
    mount_fstype: xfs
  tasks:
    - name: Монтирование с x-systemd.automount
      ansible.builtin.mount:
        path: "{{ mount_path }}"
        src: "{{ mount_src }}"
        fstype: "{{ mount_fstype }}"
        state: mounted
        opts: defaults,noatime,x-systemd.automount,x-systemd.idle-timeout=10min
      register: mount_result

    - name: Проверка доступности mount
      ansible.builtin.command: mountpoint -q {{ mount_path }}
      changed_when: false
      failed_when: false
      register: mountpoint_check

    - name: Отчёт о статусе mount
      ansible.builtin.debug:
        msg: "Mount {{ mount_path }} is {{ 'available' if mountpoint_check.rc == 0 else 'unavailable' }}"
```

**SRE-рекомендации:**
- `x-systemd.automount` — устройство монтируется при первом обращении, а не при загрузке. Уменьшает blast radius при недоступном storage.
- Для критичных сервисов добавьте `_netdev` (сетевые ФС) или `nofail` (игнорировать ошибку при загрузке).
- Проверяйте `mountpoint -q` после deployment; добавьте health check в runbook.

### Сценарий 6: Change management — деплой storage-изменений с dry-run

Использование `check_mode` и `--diff` для review storage-операций перед применением. Подходит для change approval board (CAB) и CI/CD пайплайнов.

```bash
# Dry-run: показать, что будет изменено
ansible-playbook site.yml -i inventories/production/ \
  --limit storage_servers \
  --check --diff \
  -e "storage_expand_size=+100G"

# Применение после approval
ansible-playbook site.yml -i inventories/production/ \
  --limit storage_servers \
  --diff \
  -e "storage_expand_size=+100G"
```

```yaml
# tasks/storage_expand.yml
- name: Расширение LV
  community.general.lvol:
    vg: "{{ target_vg }}"
    lv: "{{ target_lv }}"
    size: "{{ storage_expand_size | default('+50G') }}"
  register: lv_expand

- name: Расширение ФС
  ansible.builtin.filesystem:
    fstype: xfs
    dev: "/dev/{{ target_vg }}/{{ target_lv }}"
    resizefs: yes
  when: lv_expand.changed | default(false)
```

**SRE-рекомендации:**
- Всегда запускайте `--check --diff` перед применением в production. Результат `--diff` показывает точное изменение размера LV.
- Для CI/CD добавьте job, который выполняет `ansible-playbook --check` на every PR, меняющей storage-код.
- Сохраняйте вывод `--diff` в artifact хранилище для compliance и post-mortem.

### Сценарий 7: Кросс-платформенный mount (Linux, BSD, Solaris, Windows)

`ansible.builtin.mount` поддерживает `/etc/fstab` (Linux/BSD), `/etc/vfstab` (Solaris) и реестр Windows. Один плейбук для mixed-парка.

```yaml
- name: Кросс-платформенное монтирование
  hosts: all
  become: yes
  tasks:
    - name: Монтирование на Linux/BSD
      ansible.builtin.mount:
        path: /data
        src: /dev/sdb1
        fstype: xfs
        state: mounted
        opts: defaults,noatime
      when: ansible_facts['system'] != 'Win32NT'

    - name: Монтирование на Windows
      ansible.windows.win_format:
        drive_letter: D
        file_system: NTFS
        label: Data
      when: ansible_facts['system'] == 'Win32NT'

    - name: Монтирование на Windows (запись в реестр)
      ansible.windows.win_mount:
        path: D:\Data
        state: present
      when: ansible_facts['system'] == 'Win32NT'

    - name: Монтирование на Solaris
      ansible.builtin.mount:
        path: /data
        src: /dev/dsk/c1t0d0s0
        fstype: ufs
        state: mounted
      when: ansible_facts['system'] == 'SunOS'
```

**SRE-рекомендации:**
- На Windows используйте `win_format` + `win_mount`; `/etc/fstab` не существует — монтирование управляется через реестр (`HKLM:\SYSTEM\CurrentControlSet\Services\mountmgr`).
- На Solaris используется `/etc/vfstab`; `ansible.builtin.mount` автоматически определяет ОС и выбирает правильный конфиг-файл.
- На macOS используйте `/etc/fstab` или `autofs`; `ansible.builtin.mount` поддерживает macOS начиная с ansible-core 2.18.

### Сценарий 8: Восстановление LV после отказа диска (rollback)

Автоматизация отката расширения LV и ФС при сбое операции. Восстанавливает оригинальный размер LV и пересоздаёт ФС, если это необходимо.

```yaml
- name: Rollback расширения LV
  hosts: db_servers
  become: yes
  vars:
    target_vg: vg_data
    target_lv: lv_pgdata
    original_size: 200G
  tasks:
    - name: Проверка текущего размера LV
      ansible.builtin.command: lvdisplay -c /dev/{{ target_vg }}/{{ target_lv }} | cut -d: -f6
      register: current_size
      changed_when: false

    - name: Сокращение LV до оригинального размера
      community.general.lvol:
        vg: "{{ target_vg }}"
        lv: "{{ target_lv }}"
        size: "{{ original_size }}"
      when: current_size.stdout != original_size

    - name: Пересоздание XFS (только если LV сокращён)
      ansible.builtin.filesystem:
        fstype: xfs
        dev: "/dev/{{ target_vg }}/{{ target_lv }}"
        force: yes
      when: current_size.stdout != original_size
      ignore_errors: yes

    - name: Проверка целостности данных (если пересоздание не требуется)
      ansible.builtin.command: xfs_repair -n /dev/{{ target_vg }}/{{ target_lv }}
      register: xfs_check
      changed_when: false
      when: current_size.stdout == original_size
```

**SRE-рекомендации:**
- XFS нельзя уменьшить (`shrink`) штатными средствами. Для rollback используйте `filesystem` с `force: yes` (пересоздание) или восстановите из бэкапа.
- Всегда тестируйте rollback на staging перед использованием в production.
- Добавьте rollback в runbook как отдельный playbook, а не как inline-задачи.

### Сценарий 9: Автоматическое тестирование storage-конфигурации на staging

Перед применением storage-операций в production запускайте их на staging-хосте с аналогичной конфигурацией. Ansible roles и inventory переменные обеспечивают переносимость.

```yaml
# inventories/storage/hosts.yml
[storage_servers]
stg-db01 ansible_host=10.0.1.10
prd-db01 ansible_host=10.0.2.10

[storage_servers:vars]
storage_vg: vg_data
storage_lv: lv_pgdata
storage_size: 200G
storage_fstype: xfs
storage_mount: /var/lib/pgdata

# site.yml
- name: Storage configuration on staging
  hosts: storage_servers
  serial: 1
  vars_files:
    - vault/storage.yml
  tasks:
    - import_tasks: tasks/storage_expand.yml
      tags: storage

# Запуск на staging
ansible-playbook site.yml -i inventories/storage/hosts.yml \
  --limit stg-db01 \
  --tags storage \
  --check --diff

# После approval — на production
ansible-playbook site.yml -i inventories/storage/hosts.yml \
  --limit prd-db01 \
  --tags storage \
  --diff
```

**SRE-рекомендации:**
- Используйте inventory groups (`staging` / `production`) для изоляции окружений. Никогда не применяйте storage-операции на production без теста на staging.
- `serial: 1` на staging позволяет наблюдать за поведением LV/RAID/ФС на реальном железе, а не только в dry-run.
- Для CI/CD добавьте job, который запускает storage-плейбук на ephemeral VM или LXC-контейнере.

## Операции и команды

### Проверка состояния storage

| Операция | Команда | Ожидаемый вывод |
| :--- | :--- | :--- |
| Список физических томов | `pvs` | `PV /dev/sdb1 VG vg_data PV Size 100.00 GB` |
| Список групп томов | `vgs` | `VG vg_data #PV 1 #LV 2 VSize 100.00 GB` |
| Список логических томов | `lvs` | `LV lv_pgdata VG vg_data LSize 200.00 GB` |
| Проверка VG | `vgdisplay vg_data` | `VG Size: 100.00 GB`, `Free PE / Size: 50 / 200.00 GB` |
| Проверка LV | `lvdisplay /dev/vg_data/lv_pg_data` | `LV Size: 200.00 GB`, `LV Status: available` |
| Проверка RAID | `cat /proc/mdstat` | `md0: active raid10 sda1[0] sdb1[1]` |
| Проверка ZFS pool | `zpool list` | `NAME SIZE ALLOC FREE tank 1.9T 500G 1.4T` |
| Проверка ZFS datasets | `zfs list` | `NAME USED AVAIL REFER MOUNTPOINT tank/data 500G` |
| Проверка thin pool | `lvs --noheadings --units g -o lv_name,data_percent,metadata_percent vg_data/thin_pool` | `thin_pool 45.2 1.1` |
| Проверка mount | `mount | grep /data` | `/dev/md0 on /data type xfs` |
| Проверка fstab | `findmnt --verify` | `/etc/fstab: parse error` или пустой вывод |

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
| Резервное копирование метаданных VG | `vgcfgbackup -f /root/vg_data.cfg vg_data` |

### Управление RAID

| Операция | Команда |
| :--- | :--- |
| Создание RAID 10 | `mdadm --create /dev/md0 --level=10 --raid-devices=4 /dev/sd{c,d,e,f}` |
| Проверка статуса | `cat /proc/mdstat` |
| Сохранение конфига | `mdadm --detail --scan >> /etc/mdadm.conf` |
| Добавление hot spare | `mdadm --add /dev/md0 /dev/sdx` |
| Замена отказавшего диска | `mdadm --replace /dev/sda1 --with /dev/sdx1 /dev/md0` |
| Мониторинг | `mdadm --monitor --mail=ops@example.com /dev/md0` |

### Управление LUKS

| Операция | Команда |
| :--- | :--- |
| Инициализация LUKS | `cryptsetup luksFormat /dev/vg_data/lv_pgdata` |
| Открытие контейнера | `cryptsetup open /dev/vg_data/lv_pgdata luks_pgdata` |
| Закрытие контейнера | `cryptsetup close luks_pgdata` |
| Резерв заголовка | `cryptsetup luksHeaderBackup /dev/vg_data/lv_pgdata --header-backup-file /root/luks_header.bak` |
| Проверка статуса | `cryptsetup status luks_pgdata` |

## Устранение неполадок

### Типичные ошибки storage-операций

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Device or resource busy` | Том смонтирован или используется процессом | `umount /var/lib/pgdata`, проверьте `lsof +D /var/lib/pgdata` |
| `Volume group "vg_data" not found` | VG не существует или не активирована | `vgdisplay`, `vgchange -a y vg_data` |
| `Logical volume not found` | LV не существует или не активирована | `lvdisplay`, `lvchange -a y /dev/vg_data/lv_pg_data` |
| `Filesystem is already mounted` | ФС смонтирована в другом месте (bind mount) | `mount | grep xfs`, проверьте `findmnt` |
| `RAID array is degraded` | Отказал диск в RAID-массиве | `cat /proc/mdstat`, замените диск, `mdadm --add` |
| `No space left on device` | LV или VG исчерпан | `vgextend`, `lvextend` |
| `thin pool data percent > 100` | Переполнение thin pool | Остановите запись, расширьте pool, удалите старые снапшоты |
| `LUKS device not found` | Контейнер закрыт или заголовок поврежден | `cryptsetup status`, восстановите заголовок из бэкапа |
| `cryptsetup: device is busy` | Маппер используется смонтированной ФС | Размонтируйте, закройте контейнер |
| `Incorrect passphrase` | Неверный пароль LUKS | `cryptsetup luksOpen --try-passphrase`, восстановите из заголовка |

### Диагностические команды

```bash
# Проверка физических томов
pvs
# → PV /dev/sdb1   VG vg_data   PV Size 100.00 GB

# Проверка групп томов
vgdisplay vg_data
# → VG Name: vg_data
# → VG Size: 100.00 GB
# → Free PE / Size: 50 / 200.00 GB

# Проверка логических томов
lvdisplay /dev/vg_data/lv_pg_data
# → LV Path: /dev/vg_data/lv_pg_data
# → LV Size: 200.00 GB
# → LV Status: available

# Проверка thin pool
lvs --noheadings --units g -o lv_name,data_percent,metadata_percent vg_data/thin_pool
# → thin_pool  45.2  1.1

# Проверка RAID
cat /proc/mdstat
# → md0: active raid10 sda1[0] sdb1[1]

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

# Проверка монтирования
findmnt /data
# → TARGET  SOURCE    FSTYPE OPTIONS
# → /data   /dev/md0  xfs    rw,noatime,attr2,inode64,noquota
```

## Рекомендации и оптимизация

### Безопасность storage-операций

| Риск | Мера | Инструмент |
| :--- | :--- | :--- |
| Физический доступ к диску | Шифрование LUKS | `community.crypto.luks_device`, `cryptsetup` |
| Неавторизованный mount | `noauto`, `x-systemd.automount`, `nofail` | `ansible.builtin.mount` |
| Утечка метаданных LVM | Отключение автоматической активации VG | `vgchange --setautoactivation ignore` |
| Неавторизованное расширение LV | Approval gate, `serial: 1`, pre-flight audit | `ansible.builtin.pause`, `--check` |
| Утечка заголовка LUKS | Резервное копирование заголовка | `cryptsetup luksHeaderBackup` |

### Change management для storage

- **Maintenance window:** планируйте storage-операции (расширение LV, пересоздание ФС, замена диска) в approved maintenance window.
- **Serial execution:** используйте `serial: 1` или `serial: "30%"` для каскадного деплоя. Это минимизирует blast radius.
- **Pre-flight audit:** запускайте pre-flight проверку (свободное место, RAID health, ZFS pool status) перед любой операцией.
- **Approval gate:** используйте `ansible.builtin.pause` или callback-плагин для approval workflow.
- **Dry-run:** всегда запускайте `--check --diff` перед применением в production.
- **Rollback plan:** имейте готовый rollback playbook (восстановление размера LV, пересоздание ФС, восстановление из бэкапа).

### Monitoring и observability

- **Дисковое пространство:** интегрируйте `ansible.builtin.stat` или callback-плагин для сбора метрик в Prometheus/Grafana.
- **SMART:** настраивайте `smartd` для алертов при отказе дисков (Self-Monitoring, Analysis and Reporting Technology).
- **RAID:** мониторьте `/proc/mdstat` и `mdadm --monitor` для уведомлений о деградации массива.
- **LVM thin pool:** мониторьте `data_percent` и `metadata_percent`; алертите при > 80 %.
- **I/O latency:** `iostat -dx 1` или `node_exporter` metrics `node_disk_io_time_weighted_seconds_total` для SLO.
- **Audit logging:** включите `log_plays = True` в `ansible.cfg` для compliance и post-mortem анализа storage-изменений.

### Производительность и масштабирование

- **Очереди I/O:** для NVMe используйте `nr_requests=1024` и `nomerges=0` в udev rules; для HDD — `scheduler=mq-deadline`.
- **Флаги монтирования:** `noatime` или `relatime` для снижения записи; `discard` для SSD (или `fstrim.timer`).
- **XFS inode64:** для ФС > 1TB используйте `mkfs.xfs -i inode64`, иначе ограничение 2^31 inodes.
- **Асинхронность:** при массовой настройке storage (>50 хостов) используйте `async` + `poll` для долгих операций `mkfs` и `cryptsetup`.
- **delegate_to:** для shared storage (SAN/NAS) централизуйте форматирование через `delegate_to` на storage-шлюзе, чтобы избежать конфликтов доступа к блочному устройству.

### Эксплуатация и disaster recovery

- **Ротация снапшотов:** для Btrfs/ZFS/LVM используйте возраст и размер снапшотов, а не только календарь. Удаляйте снапшоты при `data_percent` > 80 % thin pool.
- **Бэкап метаданных:** `vgcfgbackup`, `mdadm --detail --scan`, `cryptsetup luksHeaderBackup` — включите в disaster recovery playbook.
- **Тестирование восстановления:** раз в квартал восстанавливайте VG/LV metadata на изолированном стенде.
- **Документация:** храните схему storage (VG→LV→mountpoint→owner→SLO) в wiki/ITSM; Ansible playbook — не замена документации, а её исполнение.

## Дополнительная информация

- **[Ansible/Modules/ansible_storage_and_disk_management_modules.md](../Modules/ansible_storage_and_disk_management_modules.md)** — полные определения, версии модулей, параметры и базовые сценарии.
- **[Ansible/CrossPlatform/ansible_cross_platform_system_config.md](../CrossPlatform/ansible_cross_platform_system_config.md)** — кроссплатформенное монтирование (Linux/BSD/Solaris/Windows/macOS).
