# SELinux (Security-Enhanced Linux)

## Определения и терминология

**SELinux (Security-Enhanced Linux)** — механизм принудительного контроля доступа (Mandatory Access Control, MAC) в ядре Linux, разработанный **АНБ (NSA)** и представленный в 2001 году. Это комплексная система безопасности, реализующая мандатное управление и ролевую модель (RBAC) на уровне ядра.

В архитектуре безопасности SELinux выступает в роли «надзирателя», чьи политики приоритетнее привилегий пользователя `root`. Даже обладая UID 0, субъект не может совершить действие, не разрешенное централизованной политикой безопасности.

**Проблема DAC:** стандартные права Linux (`rwx`) основаны на дискреционной модели — доступ определяется владельцем объекта. Это не защищает от вредоносного ПО, запущенного от имени пользователя, или процессов с повышенными привилегиями.

**Принцип MAC:** политики определяются централизованно администратором и применяются на уровне ядра через фреймворк **LSM (Linux Security Modules)**. Процесс с меткой «веб-сервер» не сможет читать файлы с меткой «документы_пользователей», даже если запущен от имени `root`.

### Ключевые термины

| Термин | Описание |
| :--- | :--- |
| **MAC (Mandatory Access Control)** | Мандатное управление доступом, политики определяются централизованно |
| **DAC (Discretionary Access Control)** | Дискреционное управление доступом, правами управляет владелец файла |
| **LSM (Linux Security Modules)** | Фреймворк в ядре Linux для реализации MAC. SELinux построен на базе LSM |
| **Контекст безопасности** | Метка в формате `user:role:type:level` в расширенных атрибутах файлов |
| **AppArmor** | Альтернативный LSM-модуль. Основан на **путях**, а не метках |

### Компоненты контекста безопасности

| Компонент | Описание | Пример |
| :--- | :--- | :--- |
| **User** | Пользователь SELinux (не UID ОС) | `system_u`, `unconfined_u` |
| **Role** | Роль, определяющая доступные домены (RBAC) | `system_r`, `object_r` |
| **Type/Domain** | Тип для объектов, домен для процессов (основа защиты) | `httpd_t`, `httpd_sys_content_t` |
| **Level** | Уровень чувствительности и категории (MLS/MCS) | `s0`, `s0:c0.c1023` |

### Типы политик

| Тип | Описание | Применение |
| :--- | :--- | :--- |
| **TE (Type Enforcement)** | Основной механизм. Связывает типы процессов и объектов | Базовый контроль доступа |
| **RBAC** | Управление доступом на основе ролей | Ограничение ролей пользователей |
| **MLS (Multi-Level Security)** | Иерархические уровни: «совершенно секретно» > «секретно» | Военные, госсектор |
| **MCS (Multi-Category Security)** | Неиерархические категории: «проект А», «проект Б» | Изоляция контейнеров, мультитенант |

#### Type Enforcement (TE) — детализация

| Компонент | Описание | Пример |
| :--- | :--- | :--- |
| **Типизация объектов** | Файлы, сокеты, устройства получают тип | `httpd_sys_content_t`, `shadow_t` |
| **Типизация процессов** | Процессы работают в доменах (типах) | `httpd_t`, `sshd_t` |
| **Правила доступа** | Политика определяет разрешённые операции между типами | `httpd_t` читает `httpd_sys_content_t` |
| **Блокировка ядром** | Нарушения блокируются на уровне ядра | Даже процесс от `root` будет заблокирован |

### История и эволюция

| Этап | Год | Событие |
| :--- | :--- | :--- |
| **Flask architecture** | 1998–2000 | Исследовательский проект НАСБ / Utah University, доказавший viability меток на уровне ОС. |
| **SELinux integration** | 2003 | Включение в ядро Linux 2.6 (patch от НСБ). |
| **RHEL 4** | 2005 | Первое массовое внедрение SELinux в дистрибутив Enterprise (policy `targeted`). |
| **CIL (Common Intermediate Language)** | 2012+ | Введение промежуточного языка для модульности и ускорения сборки политик. |
| **SELinux в Android** | 2017 (Android 8.0+) | Mandatory включение SELinux enforcing для всех приложений и процессов. |
| **RHEL 9/10** | 2022–2025 | Transition на `system_u` как системный пользователь, расширение MCS для мультитенантности, deprecation некоторых устаревших булевых. |

### Архитектура ядра (Flask + LSM)

Ядро Linux реализует SELinux через несколько компонентов:

| Компонент | Назначение |
| :--- | :--- |
| **LSM hooks** | Точки внедрения в критических операциях ядра (открытие файла, подключение к сокету, загрузка модуля). SELinux регистрирует callback-функции через LSM. |
| **Security Server** | Центральный компонент, принимающий запросы от LSM hooks и возвращающий решение (allow / deny). Работает в контексте ядра. |
| **AVC (Access Vector Cache)** | Кэш решений Security Server в оперативной памяти. Хранит последние N решений для быстрого разрешения типовых операций без повторной проверки политики. |
| **Kernel Object Manager** | Управление объектами ядра (процессы, файлы, сокеты, сообщения) и их контекстами безопасности. |

**Порядок проверки:**
1. Процесс (субъект с контекстом `user:role:type:level`) обращается к объекту (файл, порт, сокет).
2. LSM hook вызывает AVC.
3. AVC ищет решение в кэше.
4. При промахе — запрос уходит в Security Server.
5. Security Server сопоставляет контексты с полной базой политик (бинарный blob).
6. Решение кэшируется и применяется.

### Распространённые политики

| Политика | Описание | Где используется |
| :--- | :--- | :--- |
| **targeted** | Защищает только сетевые демоны и критичные процессы; пользовательские процессы работают в `unconfined_t`. | RHEL/CentOS/Fedora (по умолчанию). |
| **mls** | Полная MLS-политика с иерархическими уровнями. | Военные, госсектор, критичная инфраструктура. |
| **strict** | Каждый процесс и файл типизирован; `unconfined_t` отсутствует. | Специальные сценарии максимальной изоляции. |
| **minimum** | Минимальный набор правил (обычно для embedded). | Embedded / кастомные сборки. |

---

## Основные концепции

### Схема работы и AVC

1.  **Субъект** (процесс с контекстом) пытается получить доступ к **объекту** (файл, порт с контекстом).
2.  Ядро проверяет **AVC (Access Vector Cache)** — кэш предыдущих решений.
3.  Если решения нет в кэше, запрос отправляется в **Security Server** для проверки по полной базе политик.
4.  На основе сопоставления контекстов — **разрешает** или **запрещает** доступ.
5.  Все действия протоколируются (события AVC denied).

### Режимы работы

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **Enforcing** | Политики активно применяются, нарушения блокируются | Производственная среда |
| **Permissive** | Нарушения только логируются, доступ не блокируется | Отладка, обучение системы |
| **Disabled** | SELinux полностью выключен в ядре | Не рекомендуется; требует перезагрузки |

### Архитектура и языки политик (2025–2026)

Современный SELinux (RHEL 9/10, Android) использует промежуточный язык для обеспечения модульности и производительности:
*   **CIL (Common Intermediate Language):** Промежуточный язык (S-expressions), который поддерживает **namespaces** (пространства имен) и **blocks**. Это позволяет разным вендорам поставлять модули без риска коллизий имен типов.
*   **Compilation Flow:** Высокоуровневые `.te` файлы компилируются в CIL, который затем преобразуется в бинарную политику ядра. Это делает пересборку политик в 10–12 раз быстрее по сравнению с RHEL 8.

---

## Практические сценарии

### 1. Установка и включение

На RHEL/CentOS/Rocky/Alma/Fedora SELinux включён по умолчанию. На Debian/Ubuntu требуется ручная установка.

**RHEL/Rocky/Alma/Fedora:**
```bash
# Проверка наличия пакетов
rpm -q policycoreutils setools-console setroubleshoot-server audit

# Если пакеты отсутствуют
sudo dnf install policycoreutils setools-console setroubleshoot-server audit

# Проверка статуса
sestatus
# → SELinux status:                 enabled
# → SELinuxfs mount:                /sys/fs/selinux
# → SELinux root directory:         /etc/selinux
# → Loaded policy name:             targeted
# → Current mode:                   enforcing
# → Mode from config file:          enforcing
# → Policy MLS status:              enabled
# → Policy deny_unknown status:     allowed
```

**Debian/Ubuntu:**
```bash
sudo apt install policycoreutils selinux-utils selinux-basics
sudo selinux-activate
# Перезагрузка обязательна
sudo reboot
```

**Включение SELinux при текущем статусе `Disabled`:**

Переход из `disabled` в `enforcing` требует двухэтапного процесса (reboot между этапами):

```bash
# Этап 1: Переключение в permissive
sudo sed -i 's/^SELINUX=.*/SELINUX=permissive/' /etc/selinux/config

# Перезагрузка
sudo reboot

# Этап 2: Проверка логов на предмет отказов, затем включение enforcing
sudo grep "AVC" /var/log/audit/audit.log | audit2why

# Включение enforcing
sudo sed -i 's/^SELINUX=.*/SELINUX=enforcing/' /etc/selinux/config
sudo setenforce 1
```

**Отключение SELinux (не рекомендуется):**
```bash
# Временное (до перезагрузки)
sudo setenforce 0

# Постоянное
sudo sed -i 's/^SELINUX=.*/SELINUX=disabled/' /etc/selinux/config
# Перезагрузка
```

### 2. Проверка статуса и управление режимами

```bash
# Проверка текущего статуса
sestatus
getenforce

# Временное переключение (до перезагрузки)
sudo setenforce 0  # Permissive
sudo setenforce 1  # Enforcing

# Постоянное изменение: /etc/selinux/config
SELINUX=enforcing
```

### 3. Просмотр контекстов

```bash
# Файлы и каталоги
ls -Z /var/www/html

# Процессы
ps -Z aux | grep nginx
```

### 4. Управление пользователями, ролями, типами

```bash
# Соответствие системных пользователей пользователям SELinux
semanage login -l

# Привязка пользователя к SELinux-пользователю
sudo semanage login -a -s staff_u user1

# Просмотр пользователей SELinux
semanage user -l

# Просмотр ролей и типов
semanage role -l
seinfo -t
```

### 5. Переходы доменов (Domain Transitions)

Когда один процесс запускает другой, SELinux может разрешить или запретить переход в другой домен.

```bash
# Просмотр разрешённых переходов доменов для httpd_t
sesearch -T -s httpd_t
```

### 6. Управление портами

```bash
# Разрешенные порты для типа http_port_t
semanage port -l | grep http_port_t

# Добавление нового порта
sudo semanage port -a -t http_port_t -p tcp 8081
```

### 7. Управление файловыми контекстами

При **перемещении** (`mv`) файл сохраняет старую метку. При **копировании** (`cp`) — наследует метку целевой директории.

```bash
# Добавление правила для нового каталога (постоянно)
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/my_app(/.*)?"

# Восстановление контекста по умолчанию
sudo restorecon -Rv /srv/my_app

# Временное изменение контекста (сбросится при restorecon)
sudo chcon -t httpd_sys_content_t /srv/my_app/index.html
```

### 8. Управление булевыми значениями (Booleans)

```bash
# Просмотр всех значений
getsebool -a

# Постоянное включение
sudo setsebool -P httpd_can_network_connect on
```

### 9. Справочник булевых значений (Booleans) для распространённых сервисов

| Boolean | Описание | Значение по умолчанию | Рекомендация |
| :--- | :--- | :--- | :--- |
| `httpd_can_network_connect` | Веб-сервер может открывать исходящие соединения | `off` | `on` для бэкендов, API |
| `httpd_can_network_connect_db` | Веб-сервер может подключаться к БД на удалённых хостах | `off` | `on` для БД на отдельном сервере |
| `httpd_enable_homedirs` | Доступ Apache к домашним директориям пользователей | `off` | `on` для userdir |
| `httpd_read_user_content` | Чтение контента пользователей через `~username` | `off` | `on` для userdir |
| `httpd_tmp_exec` | Разрешение на выполнение бинарников из `/tmp` | `off` | `off` (оставить) |
| `httpd_unified` | Объединённый домен для httpd (упрощает отладку) | `off` | `off` в production |
| `mysql_connect_any` | MySQL может подключаться к любым сетевым ресурсам | `off` | `on` если нужны внешние UDF |
| `named_write_master_zones` | BIND может записывать в master-зоны | `off` | `on` для dynamic updates |
| `ntpd_sync_clock` | NTP может синхронизировать аппаратные часы | `off` | `on` для серверов времени |
| `proftpd_connect_db` | ProFTPD может подключаться к БД | `off` | `on` при использовании SQL |
| `samba_enable_home_dirs` | Доступ Samba к домашним директориям | `off` | `on` для файлового сервера |
| `samba_export_all_rw` | Samba экспортирует все разделы на запись | `off` | `on` для общего доступа |
| `samba_share_all_rw` | Samba имеет запись во все общие ресурсы | `off` | `on` для общего доступа |
| `ssh_sysadm_login` | Разрешить системным администраторам вход по SSH | `off` | `on` только для доверенных терминалов |
| `ftpd_full_access` | FTP-сервер имеет полный доступ к файловой системе | `off` | `on` для анонимного FTP |
| `ftpd_use_passive_mode` | FTP использует пассивный режим | `on` | `on` за NAT |
| `allow_httpd_awstats_script_anon_write` | AWStats может записывать данные | `off` | `on` для веб-статистики |
| `allow_httpd_mod_php_anon_write` | PHP-модуль Apache может записывать | `off` | `on` для загрузки файлов |
| `allow_httpd_sys_script_anon_write` | Скрипты CGI могут записывать | `off` | `on` для upload-скриптов |
| `daemons_dump_core` | Демоны могут создавать core dumps | `off` | `off` в production |
| `domain_kernel_loadable_modules` | Процессы могут загружать модули ядра | `off` | `on` для DKMS/NVIDIA |
| `tcp_network_connect` | Процессы могут подключаться к TCP-портам | `on` | `on` по умолчанию |

**Применение всех булевых:**
```bash
# Постоянное применение
sudo setsebool -P httpd_can_network_connect on
sudo setsebool -P httpd_can_network_connect_db on

# Пакетное применение через Ansible
ansible web_servers -b -m seboolean -a "name=httpd_can_network_connect state=true persistent=true"
```

### 10. Специфичные правила для сервисов

#### 9.1 SSH (sshd)

```bash
# Проверка контекста ключей
ls -Z /home/user/.ssh
# → system_u:object_r:ssh_home_t:s0 authorized_keys

# Восстановление контекста
sudo restorecon -Rv /home/user/.ssh

# Если SELinux блокирует вход
sudo ausearch -m avc -ts recent | grep sshd
sudo grep "AVC" /var/log/audit/audit.log | audit2allow -M ssh_fix
sudo semodule -i ssh_fix.pp
```

#### 9.2 Nginx / Apache

```bash
# Проверка контекста веб-контента
ls -Z /var/www/html
# → system_u:object_r:httpd_sys_content_t:s0 index.html

# Разрешение сетевых соединений
sudo setsebool -P httpd_can_network_connect on
sudo setsebool -P httpd_can_network_connect_db on

# Разрешение чтения домашних директорий (если нужно)
sudo setsebool -P httpd_enable_homedirs on

# Нестандартный порт
sudo semanage port -a -t http_port_t -p tcp 8080
```

#### 9.3 PostgreSQL / MySQL

```bash
# PostgreSQL: доступ к файлам данных
sudo semanage fcontext -a -t postgresql_db_t "/var/lib/pgsql(/.*)?"
sudo restorecon -Rv /var/lib/pgsql

# PostgreSQL: сетевые соединения
sudo setsebool -P postgresql_can_rsync on  # для репликации
sudo setsebool -P postgresql_connect_any on  # для FDW

# MySQL: порт
sudo semanage port -a -t mysqld_port_t -p tcp 3307

# Проверка AVC отказов
sudo ausearch -m avc -ts recent | grep -E "postgres|mysqld"
```

#### 9.4 BIND (DNS)

```bash
# Разрешение записи в master-зоны
sudo setsebool -P named_write_master_zones on

# Разрешение записи в кэш (для динамических обновлений)
sudo setsebool -P named_write_cache on

# Нестандартный порт
sudo semanage port -a -t dns_port_t -p tcp 5353
```

#### 9.5 NFS

```bash
# Экспорт директории
sudo semanage fcontext -a -t nfs_t "/srv/nfs/shared(/.*)?"
sudo restorecon -Rv /srv/nfs/shared

# Разрешение NFS-серверу на чтение/запись
sudo setsebool -P nfs_export_all_rw on
sudo setsebool -P nfs_export_all_ro on
```

#### 9.6 Samba

```bash
# Общий доступ на запись
sudo setsebool -P samba_export_all_rw on
sudo setsebool -P samba_share_all_rw on

# Контекст общей директории
sudo semanage fcontext -a -t samba_share_t "/srv/samba/data(/.*)?"
sudo restorecon -Rv /srv/samba/data
```

### 11. Управление модулями политик (Policy Modules)

Вместо изменения stock-политики создавайте отдельные модули:

```bash
# 1. Собрать AVC-отказы за период
sudo ausearch -m avc --start recent --end now -i > /tmp/avc.txt

# 2. Сгенерировать модуль (.te файл + Makefile)
sudo ausearch -m avc -ts recent | audit2allow -m my_app > my_app.te

# 3. Проверить сгенерированный .te файл
cat my_app.te
# → module my_app 1.0;
# → require { type unconfined_t; class file { read open }; }
# → allow unconfined_t httpd_sys_content_t:file { read open };

# 4. Скомпилировать и установить
sudo make -f /usr/share/selinux/devel/Makefile my_app.pp
sudo semodule -i my_app.pp

# 5. Проверить установку
sudo semodule -l | grep my_app
# → my_app 1.4
```

**Важно:** Всегда проверяйте сгенерированные `.te` файлы перед установкой. `audit2allow -M` создаёт модуль с `allow` правилами, но может потребоваться ручная корректировка (например, использование `type_transition` вместо `allow`).

**Просмотр установленных модулей:**
```bash
sudo semodule -l | less
sudo semodule -l | grep -i httpd
```

**Удаление модуля:**
```bash
sudo semodule -r my_app
```

### 12. Разработка кастомной политики (CIL)

Для сложных сценариев можно работать напрямую с CIL:

```bash
# Создание CIL-файла
cat > /tmp/my_cil.cil << 'EOF'
(block my_app
  (blockinherit httpd_content)
  (allow my_app_t my_data_t (file (read open)))
)
EOF

# Установка CIL-политики
sudo semodule -i /tmp/my_cil.cil

# Просмотр CIL-содержимого установленной политики
sudo sedinfo | head -50
```

### 13. Аудит событий через auditd

```bash
# /etc/audit/rules.d/99-selinux-audit.rules

# Логирование всех AVC отказов
-a always,exit -F arch=b64 -S all -F key=selinux_avc_denied
-a always,exit -F arch=b32 -S all -F key=selinux_avc_denied

# Изменение политик SELinux
-w /etc/selinux/ -p wa -k selinux_policy_change
-w /etc/selinux/config -p wa -k selinux_config_change

# Загрузка/выгрузка модулей
-w /sys/fs/selinux/load -p wa -k selinux_module_load
-w /sys/fs/selinux/disable -p wa -k selinux_disable

# Изменение режима enforcing
-w /sys/fs/selinux/enforce -p wa -k selinux_enforce

# Применение правил
sudo augenrules --load
sudo systemctl restart auditd
```

### 14. Автоматизация через Ansible

```yaml
- name: Управление SELinux через Ansible
  hosts: all
  become: true
  gather_facts: true
  tasks:
    - name: Убедиться, что SELinux установлен и включён
      ansible.posix.selinux:
        policy: targeted
        state: enforcing
      when: ansible_os_family == "RedHat"

    - name: Установить булевы для веб-сервера
      ansible.posix.seboolean:
        name: "{{ item }}"
        state: true
        persistent: true
      loop:
        - httpd_can_network_connect
        - httpd_can_network_connect_db

    - name: Установить контекст SELinux для директории
      ansible.builtin.command:
        cmd: semanage fcontext -a -t httpd_sys_content_t "/srv/my_app(/.*)?"
      register: fcontext_add
      changed_when: "'already defined' not in fcontext_add.stderr"

    - name: Применить контекст
      ansible.builtin.command:
        cmd: restorecon -Rv /srv/my_app

    - name: Установить порт для приложения
      ansible.posix.port:
        ports: "{{ app_port }}"
        protocol: tcp
        setype: http_port_t
      loop: "{{ app_ports }}"
      loop_control:
        loop_var: app_port

    - name: Установить модуль политики (если требуется)
      ansible.builtin.copy:
        src: my_app.pp
        dest: /tmp/my_app.pp
      register: policy_copy

    - name: Установить модуль политики
      ansible.builtin.command:
        cmd: semodule -i /tmp/my_app.pp
      when: policy_copy.changed

    - name: Установить пользователя SELinux
      ansible.posix.selinux_user:
        name: deploy
        seuser: staff_u
        state: present
```

### 15. Wazuh SCA: Проверка SELinux

SCA-политика для автоматизированного контроля. Подробнее: **[Оценка конфигурации безопасности (SCA) в Wazuh](../../../Security/Tools/Wazuh/wazuh-sca.md)**.

**Файл:** `/var/ossec/etc/custom_scripts/sca_selinux.yml`

```yaml
policy:
  id: "selinux_hardening"
  file: "selinux.yml"
  name: "SELinux Compliance"
  description: "Checks SELinux status, booleans, and file contexts"
  regex_type: "pcre2"

requirements:
  title: "Check that the target is a Linux system"
  condition: all
  rules:
    - 'f:/proc/sys/kernel/ostype -> r:Linux'

checks:
  - id: 200001
    title: "SELinux should be enabled"
    rules:
      - 'f:/sys/fs/selinux/enforce -> r:^[01]$'

  - id: 200002
    title: "SELinux should be in enforcing mode"
    rules:
      - 'f:/sys/fs/selinux/enforce -> 1'

  - id: 200003
    title: "SELinux config should be enforcing"
    rules:
      - 'f:/etc/selinux/config -> r:^SELINUX=enforcing'

  - id: 200004
    title: "nokaslr should not be present"
    rules:
      - 'f:/proc/cmdline -> r:^((?!nokaslr).)*$'

  - id: 200005
    title: "Targeted policy should be loaded"
    rules:
      - 'f:/sys/fs/selinux/policy_capabilities -> r:.*targeted.*'

### 16. Валидация, откат и Troubleshooting

#### Валидация после включения/изменения политики

```bash
# Проверка статуса SELinux
sestatus
# → Current mode:                   enforcing
# → Policy from config file:        enforcing

# Проверка загруженных LSM
cat /sys/kernel/security/lsm
# → selinux,apparmor  (SELinux должен присутствовать первым)

# Проверка наличия AVC отказов после применения
sudo ausearch -m avc --start recent --end now
# Если вывод пуст — отказов нет

# Проверка корректности политики
sudo semodule -l | wc -l
# Должен быть > 0

# Проверка AVC-кэша
cat /sys/fs/selinux/avc/cache_stats
# → lookups hits misses...
```

#### Rollback

```bash
# Отключение SELinux (временно до перезагрузки)
sudo setenforce 0

# Отключение SELinux (постоянно)
sudo sed -i 's/^SELINUX=.*/SELINUX=disabled/' /etc/selinux/config
sudo reboot

# Откат изменённых булевых
sudo setsebool -P httpd_can_network_connect off

# Удаление кастомного модуля
sudo semodule -r my_app

# Восстановление файловых контекстов по умолчанию
sudo restorecon -Rv /srv/my_app

# Откат port mappings
sudo semanage port -d -t http_port_t -p tcp 8081

# Откат файловых контекстов
sudo semanage fcontext -d -t httpd_sys_content_t "/srv/my_app(/.*)?"
```

#### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **403 Forbidden (Nginx/Apache)** | Неверный контекст файлов | `restorecon -Rv /var/www/html`, проверить `ls -Z` |
| **Permission denied (SSH)** | Неверный контекст `.ssh` | `restorecon -Rv /home/user/.ssh` |
| **Connection refused к БД** | `httpd_can_network_connect_db = off` | `setsebool -P httpd_can_network_connect_db on` |
| **Cannot bind to port 8080** | Порт не определён для типа | `semanage port -a -t http_port_t -p tcp 8080` |
| **AVC denied при mount** | Контекст устройства/директории | `mount -o context=system_u:object_r:container_file_t:s0 /dev/sdb /mnt` |
| **Docker/Podman Permission denied** | Отсутствие суффикса `:z`/`:Z` | Добавить суффикс к bind mount |
| **Сервис не стартует после hardening** | Неправильный контекст конфига | `restorecon -Rv /etc/<service>/` |
| **Kubernetes: CreateContainerConfigError** | SELinux блокирует запись в volume | Проверить `securityContext.seLinuxOptions.level` |
| **AVC denied для cgroup** | SELinux блокирует запись в cgroup | `audit2allow -w -a`, `restorecon -R /sys/fs/cgroup` |
| **auditd переполняется** | Слишком много AVC записей | Настроить `max_log_file_action = ROTATE`, `num_logs = 10` |
| **Перемаркировка занимает часы** | Большая файловая система | Использовать `touch /.autorelabel` и ждать, или `setfiles` для конкретных путей |
| **`setenforce 1` не работает** | SELinux в `disabled` в config | Изменить `/etc/selinux/config` и перезагрузиться |
| **Module not found при semodule** | Не установлен `policycoreutils-python-utils` | `dnf install policycoreutils-python-utils` |
| **`semanage: command not found`** | `semanage` перемещён в отдельный пакет | `dnf install policycoreutils-python-utils` |
| **Transition blocking при su/sudo** | Политика ограничивает переход домена | Проверить `sesearch -T -s current_t` |
| **Falco/Sysdig не видят события** | `kptr_restrict=2` или `perf_event_paranoid=3` | На хостах с мониторингом: `kptr_restrict=1`, `perf_event_paranoid=2` |

### 17. SELinux и systemd

Systemd-сервисы работают в контексте `systemd_t` или доменах сервисов:

```bash
# Проверка контекста systemd
ps -Z -p 1
# → system_u:system_r:init_t:s0 root

# Проверка контекста запущенного сервиса
ps -Z -C nginx
# → system_u:system_r:httpd_t:s0 nginx

# Если systemd блокирует запуск
sudo journalctl -u nginx | grep -i "denied"
sudo ausearch -m avc -ts recent | grep systemd

# Разрешение systemd на запись в /run
sudo setsebool -P systemd_tmpfiles_extra_rw on
```

### 18. Взаимодействие с User Namespaces

User Namespaces изолируют privileges, но не изолируют MAC-контекст:

| Механизм | Уровень изоляции | Влияние на SELinux |
| :--- | :--- | :--- |
| **User Namespace** | UID/GID mapping | Не изолирует SELinux; контекст процесса остаётся `unconfined_u:unconfined_r:unconfined_t:s0` |
| **PID Namespace** | Видимость PID | Не влияет на MAC |
| **Network Namespace** | Сеть | Не влияет на MAC |
| **Mount Namespace** | Файловая система | Контексты файлов сохраняются; mount options могут блокироваться политикой |

**Rootless контейнеры и SELinux:**
- При запуске Podman rootless контейнеры наследуют контекст пользователя, но MCS-категории всё равно применяются.
- Если пользователь хоста имеет `unconfined_u`, контейнеры также будут менее изолированы.

```bash
# Проверка контекста процесса rootless-контейнера
ps -Z -C conmon
# → unconfined_u:unconfined_r:container_t:s0:c123,c456 conmon

# Если требуется жёсткая изоляция
sudo semanage login -a -s staff_u user1
```

---

## SELinux и контейнеры (2025–2026)

### Изоляция через MCS
Podman и Docker назначают каждому контейнеру уникальные MCS-категории (напр. `s0:c123,c456`). Это предотвращает доступ одного контейнера к файлам другого, даже если оба запущены в домене `container_t`.

**Флаги монтирования томов:**
*   `:z` — Общий контекст (shared). Позволяет нескольким контейнерам работать с одним томом.
*   `:Z` — Приватный контекст (exclusive). Перемаркирует том под конкретный контейнер.

### Kubernetes: SELinuxMount (v1.36 GA)
В 2026 году Kubernetes оптимизировал работу с большими томами:
*   **Проблема:** Рекурсивный `chcon -R` занимал минуты для томов с миллионами файлов.
*   **Решение:** Опция монтирования `context=` в `mount`. Весь том получает метку мгновенно.
*   **Пример в Pod Spec:**
    ```yaml
    securityContext:
      seLinuxChangePolicy: MountOption # Включает быстрое монтирование
      seLinuxOptions:
        level: "s0:c1,c2"
    ```

### sVirt (Secure Virtualization)
Интеграция с KVM/QEMU:
*   Каждая ВМ получает уникальную MCS-метку.
*   Тип процесса ВМ: `svirt_t`.
*   Тип образа диска: `virt_image_t`.

**Диагностика sVirt:**
```bash
# Проверка метки образа
ls -Z /var/lib/libvirt/images/vm1.qcow2
# → system_u:object_r:virt_image_t:s0:c100,c200 vm1.qcow2

# Проверка процесса QEMU
ps -Z -C qemu-kvm
# → system_u:system_r:svirt_t:s0:c100,c200 qemu-kvm ...

# Если ВМ не может получить доступ к образу
sudo ausearch -m avc -ts recent | grep svirt
```

### Проблемы при работе с GPU Passthrough / SR-IOV

При прямом доступе к PCIe устройствам SELinux может блокировать доступ к устройствам:

```bash
# Проверка контекста устройства
ls -Z /dev/vfio/17
# → system_u:object_r:device_t:s0 /dev/vfio/17

# Разрешение доступа (временное)
sudo chcon -t svirt_image_t /dev/vfio/17

# Постоянное правило
sudo semanage permissive -a svirt_t
```

---

## Производительность и тюнинг (RHEL 9/10)

1.  **AVC Cache Tuning:** Для систем с высокой нагрузкой (напр. БД с тысячами соединений) увеличьте размер кэша решений:
    ```bash
    echo 8192 > /sys/fs/selinux/avc/cache_threshold
    ```
2.  **Auditd Optimization:** Снизьте нагрузку на ввод-вывод, настроив асинхронную запись в `/etc/audit/auditd.conf`:
    ```ini
    flush = INCREMENTAL_ASYNC
    priority_boost = 4
    ```

---

## Матрица совместимости: SELinux и Workload

| Профиль | Kubernetes Control Plane | Kubernetes Worker | Database (PostgreSQL/MySQL) | Web Server (nginx/Apache) | Monitoring (Prometheus/Grafana) | eBPF Observability (Falco/Cilium) | CI/CD Runners | Rootless Containers | Physical Server (SME/DB) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Maximum (Lockdown + MLS)** | [!] Требует подписи политик | [!] Требует подписи политик | [OK] | [OK] | [!] `perf_event_paranoid=2` | [BLOCKED] | [BLOCKED] | [BLOCKED] | [OK] |
| **Hardened (Targeted + RBAC)** | [OK] | [OK] | [OK] | [OK] | [OK] | [!] `kptr_restrict=1` | [OK] | [!] userns_limit>0 | [OK] |
| **Balanced (CIS L1)** | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] |
| **Minimal (Defaults)** | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] |

*Легенда: [OK] — совместимо, [!] — требует тонкой настройки/исключений, [BLOCKED] — конфликтует.*

**Примечания к новым параметрам политик:**

*   **MLS policy:** Требует пересборки политики и перемаркировки всей ФС. Используется только в high-security средах.
*   **RBAC + User namespace:** SELinux RBAC работает на уровне хоста и не изолируется в user namespace.
*   **eBPF-мониторинг:** При `kernel.kptr_restrict=2` Falco/Cilium не могут читать символы ядра. Используйте `kptr_restrict=1` или дайте `CAP_SYSLOG` агенту.
*   **Kubernetes:** Включите `ContainerRuntime` в SELinux политике для корректной работы CRI-O/containerd.

---

## Дополнительная информация

### MCS vs MLS

| Характеристика | MLS | MCS |
| :--- | :--- | :--- |
| **Структура** | Иерархическая (Levels) | Неиерархическая (Categories) |
| **Доступ** | Сверху вниз (Top Secret > Secret) | По точному совпадению категорий |
| **Применение** | Госбезопасность, военные | Изоляция контейнеров, облака |

### Инструменты и пакеты

| Пакет | Утилиты | Назначение |
| :--- | :--- | :--- |
| `setools-console` | `seinfo`, `sesearch` | Анализ политик, поиск правил |
| `policycoreutils-python-utils` | `semanage`, `audit2allow`, `seinfo` | Управление и генерация модулей |
| `policycoreutils` | `restorecon`, `fixfiles`, `secon` | Базовые утилиты управления контекстами |
| `setroubleshoot-server` | `sealert` | Человекочитаемый анализ логов |
| `selinux-policy-devel` | `Makefile` для сборки модулей | Разработка кастомных `.te` / CIL модулей |
| `slang` | `selang` | Интерактивный интерфейс для тестирования политик |

### Дополнительные ссылки по темам

*   **Fedora Project:** [SELinux/UserGuidelines](https://docs.fedoraproject.org/en-US/quick-docs/getting-started-with-selinux/) — официальное руководство по работе с SELinux.
*   **Red Hat:** [SELinux Guide for RHEL 9](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9/html/selinux_users_and_administrators_guide/index) — полное руководство.
*   **NSA:** [NSA SELinux](https://www.nsa.gov/research/selinux/) — историческая справка и исходная документация.

### См. также
- [Обзор механизмов безопасности Linux](../Linux_Security_Mechanisms_Overview.md)
- [AppArmor: альтернатива на основе путей](./AppArmor.md)
- [Аудит системных событий (auditd)](../../SystemAdministration/Logging/auditd.md)
- [Безопасность модулей ядра](./kernel_module_security.md) — подпись и контроль загрузки модулей
- [Харденинг ядра Linux](../../Security/Mechanisms/Kernel/hardening.md)
- [KPTI: защита таблиц страниц ядра](./KPTI.md)
