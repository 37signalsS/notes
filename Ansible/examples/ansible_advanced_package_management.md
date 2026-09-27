# Расширенное управление пакетами через Ansible

## Определения

**Package (пакет)** — архив с файлами программы, метаданными (версия, зависимости, описание) и скриптами установки/удаления. В Linux: `.deb` (Debian/Ubuntu), `.rpm` (RHEL/AlmaLinux/Rocky/Fedora), `.pkg.tar.zst` (Arch), `.apk` (Alpine). В Windows: `.msi`, `.exe`.

**Repository (репозиторий)** — хранилище пакетов, которое предоставляет пакеты для установки через менеджер пакетов (apt, dnf, zypper). Подробнее о теории репозиториев см. [Управление репозиториями пакетов в Linux](../../Linux/PackageManagement/Repository_Management/index.md).

**Dependency (зависимость)** — другой пакет, который требуется для работы устанавливаемого пакета. Менеджер пакетов автоматически разрешает зависимости.

**Version pinning** — фиксация конкретной версии пакета, чтобы предотвратить автоматическое обновление до более новой версии.

**Hold (удержание)** — состояние пакета, при котором менеджер пакетов не будет обновлять его автоматически. В Debian/Ubuntu: `apt-mark hold`; в RHEL/AlmaLinux/Rocky: `dnf versionlock add`.

**Package manager** — инструмент для установки, обновления и удаления пакетов: `apt` (Debian/Ubuntu), `dnf`/`dnf5` (RHEL 8+/AlmaLinux/Rocky/Fedora), `zypper` (SUSE/openSUSE), `apk` (Alpine), `pacman` (Arch), `chocolatey`/`winget` (Windows).

**DNF5** — новое поколение пакетного менеджера, полностью переписанное на C++ (`libdnf5`). Входит в RHEL 9/10, AlmaLinux 9/10, Rocky Linux 9/10, Fedora 41+. В Ansible доступен через модуль `ansible.builtin.dnf5` (добавлен в ansible-core 2.15). Отличия от DNF4: нет `enablerepo`/`disablerepo`, нет `download_dir`, другой `disable_gpg_check`. Подробнее см. [Ansible: Модули управления пакетами](../Modules/ansible_package_management_modules.md#dnf4-и-dnf5-два-модуля-один-менеджер-пакетов).

**Module stream (поток модуля)** — версия пакета или набора пакетов в репозитории AppStream (RHEL/AlmaLinux/Rocky). Например, `nodejs:18` и `nodejs:20` — разные потоки одного модуля.

**Versionlock** — механизм блокировки версий пакетов в DNF5/DNF4 через плагин `dnf-plugin-versionlock` или файлы в `/etc/dnf/plugins/`. В Debian/Ubuntu аналогичная функция — `apt-mark hold`.

**Local repository (локальный репозиторий)** — локальное хранилище пакетов для изолированных сетей, создаваемое через `reprepro` (APT) или `createrepo_c` (RPM). Снижает нагрузку на внешние каналы и ускоряет установку.

**Delta RPM (DRPM)** — механизм обновления пакетов, при котором загружается только разница между старой и новой версией. В DNF 5 поддержка DRPM удалена из соображений производительности.

**Package verification (верификация пакетов)** — проверка целостности установленных пакетов через `rpm -V` (RPM) или `debsums` (DEB). Критически важна для compliance и обнаружения несанкционированных изменений.

**Change management (управление изменениями)** — процесс применения изменений в инфраструктуре с контролем рисков: maintenance windows, serial deployment, throttle, pre/post validation.

## Базовые концепции

### Архитектура управления пакетами в инфраструктуре

```
Internet / External Repos
    ↓
[Internal Mirror / Local Repo] ← reprepro (APT), createrepo_c (RPM)
    ↓
[Ansible Control Node] → playbooks → managed hosts
    ↓
[Managed Hosts]
    ├── Debian/Ubuntu → apt / dpkg
    ├── RHEL/AlmaLinux/Rocky → dnf / dnf5 / rpm
    ├── SUSE/openSUSE → zypper / rpm
    └── Alpine → apk
```

**Для SRE:** управление пакетами через Ansible обеспечивает:
- **Идемпотентность** — повторный запуск не ломает рабочую конфигурацию
- **Аудит** — все изменения хранятся в Git
- **Восстанавливаемость** — можно откатить любое изменение через playbook
- **Масштабируемость** — одинаковые правила применяются к сотням хостов
- **Compliance** — версии пакетов фиксируются, drift обнаруживается автоматически
- **Change control** — deployment ведется через maintenance windows с throttle/serial

### Сравнение инструментов управления пакетами

| Дистрибутив / Семейство | Менеджер пакетов | Формат пакетов | Ansible модуль | Версия модуля |
|---|---|---|---|---|
| **Debian / Ubuntu** | apt / dpkg | `.deb` | `ansible.builtin.apt` | Стандартный |
| **RHEL 8 / AlmaLinux 8 / Rocky 8** | dnf (DNF4) | `.rpm` | `ansible.builtin.dnf` | `use_backend: auto` |
| **RHEL 9+ / AlmaLinux 9+ / Rocky 9+ / Fedora 41+** | dnf5 | `.rpm` | `ansible.builtin.dnf5` | Нативный DNF5 |
| **RHEL 8+ mixed** | dnf (DNF4/DNF5) | `.rpm` | `ansible.builtin.dnf` | `use_backend: auto` |
| **SUSE / openSUSE** | zypper | `.rpm` | `ansible.builtin.zypper` | Стандартный |
| **Alpine** | apk | `.apk` | `ansible.builtin.apk` | Стандартный |
| **Arch** | pacman | `.pkg.tar.zst` | `community.general.pacman` | Требует коллекцию |
| **Windows** | chocolatey / winget / MSI | `.msi`, `.exe` | `chocolatey.chocolatey.win_chocolatey`, `ansible.windows.win_package` | Коллекции |

### Жизненный цикл управления пакетами

1. **Оценка состояния** — сбор фактов о версиях пакетов, репозиториях, доступных обновлениях.
2. **Планирование изменений** — определение maintenance window, serial/throttle, approval workflow.
3. **Резервное копирование** — snapshot ЛВМ или сохранение списка пакетов для отката.
4. **Обновление кеша** — `apt update` / `dnf makecache` с контролем времени кеша.
5. **Применение изменений** — установка/обновление/удаление пакетов через Ansible модули.
6. **Валидация** — проверка версий, работа сервисов, health-check.
7. **Верификация целостности** — `rpm -V`, `debsums` для compliance.
8. **Аудит** — запись изменений в журнал, сверка с desired state.
9. **Документирование** — обновление SBOM, changelog.

### Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая версия | Проверка |
|---|---|---|---|
| **ansible-core** | 2.15 | 2.21+ | `ansible --version` |
| **Python** (control node) | 3.12 | 3.14 | `python3 --version` |
| **Python** (managed node) | 3.9 | 3.12+ | `python3 --version` |
| **apt** (Debian/Ubuntu) | 2.0 | Актуальная LTS | `apt --version` |
| **dnf** (RHEL/AlmaLinux/Rocky) | 4.0 | 5.0+ | `dnf --version` |
| **dnf5** (RHEL 9+/AlmaLinux 9+/Rocky 9+/Fedora 41+) | — | Актуальная | `dnf5 --version` |
| **zypper** (SUSE) | 1.14 | Актуальная LTS | `zypper --version` |
| **apk** (Alpine) | 2.10 | Актуальная LTS | `apk --version` |
| **createrepo_c** | 0.10 | Актуальная | `createrepo_c --version` |
| **reprepro** | 5.0 | Актуальная | `reprepro --version` |
| **debsums** | 2.0 | Актуальная | `debsums --version` |

### Ключевые принципы

1. **Idempotency** — установка пакета должна быть идемпотентной. Повторный запуск не должен вносить лишние изменения.
2. **Version pinning** — фиксируйте версии критичных пакетов. Используйте `apt-mark hold` (Debian/Ubuntu) или `dnf versionlock add` (RHEL/AlmaLinux/Rocky) для защиты от автоматических обновлений.
3. **Security** — проверяйте подписи пакетов (`gpgcheck=1`), используйте HTTPS репозитории, применяйте только security-обновления в production.
4. **Change management** — применяйте обновления через maintenance windows с контролем serial/throttle.
5. **Verification** — после обновления проверяйте целостность пакетов (`rpm -V`, `debsums`) и работоспособность сервисов.
6. **Audit** — все изменения фиксируются в Git, ведется журнал пакетных изменений.
7. **Local repositories** — используйте локальные репозитории для изолированных сред.
8. **Rollback readiness** — всегда имейте подготовленный план отката (snapshot, package list, rollback playbook).

## Практические сценарии

### Сценарий 1: Кроссплатформенное управление пакетами с версионированием

Универсальный плейбук для mixed-парка Debian/Ubuntu, RHEL/AlmaLinux/Rocky, Alpine с переменными версий и hold/versionlock.

```yaml
---
- name: Расширенное кроссплатформенное управление пакетами
  hosts: all
  become: true
  vars:
    packages_to_install:
      - name: nginx
        versions:
          Debian: "1.24.0-1ubuntu3"
          RedHat: "1.24.0-1.el9"
          Alpine: "1.24.0-r5"
        state: present
      - name: curl
        state: latest
      - name: htop
        state: absent

    packages_to_hold:
      Debian:
        - linux-image-generic
      RedHat:
        - kernel
      Alpine: []

  tasks:
    - name: Определение пакетного менеджера
      ansible.builtin.debug:
        msg: "Пакетный менеджер: {{ ansible_facts['pkg_mgr'] }}"

    - name: Установка пакетов с версионированием
      ansible.builtin.package:
        name: "{{ item.name }}{% if item.versions[ansible_facts['os_family']] is defined %}={{ item.versions[ansible_facts['os_family']] }}{% endif %}"
        state: "{{ item.state }}"
      loop: "{{ packages_to_install }}"

    - name: Удержание пакетов (Debian/Ubuntu)
      ansible.builtin.command: apt-mark hold {{ item }}
      loop: "{{ packages_to_hold[ansible_facts['os_family']] | default([]) }}"
      register: hold_result
      changed_when: "'was already' not in hold_result.stdout"
      when: ansible_facts['os_family'] == 'Debian'

    - name: Блокировка версий пакетов (RHEL/AlmaLinux/Rocky)
      ansible.builtin.command: dnf versionlock add {{ item }}
      loop: "{{ packages_to_hold[ansible_facts['os_family']] | default([]) }}"
      register: versionlock_result
      changed_when: "'added' in versionlock_result.stdout or 'already' not in versionlock_result.stdout"
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Проверка установленных версий
      ansible.builtin.command: "{{ 'dpkg -l' if ansible_facts['os_family'] == 'Debian' else 'rpm -q' }} {{ item.name }}"
      loop: "{{ packages_to_install }}"
      register: version_check
      changed_when: false

    - name: Вывод версий пакетов
      ansible.builtin.debug:
        msg: "{{ version_check.results | map(attribute='stdout') | list }}"
```

**Валидация:**

```bash
# Проверка установленных пакетов (Debian/Ubuntu)
dpkg -l nginx
# → ii  nginx                         1.24.0-1ubuntu3   amd64        Nginx web server

# Проверка hold (Debian/Ubuntu)
apt-mark showhold
# → linux-image-generic

# Проверка versionlock (RHEL/AlmaLinux/Rocky)
dnf versionlock list
# → kernel-*

# Проверка установленных пакетов (RHEL/AlmaLinux/Rocky)
rpm -q nginx
# → nginx-1.24.0-1.el9.x86_64

# Проверка установленных пакетов (Alpine)
apk info -v nginx
# → nginx-1.24.0-r5
```

### Сценарий 2: Управление пакетами в RHEL 9+/AlmaLinux 9+/Rocky 9+ с DNF5 и модулями

Настройка DNF5 с module streams, versionlock и security-only обновлениями.

```yaml
---
- name: Расширенное управление пакетами на RHEL 9+
  hosts: rhel9_servers
  become: true
  vars:
    dnf_packages:
      - name: nginx
        state: present
      - name: vim
        state: latest
      - name: telnet
        state: absent

    dnf_modules:
      - name: nodejs
        stream: "18"
        state: enabled
      - name: python39
        stream: "3.9"
        state: enabled

    dnf_repositories:
      - name: epel
        description: "Extra Packages for Enterprise Linux"
        baseurl: "https://download.fedoraproject.org/pub/epel/9/Everything/$basearch"
        gpgcheck: yes
        gpgkey: "https://download.fedoraproject.org/pub/epel/RPM-GPG-KEY-EPEL-9"

    packages_to_lock:
      - kernel
      - glibc
      - systemd

  tasks:
    - name: Обновление кеша dnf
      ansible.builtin.dnf:
        update_cache: yes
        cache_valid_time: 3600

    - name: Включение модулей AppStream
      ansible.builtin.dnf_module:
        name: "{{ item.name }}"
        stream: "{{ item.stream }}"
        state: "{{ item.state }}"
      loop: "{{ dnf_modules }}"

    - name: Установка пакетов
      ansible.builtin.dnf:
        name: "{{ item.name }}"
        state: "{{ item.state }}"
        enable_excludes: yes
      loop: "{{ dnf_packages }}"

    - name: Добавление репозиториев
      ansible.builtin.dnf_repository:
        name: "{{ item.name }}"
        description: "{{ item.description }}"
        baseurl: "{{ item.baseurl }}"
        gpgcheck: "{{ item.gpgcheck }}"
        gpgkey: "{{ item.gpgkey }}"
        state: present
      loop: "{{ dnf_repositories }}"
      notify: Update dnf cache

    - name: Блокировка критичных пакетов (versionlock)
      ansible.builtin.command: dnf versionlock add {{ item }}
      loop: "{{ packages_to_lock }}"
      register: versionlock_result
      changed_when: "'added' in versionlock_result.stdout"

    - name: Установка только security-обновлений
      ansible.builtin.dnf:
        name: "*"
        state: latest
        security: yes
      when: apply_security_updates | default(false)

    - name: Проверка установленных пакетов
      ansible.builtin.command: rpm -qa | grep nginx
      register: nginx_installed
      changed_when: false

    - name: Проверка модулей AppStream
      ansible.builtin.command: dnf module list
      register: module_list
      changed_when: false

  handlers:
    - name: Update dnf cache
      ansible.builtin.dnf:
        update_cache: yes
```

**Валидация:**

```bash
# Проверка установленных пакетов
rpm -qa | grep nginx
# → nginx-1.24.0-1.el9.x86_64

# Проверка модулей
dnf module list nodejs
# → Name        Streams        Profiles        Summary
# → nodejs     18 [d]         common [d]      Node.js JavaScript runtime

# Проверка versionlock
dnf versionlock list
# → kernel-*
# → glibc-*
# → systemd-*

# Проверка security-обновлений
dnf updateinfo list --security
# → CVE-2024-1086 Important/Security
```

### Сценарий 3: Security-hardened package management с compliance проверками

Установка пакетов с GPG-верификацией, HTTPS-репозиториями и последующей проверкой целостности.

```yaml
---
- name: Security-hardened package management
  hosts: all
  become: true
  vars:
    apt_repositories:
      - repo: "deb https://security.ubuntu.com/ubuntu noble-security main restricted universe multiverse"
        filename: "ubuntu-security"
        key_url: "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x871920D1991BC93C"
      - repo: "deb https://archive.ubuntu.com/ubuntu noble main restricted universe multiverse"
        filename: "ubuntu-main"
        key_url: "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x871920D1991BC93C"

    packages_to_install:
      - nginx
      - curl
      - fail2ban

  tasks:
    - name: Импорт GPG-ключей репозиториев (APT)
      ansible.builtin.apt_key:
        url: "{{ item.key_url }}"
        state: present
      loop: "{{ apt_repositories }}"

    - name: Добавление HTTPS-репозиториев
      ansible.builtin.apt_repository:
        repo: "{{ item.repo }}"
        filename: "{{ item.filename }}"
        state: present
        update_cache: yes
      loop: "{{ apt_repositories }}"

    - name: Установка пакетов с purging неиспользуемых зависимостей
      ansible.builtin.apt:
        name: "{{ packages_to_install }}"
        state: present
        autoremove: yes
        purge: yes
        update_cache: yes
        cache_valid_time: 3600

    - name: Установка debsums для проверки целостности
      ansible.builtin.apt:
        name: debsums
        state: present

    - name: Проверка контрольных сумм установленных пакетов
      ansible.builtin.command: debsums -s
      register: debsums_result
      changed_when: false
      failed_when: debsums_result.rc != 0 and debsums_result.stdout != ""
```

**Валидация:**

```bash
# Проверка подписей репозиториев
apt-cache policy nginx
# → 500 https://archive.ubuntu.com/ubuntu noble/main amd64 Packages
# → release a=noble,n/a=a=871920D1991BC93C

# Проверка контрольных сумм DEB пакетов
sudo debsums -s
# → (пустой вывод = все контрольные суммы совпадают)

# Проверка подписей пакетов
dpkg -V nginx
# → (пустой вывод = файлы не изменены)
```

### Сценарий 4: Пакетное обновление с change management

Применение обновлений в maintenance window с serial deployment, throttle и pre/post проверками.

```yaml
---
- name: Пакетное обновление с change management
  hosts: webservers
  become: true
  serial: 2
  throttle: 1
  vars:
    packages_to_update:
      - nginx
      - curl
    maintenance_window: "{{ ansible_date_time.iso8601 }}"
    rollback_dir: "/var/backups/package-rollback"

  pre_tasks:
    - name: Проверка maintenance window
      ansible.builtin.assert:
        that:
          - ansible_date_time.hour | int >= 2
          - ansible_date_time.hour | int < 4
        fail_msg: "Обновления разрешены только с 02:00 до 04:00"
        success_msg: "Maintenance window активирован"

    - name: Создание директории для отката
      ansible.builtin.file:
        path: "{{ rollback_dir }}"
        state: directory
        mode: '0750'

    - name: Сохранение списка установленных пакетов
      ansible.builtin.command: "{{ 'dpkg --get-selections' if ansible_facts['os_family'] == 'Debian' else 'rpm -qa' }} > {{ rollback_dir }}/packages-{{ ansible_date_time.date }}.txt"
      register: save_packages
      changed_when: save_packages.rc == 0

    - name: Создание LVM снапшота (если доступно)
      ansible.builtin.command: lvcreate --size 2G --snapshot --name pre-update-{{ ansible_date_time.date }} /dev/vg0/root
      register: lv_snapshot
      changed_when: "'created' in lv_snapshot.stdout"
      when: ansible_lvm.vgs.vg0 is defined

  tasks:
    - name: Обновление пакетов
      ansible.builtin.package:
        name: "{{ packages_to_update }}"
        state: latest
      register: update_result
      notify: Restart services

    - name: Проверка работоспособности после обновления
      ansible.builtin.uri:
        url: "http://localhost/health"
        status_code: 200
        timeout: 10
      register: health_check
      until: health_check.status == 200
      retries: 5
      delay: 10

    - name: Проверка целостности пакетов после обновления
      ansible.builtin.command: "{{ 'debsums -s' if ansible_facts['os_family'] == 'Debian' else 'rpm -V nginx curl' }}"
      register: integrity_check
      changed_when: false
      failed_when: integrity_check.rc != 0 and integrity_check.stdout != ""

  rescue:
    - name: Откат при ошибке обновления
      ansible.builtin.import_playbook: rollback_packages.yml

  always:
    - name: Уведомление об результате
      ansible.builtin.debug:
        msg: "Обновление завершено: changed={{ update_result.changed | default(false) }}, health={{ health_check.status | default('N/A') }}"
```

**Rollback playbook (`rollback_packages.yml`):**

```yaml
---
- name: Rollback packages
  hosts: all
  become: true
  vars:
    rollback_dir: "/var/backups/package-rollback"

  tasks:
    - name: Восстановление списка пакетов (Debian)
      ansible.builtin.command: dpkg --set-selections < {{ rollback_dir }}/packages-*.txt
      when: ansible_facts['os_family'] == 'Debian'

    - name: Восстановление RPM пакетов
      ansible.builtin.command: dnf downgrade $(cat {{ rollback_dir }}/packages-*.txt | tr '\n' ' ')
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Восстановление из LVM снапшота
      ansible.builtin.command: lvconvert --merge /dev/vg0/pre-update-{{ ansible_date_time.date }}
      when: ansible_lvm.vgs.vg0 is defined

    - name: Удаление снапшота
      ansible.builtin.command: lvremove /dev/vg0/pre-update-{{ ansible_date_time.date }} --force
      when: ansible_lvm.vgs.vg0 is defined
```

**Валидация:**

```bash
# Проверка maintenance window
ansible-playbook -i inventory.ini update_packages.yml
# → TASK [Проверка maintenance window]
# → ok: [web01] => {
# →     "msg": "Maintenance window активирован"
# → }

# Проверка обновленных пакетов
dpkg -l nginx
# → новая версия установлена

# Проверка целостности
debsums -s
# → (пустой вывод = целостность не нарушена)
```

### Сценарий 5: Локальный репозиторий APT с reprepro

Создание локального APT-репозитория с GPG-подписью и приоритетом через `deb822_repository`. Подробнее о теории репозиториев см. [Управление репозиториями пакетов в Linux](../../Linux/PackageManagement/Repository_Management/index.md).

```yaml
---
- name: Настройка локального репозитория APT
  hosts: repo_server
  become: true
  vars:
    repo_dir: "/srv/apt-repo"
    repo_dist: "noble"
    repo_components:
      - main
      - restricted
      - universe
      - multiverse

  tasks:
    - name: Установка утилит для репозитория
      ansible.builtin.package:
        name:
          - nginx
          - reprepro
          - dpkg-dev
          - gnupg
        state: present

    - name: Создание директории репозитория
      ansible.builtin.file:
        path: "{{ repo_dir }}"
        state: directory
        mode: '0755'

    - name: Инициализация репозитория
      ansible.builtin.command: reprepro -b {{ repo_dir }} create {{ repo_dist }}
      register: reprepro_init
      changed_when: "'Creating' in reprepro_init.stdout"

    - name: Добавление пакетов в репозиторий
      ansible.builtin.command: >
        reprepro -b {{ repo_dir }} includedeb {{ repo_dist }} {{ item }}
      loop: "{{ local_packages }}"
      register: reprepro_add
      changed_when: "'including' in reprepro_add.stdout"

    - name: Экспорт GPG-ключа для подписи репозитория
      ansible.builtin.command: gpg --armor --export {{ repo_gpg_key_id }}
      register: gpg_export
      changed_when: false

    - name: Создание конфигурации Nginx для репозитория
      ansible.builtin.copy:
        dest: /etc/nginx/sites-available/apt-repo
        content: |
          server {
              listen 80;
              server_name repo.internal;

              location / {
                  alias {{ repo_dir }}/;
                  autoindex on;
              }
          }
        mode: '0644'

    - name: Включение сайта Nginx
      ansible.builtin.file:
        src: /etc/nginx/sites-available/apt-repo
        dest: /etc/nginx/sites-enabled/apt-repo
        state: link
      notify: Reload Nginx

    - name: Добавление локального репозитория на клиенты через deb822
      ansible.builtin.deb822_repository:
        name: "local-{{ repo_dist }}"
        types: deb
        uris: "http://repo.internal/apt-repo/"
        suites: "{{ repo_dist }}"
        components: "{{ repo_components | join(' ') }}"
        signed_by: "http://repo.internal/apt-repo/dists/{{ repo_dist }}/InRelease"
        state: present
      delegate_to: "{{ item }}"
      loop: "{{ client_hosts }}"
```

**Использование клиентами:**

```bash
# Обновление кеша
sudo apt update

# Установка пакетов из локального репозитория
sudo apt install my-local-package
```

**Валидация:**

```bash
# Проверка репозитория на сервере
ls -la /srv/apt-repo/
# → conf/, db/, dists/, pool/

# Проверка подписей
reprepro -b /srv/apt-repo verify
# → (пустой вывод = контрольные суммы корректны)

# Проверка доступности
curl http://repo.internal/apt-repo/dists/noble/Release
# → показывает метаданные репозитория

# Проверка на клиенте
apt-cache policy my-local-package
# → my-local-package:
# →   100 http://repo.internal/apt-repo noble/main amd64 Packages
```

### Сценарий 6: Локальный репозиторий YUM/DNF с createrepo_c

Создание локального RPM-репозитория с GPG-подписью для изолированных сетей.

```yaml
---
- name: Настройка локального репозитория YUM/DNF
  hosts: repo_server
  become: true
  vars:
    repo_dir: "/srv/yum-repo"
    repo_name: "local-almalinux-9"
    gpg_key_id: "repository@company.local"

  tasks:
    - name: Установка утилит для репозитория
      ansible.builtin.package:
        name:
          - nginx
          - createrepo_c
          - rpm-sign
          - yum-utils
        state: present

    - name: Создание директории репозитория
      ansible.builtin.file:
        path: "{{ repo_dir }}"
        state: directory
        mode: '0755'

    - name: Копирование RPM пакетов
      ansible.builtin.copy:
        src: "{{ item }}"
        dest: "{{ repo_dir }}/"
        remote_src: yes
      loop: "{{ local_rpm_packages }}"

    - name: Создание метаданных репозитория (createrepo_c)
      ansible.builtin.command: createrepo_c --database --zmetadata {{ repo_dir }}
      register: createrepo_result
      changed_when: "'Completed' in createrepo_result.stdout"

    - name: Подпись репозитория GPG
      ansible.builtin.command: gpg --detach-sign --armor {{ repo_dir }}/repodata/repomd.xml
      register: gpg_sign
      changed_when: "'created' in gpg_sign.stdout"

    - name: Создание конфигурации репозитория
      ansible.builtin.copy:
        dest: /etc/yum.repos.d/local.repo
        content: |
          [{{ repo_name }}]
          name={{ repo_name }}
          baseurl=http://repo.internal/yum-repo/
          enabled=1
          gpgcheck=1
          gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-local
        mode: '0644'

    - name: Создание конфигурации Nginx для репозитория
      ansible.builtin.copy:
        dest: /etc/nginx/sites-available/yum-repo
        content: |
          server {
              listen 80;
              server_name repo.internal;

              location / {
                  alias {{ repo_dir }}/;
                  autoindex on;
              }
          }
        mode: '0644'

    - name: Включение сайта Nginx
      ansible.builtin.file:
        src: /etc/nginx/sites-available/yum-repo
        dest: /etc/nginx/sites-enabled/yum-repo
        state: link
      notify: Reload Nginx

    - name: Добавление локального репозитория на клиенты
      ansible.builtin.dnf_repository:
        name: "{{ repo_name }}"
        description: "Local {{ repo_name }}"
        baseurl: "http://repo.internal/yum-repo/"
        enabled: yes
        gpgcheck: yes
        gpgkey: "http://repo.internal/yum-repo/repodata/repomd.xml.key"
        state: present
      delegate_to: "{{ item }}"
      loop: "{{ client_hosts }}"

  handlers:
    - name: Reload Nginx
      ansible.builtin.systemd:
        name: nginx
        state: reloaded
```

**Использование клиентами:**

```bash
# Очистка кеша
sudo dnf clean all

# Установка пакетов из локального репозитория
sudo dnf install my-local-package

# Проверка репозитория
dnf repolist
# → local-almalinux-9 | 1.2 kB 00:00
```

**Валидация:**

```bash
# Проверка репозитория на сервере
ls -la /srv/yum-repo/
# → repodata/, *.rpm

# Проверка подписей
gpg --verify /srv/yum-repo/repodata/repomd.xml.asc
# → Good signature from "Repository Key"

# Проверка доступности
curl http://repo.internal/yum-repo/repodata/repomd.xml
# → возвращает метаданные репозитория
```

### Сценарий 7: Пакетное обновление с откатом через block/rescue

Атомарное обновление с автоматическим откатом при ошибке. Для кроссплатформенных паттернов отката см. [Кроссплатформенный откат и drift detection](../CrossPlatform/ansible_cross_platform_rollback_testing_drift.md).

```yaml
---
- name: Обновление пакетов с возможностью отката
  hosts: all
  become: true
  vars:
    packages_to_update:
      - nginx
      - curl
    rollback_dir: "/var/backups/package-rollback"

  tasks:
    - name: Создание директории для отката
      ansible.builtin.file:
        path: "{{ rollback_dir }}"
        state: directory
        mode: '0750'

    - name: Сохранение списка установленных пакетов
      ansible.builtin.command: "{{ 'dpkg --get-selections' if ansible_facts['os_family'] == 'Debian' else 'rpm -qa' }} > {{ rollback_dir }}/packages-{{ ansible_date_time.date }}.txt"
      register: save_selections
      changed_when: save_selections.rc == 0

    - name: Создание снапшота перед обновлением
      ansible.builtin.command: lvcreate --size 1G --snapshot --name pre-update-snap /dev/vg0/root
      register: lv_snapshot
      changed_when: "'created' in lv_snapshot.stdout"
      when: ansible_lvm.vgs.vg0 is defined

    - name: Атомарное обновление пакетов
      block:
        - name: Обновление пакетов
          ansible.builtin.package:
            name: "{{ packages_to_update }}"
            state: latest
          register: update_result

        - name: Проверка работоспособности после обновления
          ansible.builtin.uri:
            url: http://localhost/health
            status_code: 200
            timeout: 10
          register: health_check
          until: health_check.status == 200
          retries: 5
          delay: 10

      rescue:
        - name: Откат: восстановление пакетов (Debian)
          ansible.builtin.command: dpkg --set-selections < {{ rollback_dir }}/packages-*.txt
          when: ansible_facts['os_family'] == 'Debian'

        - name: Откат: downgrade пакетов (RedHat)
          ansible.builtin.command: dnf downgrade $(cat {{ rollback_dir }}/packages-*.txt | tr '\n' ' ')
          when: ansible_facts['os_family'] == 'RedHat'

        - name: Откат: восстановление из LVM снапшота
          ansible.builtin.command: lvconvert --merge /dev/vg0/pre-update-snap
          when: ansible_lvm.vgs.vg0 is defined

        - name: Откат: перезагрузка
          ansible.builtin.reboot:
            reboot_timeout: 300
          when: ansible_lvm.vgs.vg0 is defined

      always:
        - name: Удаление снапшота
          ansible.builtin.command: lvremove /dev/vg0/pre-update-snap --force
          when: ansible_lvm.vgs.vg0 is defined and lv_snapshot is changed

        - name: Уведомление об ошибке
          ansible.builtin.debug:
            msg: "Обновление завершилось с ошибкой, выполнен откат"
          when: update_result is failed
```

**Валидация:**

```bash
# Запуск обновления с возможностью отката
ansible-playbook -i inventory.ini update_with_rollback.yml

# Проверка списка пакетов
dpkg -l nginx
# → новая версия установлена

# В случае ошибки:
# → автоматически запускается rescue-блок
# → пакеты возвращаются к предыдущим версиям
```

### Сценарий 8: Пакетный аудит и compliance проверки

Регулярная проверка целостности пакетов и compliance с desired state через Ansible drift detection.

```yaml
---
- name: Пакетный аудит и compliance проверки
  hosts: all
  become: true
  vars:
    audit_dir: "/var/log/package-audit"
    expected_packages:
      - nginx
      - curl
      - fail2ban
    blocked_packages:
      - telnet
      - rsh
      - rlogin

  tasks:
    - name: Создание директории для аудита
      ansible.builtin.file:
        path: "{{ audit_dir }}"
        state: directory
        mode: '0750'

    - name: Проверка установленных ожидаемых пакетов
      ansible.builtin.package:
        name: "{{ expected_packages }}"
        state: present
      register: expected_check

    - name: Удаление заблокированных пакетов
      ansible.builtin.package:
        name: "{{ blocked_packages }}"
        state: absent
      register: blocked_check

    - name: Верификация целостности пакетов (Debian/Ubuntu)
      ansible.builtin.command: debsums -s
      register: debsums_result
      changed_when: false
      when: ansible_facts['os_family'] == 'Debian'

    - name: Верификация целостности пакетов (RHEL/AlmaLinux/Rocky)
      ansible.builtin.command: rpm -Va
      register: rpm_verify
      changed_when: false
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Проверка versionlock/hold
      ansible.builtin.command: "{{ 'apt-mark showhold' if ansible_facts['os_family'] == 'Debian' else 'dnf versionlock list' }}"
      register: lock_check
      changed_when: false

    - name: Сохранение отчета аудита
      ansible.builtin.copy:
        dest: "{{ audit_dir }}/audit-{{ ansible_date_time.date }}.txt"
        content: |
          Date: {{ ansible_date_time.iso8601 }}
          Host: {{ inventory_hostname }}
          Expected packages: {{ expected_packages }}
          Blocked packages: {{ blocked_packages }}
          Integrity check: {{ (debsums_result.stdout if ansible_facts['os_family'] == 'Debian' else rpm_verify.stdout) | default('N/A') }}
          Lock status: {{ lock_check.stdout }}
        mode: '0640'
```

**Валидация:**

```bash
# Проверка compliance
ansible-playbook -i inventory.ini package_audit.yml

# Проверка отчета
cat /var/log/package-audit/audit-2026-09-26.txt
# → Date: 2026-09-26T...
# → Host: web01
# → Expected packages: ['nginx', 'curl', 'fail2ban']
# → Blocked packages: ['telnet', 'rsh']
# → Integrity check: (пустой вывод = OK)
# → Lock status: kernel-*
```

## Операции и команды

### Основные команды для управления пакетами

| Команда | Назначение | Пример |
|---|---|---|
| `apt install <package>` | Установка пакета | `apt install nginx=1.24.0-1ubuntu3` |
| `apt-mark hold <package>` | Удержание пакета | `apt-mark hold linux-image-generic` |
| `apt-mark unhold <package>` | Снятие удержания | `apt-mark unhold linux-image-generic` |
| `apt-cache policy <package>` | Проверка доступных версий | `apt-cache policy nginx` |
| `apt list --upgradable` | Список обновляемых пакетов | `apt list --upgradable` |
| `dnf install <package>` | Установка пакета | `dnf install nginx` |
| `dnf module enable <module>:<stream>` | Включение модуля | `dnf module enable nodejs:18` |
| `dnf versionlock add <package>` | Блокировка версии | `dnf versionlock add kernel` |
| `dnf versionlock list` | Список заблокированных | `dnf versionlock list` |
| `dnf updateinfo list --security` | Security-обновления | `dnf updateinfo list --security` |
| `yum downgrade <package>` | Откат пакета | `yum downgrade nginx-1.23.0` |
| `dnf downgrade <package>` | Откат пакета (DNF4/DNF5) | `dnf downgrade nginx-1.23.0` |
| `rpm -qa` | Список установленных пакетов | `rpm -qa \| grep nginx` |
| `rpm -V <package>` | Верификация пакета | `rpm -V nginx` |
| `rpm -Va` | Верификация всех пакетов | `rpm -Va` |
| `createrepo_c <directory>` | Создание RPM-репозитория | `createrepo_c /srv/yum-repo` |
| `reprepro includedeb <dist> <package>` | Добавление пакета в APT репозиторий | `reprepro -b /srv/apt-repo includedeb noble package.deb` |
| `zypper install <package>` | Установка пакета (SUSE) | `zypper install nginx` |
| `zypper patch` | Установка патчей (SUSE) | `zypper patch` |
| `apk add <package>` | Установка пакета (Alpine) | `apk add nginx` |
| `debsums -s` | Проверка контрольных сумм DEB | `debsums -s` |

### Команды для проверки пакетов

| Команда | Назначение | Пример |
|---|---|---|
| `dpkg -l <package>` | Проверка установленного пакета | `dpkg -l nginx` |
| `dpkg -s <package>` | Детальная информация о пакете | `dpkg -s nginx` |
| `dpkg-query -W -f='${Package} ${Version}\n'` | Список пакетов с версиями | `dpkg-query -W -f='${Package} ${Version}\n'` |
| `rpm -q <package>` | Проверка установленного пакета RPM | `rpm -q nginx` |
| `rpm -qi <package>` | Детальная информация о пакете | `rpm -qi nginx` |
| `apt-cache show <package>` | Информация о пакете | `apt-cache show nginx` |
| `dnf info <package>` | Информация о пакете | `dnf info nginx` |
| `dnf module list` | Список модулей AppStream | `dnf module list nodejs` |
| `dnf history` | История транзакций | `dnf history` |
| `dnf history undo <id>` | Откат транзакции | `dnf history undo 5` |
| `apk info -v <package>` | Информация о пакете (Alpine) | `apk info -v nginx` |
| `zypper info <package>` | Информация о пакете (SUSE) | `zypper info nginx` |

## Устранение типичных неполадок

| Ошибка | Причина | Решение |
|---|---|---|
| `Package not found` | Пакет не найден в репозиториях | Проверьте `apt-cache search <package>`, добавьте репозиторий, обновите кеш |
| `Dependency conflict` | Конфликт зависимостей | Используйте `apt-cache policy <package>`, `dnf deplist <package>`, разрешите вручную |
| `Hold not working` | Пакет обновляется несмотря на hold | Проверьте `apt-mark showhold`, убедитесь в правильности команды |
| `Versionlock not working` | Пакет обновляется несмотря на versionlock | Проверьте `dnf versionlock list`, убедитесь что установлен `dnf-plugin-versionlock` |
| `Repository unreachable` | Репозиторий недоступен | Проверьте сеть, DNS, firewall, proxy |
| `Signature verification failed` | Ошибка проверки подписи | Импортируйте GPG ключ: `apt-key add <key>` или `rpm --import <key>` |
| `Downgrade not allowed` | Запрет понижения версии | Используйте `allow_downgrade: yes` в Ansible или `dnf downgrade` |
| `Local repository empty` | Пакеты не добавлены в репозиторий | Проверьте `reprepro list` или `createrepo_c --update` |
| `Package verification failed` | Файлы пакета изменены | Проверьте журналы изменений, переустановите пакет, проверьте целостность системы |
| `DNF5 parameter not supported` | Используется параметр DNF4 в DNF5 | Перейдите на `ansible.builtin.dnf5` или используйте `use_backend: dnf` для DNF4 |
| `Module stream not found` | Поток модуля не существует | Проверьте `dnf module list`, выберите доступный stream |
| `Lock timeout` | Блокировка пакетного менеджера | Увеличьте `lock_timeout` в `apt`, используйте `retries` и `delay` в задачах Ansible |

## Рекомендации

### Best Practices

1. **Version pinning** — фиксируйте версии критичных пакетов через `pkg=version` (APT), `pkg-version` (DNF) или `versionlock`/`hold`.
2. **Security repositories** — используйте security-репозитории с `gpgcheck=1` и HTTPS.
3. **Change management** — применяйте обновления через maintenance windows с `serial` и `throttle`.
4. **Local repositories** — используйте локальные репозитории для изолированных сред.
5. **Verification** — после обновления проверяйте целостность пакетов (`rpm -V`, `debsums`) и работоспособность сервисов.
6. **Audit** — все изменения фиксируются в Git, ведется журнал пакетных изменений.
7. **Rollback readiness** — всегда имейте подготовленный план отката: snapshot ЛВМ, сохраненный список пакетов, rollback playbook.
8. **Dependency management** — контролируйте разрешение зависимостей, используйте `autoremove: yes` и `purge: yes` для очистки.
9. **Testing** — тестируйте обновления пакетов на staging перед production.
10. **Documentation** — документируйте, какие пакеты закреплены и почему.

### Чек-лист валидации после настройки

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Пакет установлен | `dpkg -l <package>` или `rpm -q <package>` | Пакет установлен нужной версии |
| Версия пакета | `dpkg -l <package>` или `rpm -q <package>` | Правильная версия установлена |
| Hold работает | `apt-mark showhold` | Пакет в списке hold |
| Versionlock работает | `dnf versionlock list` | Пакет в списке заблокированных |
| Репозиторий доступен | `curl http://repo.internal/` | Репозиторий отвечает |
| Подпись репозитория | `apt-cache policy <package>` / `rpm -qi <package>` | Подпись проверена |
| Зависимости разрешены | `apt install <package>` / `dnf install <package>` | Без ошибок зависимостей |
| Локальный репозиторий | `apt-cache policy <package>` / `dnf repolist` | Пакет доступен из локального репозитория |
| Целостность пакетов | `debsums -s` / `rpm -V <package>` | Контрольные суммы совпадают |
| Обновления кеша | `apt list --upgradable` / `dnf check-update` | Список обновлений корректен |

## Дополнительная информация

### Смотрите также

- **[Ansible: Модули управления пакетами](../Modules/ansible_package_management_modules.md)** — полный справочник модулей (`apt`, `dnf`, `dnf5`, `package`, `zypper`, `apk`), возвращаемые значения, идемпотентность, параметры `state`.
- **[Ansible: Управление обновлениями (Patch Management)](../ansible_patch_management.md)** — стратегии rolling update, maintenance windows, security-обновления, Kernel Livepatching.
- **[Управление репозиториями пакетов в Linux](../../Linux/PackageManagement/Repository_Management/index.md)** — теория и практика управления репозиториями APT, DNF, reprepro, createrepo_c, GPG.

### Интеграция с другими системами

| Система | Назначение | Интеграция |
|---|---|---|
| **APT/YUM/DNF/Zypper/Apk** | Управление пакетами | Ansible package modules |
| **Ansible Galaxy** | Роли для управления пакетами | `geerlingguy.nginx`, `geerlingguy.docker`, `geerlingguy.postgresql` |
| **Nexus / Artifactory / Verdaccio** | Локальные репозитории | Хранение пакетов, проксирование внешних репозиториев |
| **Jenkins / GitLab CI** | Автоматическое обновление | CI/CD pipelines с maintenance windows |
| **Prometheus / Grafana** | Мониторинг | Метрики обновлений, compliance, целостности пакетов |
| **ELK / Loki** | Логирование | Аудит пакетных изменений, drift detection |
| **SIEM** | Security monitoring | Интеграция `rpm -Va` / `debsums -s` в корпоративные SIEM |

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Конфликт зависимостей | Пакет не может быть установлен | Используйте `allow_downgrade`, разрешите вручную через `apt-cache policy` / `dnf deplist` |
| Пакет удерживается, но обновляется | Hold/versionlock не работает | Проверьте `apt-mark showhold` / `dnf versionlock list`, убедитесь в правильности команды |
| Локальный репозиторий не синхронизируется | Пакеты устарели | Используйте `reprepro --update` или `createrepo_c --update`, настройте cron/systemd timer |
| Откат пакета невозможен | Зависимости сломаны | Используйте снапшоты ЛВМ или восстановление из бэкапа списка пакетов |
| Большое количество пакетов | Долгое обновление | Используйте `--no-install-recommends`, параллельные обновления с `serial`/`throttle` |
| DNF5 параметр не поддерживается | Перенос с DNF4 на DNF5 | Используйте `ansible.builtin.dnf5` вместо `dnf`, настройте `use_backend` или конфигурационные файлы `.repo` |
| Пакеты изменены после установки | Compromised integrity | Переустановите пакет, проверьте журналы, проведите forensic анализ через `rpm -Va` / `debsums -s` |
| Контейнер перезаписывает iptables | Docker/Podman перезаписывает правила | Используйте `DOCKER-USER` chain (iptables) или кастомные nftables-таблицы с приоритетом выше Docker |
| Maintenance window превышен | Обновление затягивается | Используйте `serial`, `throttle`, `async` + `poll: 0`, pre-staging пакетов |
