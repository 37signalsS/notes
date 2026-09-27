# Автоматизация LVM через Ansible: модули, сценарии и best practices

## Определения

**Ansible** — инструмент автоматизации конфигурации систем (Infrastructure as Code), использующий declarative YAML-описания (playbooks) и SSH-доступ к Managed Nodes. Не требует агентов на управляемых узлах.

**Module** — модуль Ansible, реализующий конкретную операцию (создание LV, расширение VG и т.д.). Модули идемпотентны: повторный запуск не изменяет систему, если она уже в целевом состоянии.

**Idempotency (Идемпотентность)** — свойство playbook: повторное выполнение с теми же параметрами не приводит к изменениям. Критично для LVM-операций, чтобы избежать дублирования PV/VG/LV.

**Volume Group (VG)** — виртуальный пул физических томов. В Ansible управляется через модуль `community.general.lvg`.

**Logical Volume (LV)** — логический том в пределах VG. Управляется через модуль `community.general.lvol`.

**Physical Volume (PV)** — физический диск, инициализированный для LVM. Управляется через модуль `community.general.lvg` (при добавлении дисков).

## Базовые концепции

### Иерархия модулей Ansible для LVM

| Модуль | Назначение | Ключевые параметры |
|:---|:---|:---|
| `community.general.lvg` | Управление VG (создание, расширение, уменьшение) | `vg`, `pvs`, `state` |
| `community.general.lvol` | Управление LV (создание, расширение, удаление) | `lv`, `vg`, `size`, `state` |
| `ansible.builtin.parted` | Создание разделов перед `lvg` | `device`, `part_type`, `number` |
| `ansible.builtin.filesystem` | Создание ФС на LV | `fstype`, `dev` |
| `ansible.builtin.mount` | Монтирование LV | `path`, `src`, `fstype` |

### Поток данных (Data Flow)

```
Inventory (hosts.yml)
    ↓
Playbook (site.yml)
    ↓
Role: lvm_setup
  ├── tasks/main.yml
  │   ├── parted (создание разделов)
  │   ├── lvg (создание/расширение VG)
  │   ├── lvol (создание/расширение LV)
  │   ├── filesystem (создание ФС)
  │   └── mount (монтирование)
  └── defaults/main.yml
        └── переменные (размеры, имена VG/LV)
```

## Практические сценарии

### Шаг 1: Базовый playbook — создание VG и LV

```yaml
# playbook_lvm.yml
---
- name: LVM Setup
  hosts: db_servers
  become: yes
  vars:
    vg_name: vg_data
    pv_disks:
      - /dev/sdb
      - /dev/sdc
    lvs:
      - name: lv_db
        size: 100G
        fstype: xfs
        mount: /var/lib/postgresql
      - name: lv_logs
        size: 50G
        fstype: ext4
        mount: /var/log/app
  tasks:
    - name: Ensure PVs exist
      community.general.lvg:
        vg: "{{ vg_name }}"
        pvs: "{{ pv_disks }}"
        state: present

    - name: Create LVs
      community.general.lvol:
        lv: "{{ item.name }}"
        vg: "{{ vg_name }}"
        size: "{{ item.size }}"
        state: present
      loop: "{{ lvs }}"

    - name: Create filesystems
      community.general.filesystem:
        fstype: "{{ item.fstype }}"
        dev: "/dev/{{ vg_name }}/{{ item.name }}"
      loop: "{{ lvs }}"

    - name: Mount LVs
      ansible.builtin.mount:
        path: "{{ item.mount }}"
        src: "/dev/{{ vg_name }}/{{ item.name }}"
        fstype: "{{ item.fstype }}"
        state: mounted
      loop: "{{ lvs }}"
```

```bash
ansible-playbook -i inventory.ini playbook_lvm.yml
```

### Шаг 2: Role для переиспользования

```
roles/
  lvm_setup/
    ├── defaults/
    │   └── main.yml        # Значения по умолчанию
    ├── tasks/
    │   └── main.yml        # Основные задачи
    ├── handlers/
    │   └── main.yml        # Обработчики (resize2fs, xfs_growfs)
    └── vars/
        └── debian.yml      # Переменные для Debian
        └── redhat.yml      # Переменные для RHEL
```

```yaml
# roles/lvm_setup/defaults/main.yml
---
vg_name: vg_data
pv_disks: []
lvs: []
fs_type: xfs
mount_state: mounted

# roles/lvm_setup/tasks/main.yml
---
- name: Include OS-specific variables
  include_vars: "{{ ansible_os_family | lower }}.yml"

- name: Create PV and VG
  community.general.lvg:
    vg: "{{ vg_name }}"
    pvs: "{{ pv_disks }}"
    state: present
  when: pv_disks | length > 0

- name: Create LVs
  community.general.lvol:
    lv: "{{ item.name }}"
    vg: "{{ vg_name }}"
    size: "{{ item.size | default('10G') }}"
    opts: "{{ item.opts | default(omit) }}"
    state: present
  loop: "{{ lvs }}"
  notify: "{{ 'Grow ' + item.fstype if item.grow | default(false) else omit }}"

- name: Create filesystems
  community.general.filesystem:
    fstype: "{{ item.fstype | default(fs_type) }}"
    dev: "/dev/{{ vg_name }}/{{ item.name }}"
    opts: "{{ item.fs_opts | default(omit) }}"
  loop: "{{ lvs }}"
  when: item.create_fs | default(true)

- name: Ensure mount points exist
  ansible.builtin.file:
    path: "{{ item.mount }}"
    state: directory
  loop: "{{ lvs }}"
  when: item.mount is defined

- name: Mount LVs
  ansible.builtin.mount:
    path: "{{ item.mount }}"
    src: "/dev/{{ vg_name }}/{{ item.name }}"
    fstype: "{{ item.fstype | default(fs_type) }}"
    opts: "{{ item.mount_opts | default('defaults') }}"
    state: "{{ mount_state }}"
  loop: "{{ lvs }}"
  when: item.mount is defined

# roles/lvm_setup/handlers/main.yml
---
- name: Grow xfs
  community.general.filesystem:
    fstype: xfs
    dev: "/dev/{{ vg_name }}/{{ item.name }}"
    resizefs: true

- name: Grow ext4
  community.general.filesystem:
    fstype: ext4
    dev: "/dev/{{ vg_name }}/{{ item.name }}"
    resizefs: true
```

### Шаг 3: Инвентори сгруппированных серверов

```yaml
# inventory/hosts.yml
---
all:
  children:
    db_servers:
      hosts:
        db-01:
          ansible_host: 10.0.1.10
          pv_disks:
            - /dev/nvme0n1
            - /dev/nvme1n1
          lvs:
            - name: lv_pg_data
              size: 500G
              mount: /var/lib/postgresql
            - name: lv_pg_wal
              size: 100G
              mount: /var/lib/postgresql_wal
        db-02:
          ansible_host: 10.0.1.11
          pv_disks:
            - /dev/sda
          lvs:
            - name: lv_pg_data
              size: 200G
              mount: /var/lib/postgresql
```

### Шаг 4: Расширение LV через Ansible

```yaml
# playbook_resize.yml
---
- name: Resize LVM
  hosts: db_servers
  become: yes
  tasks:
    - name: Extend LV
      community.general.lvol:
        lv: lv_pg_data
        vg: vg_data
        size: +200G
        state: present

    - name: Resize XFS filesystem
      community.general.filesystem:
        fstype: xfs
        dev: /dev/vg_data/lv_pg_data
        resizefs: true
```

### Шаг 5: Идемпотентные проверки

```yaml
# tasks/check_lvm.yml
---
- name: Check if VG exists
  ansible.builtin.shell: vgs --noheadings -o vg_name | grep -q "{{ vg_name }}"
  register: vg_check
  changed_when: false

- name: Debug VG status
  ansible.builtin.debug:
    msg: "VG {{ vg_name }} {{ 'exists' if vg_check.rc == 0 else 'does NOT exist' }}"

- name: Check LV size
  ansible.builtin.shell: lvs --noheadings --nosuffix --units g -o lv_size {{ vg_name }}/{{ item.name }}
  register: lv_size
  loop: "{{ lvs }}"
  changed_when: false

- name: Report LV sizes
  ansible.builtin.debug:
    msg: "{{ item.item.name }}: {{ item.stdout }}G"
  loop: "{{ lv_size.results }}"
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
|:---|:---|:---|
| `No such device` | Диск не подключён или не виден | Проверить `lsblk`, `smartctl -i /dev/sdX` |
| `Volume group not found` | VG ещё не создан или неверное имя | Убедиться, что `community.general.lvg` отработал first |
| `Size is too small` | LV уже больше запрошенного размера | Использовать `state: present` (идемпотентно), не уменьшать LV через Ansible |
| `Filesystem already mounted` | Дублирование mount-задач | Проверить `mount_state: mounted` (не `present`) |
| `Permission denied` | Нет `become: yes` | Добавить `become: yes` в play или task |

### Best Practices

1. **Идемпотентность:** Используйте `state: present` для `lvg`/`lvol` — модули проверяют текущее состояние перед изменением.
2. **Проверка перед изменением:** Добавляйте `assert` или `shell`-проверки (см. Шаг 5) в критичные playbook'и.
3. **Логирование:** Используйте `register` + `debug` для фиксации изменений в логах Ansible.
4. **Шифрование секретов:** Для LUKS-контейнеров используйте `ansible-vault` для хранения паролей.
5. **Rollback plan:** Всегда продумывайте откат (snapshots, vgcfgbackup) перед大规模 операциями.
6. **Тестирование:** Запускайте playbook'и с `--check --diff` для preview без реальных изменений.

### См. также
- **[Ansible: Модули управления хранилищем и дисками](../../../Ansible/Modules/ansible_storage_and_disk_management_modules.md)** — SSoT по модулям `parted`, `lvg`, `lvol`, `mdadm`, `zfs`, `btrfs`, `luks_device`.
- **[LVM — Создание PV, VG, LV](./pv_vg_creation.md)** — ручные команды для понимания.
- **[LVM — Изменение размеров](./lvm_resize.md)** — онлайн-расширение.
