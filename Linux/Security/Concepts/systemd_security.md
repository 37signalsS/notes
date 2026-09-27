# Безопасность systemd: Изоляция и защита сервисов

## Определения

**systemd Security** — комплекс механизмов изоляции и ограничения привилегий для сервисов (unit-файлов), управляемых/init-системой systemd. Эти механизмы реализуют принцип минимальных привилегий (Principle of Least Privilege) и защиту глубины (Defense in Depth), предотвращая компрометацию одного сервиса от распространения на всю систему.

**Ключевые понятия:**
- **Sandboxing** — изоляция процесса от ресурсов хоста (ФС, сеть, временные файлы)
- **Capability Bounding Set** — ограничение набора Linux Capabilities для процесса
- **System Call Filtering** — фильтрация системных вызовов через seccomp
- **Mount Namespace** — изолированное пространство монтирования

## Теоретический блок

### Уровни защиты systemd

| Уровень | Механизмы | Описание |
| :--- | :--- | :--- |
| **Файловая система** | `ProtectSystem`, `ProtectHome`, `ReadWritePaths`, `ReadOnlyPaths` | Ограничение доступа к директориям |
| **Временные файлы** | `PrivateTmp`, `PrivateDevices` | Изолированный `/tmp`, `/var/tmp`, устройства |
| **Сеть** | `PrivateNetwork`, `RestrictAddressFamilies` | Ограничение сетевого доступа |
| **Привилегии** | `NoNewPrivileges`, `CapabilityBoundingSet`, `AmbientCapabilities` | Контроль привилегий |
| **Системные вызовы** | `SystemCallFilter`, `SystemCallArchitectures` | Фильтрация syscall через seccomp |
| **Ядро** | `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectControlGroups` | Защита параметров ядра |
| **Память** | `MemoryDenyWriteExecute`, `RestrictRealtime` | Защита памяти |

### Ключевые директивы безопасности

#### Защита файловой системы

| Директива | Значение | Рекомендация |
| :--- | :--- | :--- |
| `ProtectSystem=full` | `/usr`, `/boot`, `/etc` доступны только для чтения | Для всех сервисов |
| `ProtectSystem=strict` | Вся ФС доступна только для чтения | Для сервисов, не требующих записи |
| `ProtectHome=yes` | `/home`, `/root`, `/run/user` недоступны | Для системных сервисов |
| `ReadWritePaths=` | Разрешенные пути для записи | Ограничить только необходимыми |
| `ReadOnlyPaths=` | Пути, доступные только для чтения | Для конфигурационных файлов |
| `InaccessiblePaths=` | Полностью недоступные пути | Для чувствительных данных |

#### Изоляция временных файлов и устройств

| Директива | Значение |
| :--- | :--- |
| `PrivateTmp=yes` | Изолированный `/tmp` и `/var/tmp` для сервиса |
| `PrivateDevices=yes` | Изолированные устройства (`/dev`) |
| `PrivateMounts=yes` | Изолированное пространство монтирования |
| `PrivateUsers=yes` | Изолированное пространство пользователей |

#### Управление привилегиями

| Директива | Значение | Рекомендация |
| :--- | :--- | :--- |
| `NoNewPrivileges=yes` | Запрет получения новых привилегий через `execve()` | Включать для всех сервисов |
| `CapabilityBoundingSet=` | Набор доступных capabilities | Оставить только необходимые |
| `AmbientCapabilities=` | Capabilities, передаваемые процессу | Для непривилегированных сервисов |
| `User=` | Запуск от конкретного пользователя | Избегать запуска от root |
| `Group=` | Группа для запуска | Использовать системные группы |

#### Фильтрация системных вызовов

| Директива | Значение |
| :--- | :--- |
| `SystemCallFilter=` | Разрешенные/запрещенные системные вызовы |
| `SystemCallArchitectures=` | Разрешенные архитектуры (native, x86, x86-64) |
| `RestrictNamespaces=yes` | Запрет создания пространств имён |
| `RestrictSUIDSGID=yes` | Запрет создания SUID/SGID файлов |

#### Защита ядра

| Директива | Значение |
| :--- | :--- |
| `ProtectKernelTunables=yes` | Защита `/proc/sys`, `/sys` |
| `ProtectKernelModules=yes` | Запрет загрузки модулей ядра |
| `ProtectKernelLogs=yes` | Ограничение доступа к логам ядра |
| `ProtectControlGroups=yes` | Защита cgroups |

### Оценка безопасности systemd

Команда `systemd-analyze security` оценивает безопасность сервиса по шкале от 0 до 9.6 (уникальные баллы). Низкие баллы указывают на слабые места.

```bash
# Оценка безопасности сервиса
systemd-analyze security nginx.service

# Показать только критические замечания
systemd-analyze security --no-pager nginx.service | grep -E "Bad|Unsafe"
```

## Практический блок

### Пример защищенного unit-файла

```ini
# /etc/systemd/system/web-app.service
[Unit]
Description=Web Application with Hardened Security
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=webapp
Group=webapp

# --- Файловая система ---
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/webapp /var/log/webapp
ReadOnlyPaths=/etc/webapp
InaccessiblePaths=/root /home

# --- Временные файлы и устройства ---
PrivateTmp=yes
PrivateDevices=yes
PrivateMounts=yes

# --- Привилегии ---
NoNewPrivileges=yes
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
RestrictSUIDSGID=yes

# --- Сетевые ограничения ---
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

# --- Фильтрация системных вызовов ---
SystemCallFilter=@system-service
SystemCallArchitectures=native

# --- Защита ядра ---
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes

# --- Память ---
MemoryDenyWriteExecute=yes
RestrictRealtime=yes

# --- Дополнительно ---
LockPersonality=yes
RestrictNamespaces=yes
PrivateNetwork=no
PrivateUsers=no

ExecStart=/usr/bin/webapp --config /etc/webapp/config.yml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Проверка текущих настроек безопасности

```bash
# Показать все security-related опции для сервиса
systemctl show web-app.service -p NoNewPrivileges -p ProtectSystem -p PrivateTmp

# Проверить, что сервис запущен с правильными флагами
cat /proc/$(pgrep webapp)/status | grep -E 'NoNewPrivs|Seccomp'

# Проверить capabilities процесса
getpcaps $(pgrep webapp)
```

### Постепенное ужесточение

```bash
# 1. Начать с оценки
systemd-analyze security myapp.service

# 2. Добавить базовые директивы
sudo systemctl edit myapp.service
# Добавить:
# [Service]
# NoNewPrivileges=yes
# ProtectSystem=full
# PrivateTmp=yes

# 3. Перезагрузить и проверить
sudo systemctl daemon-reload
sudo systemctl restart myapp.service
systemd-analyze security myapp.service

# 4. Постепенно добавлять более строгие ограничения
```

### Интеграция с Ansible

```yaml
- name: Deploy hardened systemd service
  ansible.builtin.template:
    src: myapp.service.j2
    dest: /etc/systemd/system/myapp.service
    mode: '0644'
  notify: Restart myapp

- name: Ensure systemd security options
  ansible.builtin.lineinfile:
    path: /etc/systemd/system/myapp.service
    regexp: "{{ item.regexp }}"
    line: "{{ item.line }}"
    insertafter: '[Service]'
  loop:
    - { regexp: '^NoNewPrivileges=', line: 'NoNewPrivileges=yes' }
    - { regexp: '^ProtectSystem=', line: 'ProtectSystem=strict' }
    - { regexp: '^PrivateTmp=', line: 'PrivateTmp=yes' }
    - { regexp: '^ProtectHome=', line: 'ProtectHome=yes' }
  notify: Restart myapp
```

## Дополнительная информация

### Связанные темы
- **[Linux Capabilities](../Mechanisms/Capabilities.md)** — гранулярные привилегии вместо полного root
- **[Seccomp](../Mechanisms/Seccomp.md)** — фильтрация системных вызовов
- **[SELinux](../Mechanisms/SELinux.md)**, **[AppArmor](../Mechanisms/AppArmor.md)** — принудительный контроль доступа
- **[Безопасность модулей ядра](../Mechanisms/kernel_module_security.md)** — подпись и контроль загрузки модулей
- **[Cgroups](../../Core/cgroups.md)** — ограничение ресурсов (CPU, память)
- **[Аудит событий](../../SystemAdministration/Logging/auditd.md)** — мониторинг запуска сервисов
- **[Docker security](../../Docker/Docker_security/container_hardening.md)** — sandboxing контейнеров
- **[Обзор механизмов безопасности](../Linux_Security_Mechanisms_Overview.md)** — контекст всех механизмов защиты

### Соответствие стандартам
- **CIS Benchmarks** — рекомендации по настройке systemd для конкретных ОС
- **DISA STIG** — требования к изоляции сервисов
- **PCI DSS** — требование 2.2: настройка безопасной конфигурации

### Лучшие практики
1. **Запуск от непривилегированных пользователей**: всегда используйте `User=` и `Group=`
2. **Минимизация привилегий**: `NoNewPrivileges=yes` для всех сервисов
3. **Изоляция ФС**: `ProtectSystem=strict` + `ReadWritePaths` только для необходимых путей
4. **Регулярная оценка**: используйте `systemd-analyze security` при каждом обновлении
5. **Версионирование**: храните unit-файлы в Git для отслеживания изменений

### Частые ошибки
- Запуск сервисов от `root` без необходимости
- Отсутствие `NoNewPrivileges=yes` (позволяет эскалацию через SUID)
- Использование `--privileged` в Docker (отключает все ограничения)
- Неполная изоляция ФС (сервис может изменять критические файлы)
