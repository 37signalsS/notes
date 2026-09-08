# Модули ядра Linux

## Определения

**Модуль ядра (Kernel Module)** — это скомпилированный объектный файл (обычно с расширением `.ko`, `.ko.zst` или `.ko.xz`), содержащий код для расширения базовой функциональности ядра. Это позволяет динамически добавлять поддержку драйверов, файловых систем и сетевых протоколов без перезагрузки.

**LKM (Loadable Kernel Module)** — механизм, обеспечивывающий модульность Linux, позволяя подгружать компоненты в адресное пространство ядра по требованию.

**Встроенный модуль (Built-in)** — код, статически компонованный в образ ядра (`vmlinuz`). В отличие от LKM, такие модули не могут быть выгружены. Их параметры находятся в `/sys/module/`, но они не появляются в `lsmod`, так как не загружаются динамически.

**In-tree vs Out-of-tree:**
- **In-tree:** Модули, находящиеся в основном дереве исходного кода ядра Linux. Обслуживаются сообществом, гарантированно совместимы с конкретной версией ядра.
- **Out-of-tree:** Сторонние модули (NVIDIA, ZFS, VirtualBox), разрабатываемые вне основного дерева. Требуют пересборки при обновлении ядра (обычно через DKMS).

## Основные концепции

### Жизненный цикл и механизмы загрузки

Механизм загрузки модуля основан на системных вызовах, которые переводят исполняемый код из пользовательского пространства в адресное пространство ядра:

1. **Системные вызовы (`syscalls`):**
   - **`init_module()`** — классический вызов, принимающий путь к файлу `.ko`. Уязвим к гонкам (race conditions), так как путь разрешается в контексте ядра.
   - **`finit_module()` (Linux 3.8+)** — современный вызов, принимающий дескриптор файла. Предпочтителен при Secure Boot, так как файл может быть открыт с проверкой подписи через `O_CLOEXEC`, и путь к файлу не разрешается в контексте ядра. Используется `modprobe` и `insmod` при наличии поддержки.
   - **`delete_module()`** — выгружает модуль из памяти ядра.

2. **Этапы загрузки через `modprobe`:**
   - modprobe читает базу данных модулей в `/lib/modules/$(uname -r)/`.
   - С помощью `modules.alias` определяет, какой файл `.ko` соответствует запрошенному имени или аппаратному псевдониму.
   - С помощью `modules.dep` (создаваемого `depmod`) вычисляет цепочку зависимостей и загружает их по порядке.
   - Для каждого модуля вызывается `finit_module()`, после чего исполняется функция инициализации модуля (`module_init`).

3. **Функции инициализации и выгрузки:**
   - **`module_init()`** — макрос, объявляющий функцию, вызываемую при загрузке модуля. Выполняет регистрацию символов (`EXPORT_SYMBOL`), файловых операций, устройств (`device_create`) и т.д.
   - **`module_exit()`** — макрос, объявляющий функцию, вызываемую при выгрузке (`rmmod`). Должна отменить все изменения, внесенные `module_init`.

4.  **Rust в ядре:** Начиная с версии 6.1 начата интеграция Rust, а к версии 7.x (2026) Rust признан вторым официальным языком разработки. Это устраняет целые классы ошибок управления памятью (Use-after-free, Double free, Buffer overflow) на этапе компиляции. Подробнее в [обзоре ядра](./overview.md).

5.  **Загрязнение ядра (Kernel Taint):** Если загружается проприетарный или Out-of-tree модуль, ядро помечается как «загрязненное» (tainted). Это важный индикатор при анализе Kernel Panic. Полная таблица флагов и методы расшифровки описаны в [Kernel Panic](./kernel_panic.md) и [документе по dmesg](../../Diagnostics/Kernel/dmesg/troubleshooting.md).
   - Проверка: `cat /proc/sys/kernel/tainted` (0 — чистое ядро).

6.  **Безопасность и подпись модулей:**
   - **Secure Boot + Lockdown:** Требуют обязательной подписи модулей. При включенном Secure Boot активируется режим Kernel Lockdown.
   - `CONFIG_MODULE_SIG_FORCE=y`: Ядро откажется загружать любой модуль без валидной подписи. Подробнее в [харденинге ядра](../../Security/Mechanisms/Kernel/hardening.md).
   - Проверка подписи: `modinfo -F signature module_name` и `modinfo -F sig_key module_name`.

7.  **Алиасы и udev:** Ядро сопоставляет оборудование с модулями через таблицу алиасов (`modules.alias`). При обнаружении устройства `udev` автоматически вызывает `modprobe` для загрузки нужного драйвера. Это происходит на этапе раннего userspace в `initramfs` — см. [процесс загрузки](./boot_process.md).

### Управление зависимостями

- **`modprobe`**: Основной инструмент. Использует `modules.dep` (создается `depmod`) для автоматической загрузки цепочки зависимостей. Автоматически разрешает алиасы через `modules.alias` и поддерживает параметры загрузки.
  - `modprobe -r module_name`: Выгружает модуль и все модули, зависящие от него.
  - `modprobe --show-depends module_name`: Показывает цепочку зависимостей без реальной загрузки.
  - `modprobe -c`: Выводит полную конфигурацию modprobe (черные списки, опции, алиасы).
  - `modprobe -v module_name`: Verbose-режим для отладки загрузки.
- **`insmod`**: Загружает конкретный файл `.ko`. Игнорирует зависимости и не использует системные пути. Требует ручного указания всех зависимостей.
- **`rmmod`**: Выгружает модуль по имени. Не выгружает зависимые модули автоматически — используйте `modprobe -r` для этого.
- **`depmod`**: Сканирует все модули в `/lib/modules/$(uname -r)/` и создает:
  - `modules.dep` — таблица зависимостей
  - `modules.alias` — сопоставление аппаратных псевдонимов с модулями
  - `modules.symbols` — экспортируемые символы
  - `modules.builtin` — список встроенных модулей
  - Обычно вызывается автоматически при установке пакета ядра. Для принудительного пересоздания: `depmod -a` (все модули) или `depmod -A` (только измененные).

### Параметры модулей

**Параметры модуля (Module Parameters)** — механизм передачи конфигурационных значений в LKM при загрузке или во время работы. Параметры определяются в исходном коде модуля через макрос `module_param(name, type, perm)`, где:
- `name` — имя параметра
- `type` — тип (`int`, `uint`, `charp`, `bool`, `ulong`, `long`, `ushort`, `short`, `byte`, `ulong`)
- `perm` — permissions для sysfs-атрибута (0 — скрыть, 0644 — чтение/запись, 0444 — только чтение)

**Способы установки параметров:**
1. **При загрузке через modprobe:** `modprobe module_name param=value`
2. **На этапе загрузки через /etc/modprobe.d/:** `options module_name param=value`
3. **Через аргументы ядра в GRUB:** `module_name.param=value` (только для built-in модулей)
4. **В runtime через sysfs:** изменение файлов в `/sys/module/module_name/parameters/` (если `perm & S_IW`)

**Просмотр параметров:**
```bash
modinfo -p module_name    # показать все параметры с типами и описаниями
cat /sys/module/module_name/parameters/param_name   # текущее значение в runtime
```

## Практические сценарии

### Инвентаризация и инспекция

```bash
# Список загруженных модулей (колонки: Module, Size, Used by)
lsmod
# → Module                  Size  Used by
# → overlay               108544  1
# → nf_conntrack          172032  1 nf_conntrack_ftp

# Аналогично, но через /proc/modules (сырой формат)
cat /proc/modules

# Список модулей, отсортированный по количествю обратных зависимостей
# (количество модулей, которые используют данный — колонка "Used by")
lsmod | sort -k3 -nr | head

# Полный вывод modinfo — все метаданные модуля
modinfo nvme

# Только конкретное поле (ключевые поля для администрирования)
modinfo -F vermagic nf_conntrack    # совместимость с версией ядра
modinfo -F depends nf_conntrack    # зависимости
modinfo -F license nvme            # лицензия (влияет на доступ к GPL-символам)
modinfo -F srcversion nvme         # хэш исходного кода
modinfo -F alias nf_conntrack     # аппаратные псевдонимы для автозагрузки
modinfo -p usb_storage             # только список параметров модуля

# Просмотр структуры /sys/module/ для конкретного модуля
ls /sys/module/nvme/parameters/
# → async_probe  iodir  iomap_limit  iomove_max_sectors  ...
# → (можно читать и писать значения, если разрешены права)

# Проверка экспортированных символов (функций) модуля
grep "\[nvme\]" /proc/kallsyms   # все символы модуля
grep " T " /proc/kallsyms | grep "\[nvme\]"   # только экспортированные функции (global text)

# Проверка статуса загрязнения конкретного модуля
cat /sys/module/nvme/taint    # 0 = чистый, !0 = проприетарный/подозрительный
```

### Управление загрузкой и выгрузкой модулей

```bash
# Загрузка модуля (автоматически разрешает зависимости)
sudo modprobe wireguard

# Выгрузка модуля с зависимыми
sudo modprobe -r wireguard

# Загрузка конкретного файла .ko (без разрешения зависимостей)
sudo insmod /path/to/module.ko

# Выгрузка по имени (без разрешения обратных зависимостей)
sudo rmmod module_name

# Сухой прогон: что будет загружено включая зависимости (без реальной загрузки)
modprobe -n -v module_name

# Проверка: был ли модуль загружен успешно
lsmod | grep module_name

# Просмотр логов загрузки в реальном времени
sudo dmesg -w | grep module_name &

sudo modprobe module_name

# Сборка и установка для конкретного ядра через DKMS (без перезагрузки)
sudo dkms install -m module_name -v version -k $(uname -r)
```

### Автозагрузка на этапе загрузки

Модули, которые должны загружаться при каждой загрузке системы, настраиваются через специальные каталоги.

**Современный способ — `/etc/modules-load.d/`:**

```bash
# /etc/modules-load.d/network-modules.conf
# Один модуль на строку
ip_vs
ip_vs_rr
ip_vs_wrr
ip_vs_sh
nf_conntrack

# Применение без перезагрузки
sudo systemctl restart systemd-modules-load

# Проверка статуса службы
systemctl status systemd-modules-load
# → active (exited) — все модули из *.conf загружены
```

**Наследуемый способ — `/etc/modules`:**

```bash
# /etc/modules (один модуль на строку, legacy-формат)
# До 2026 года поддерживается на всех major Linux-дистрибутивах
bonding
```

> Справочно: `systemd-modules-load.service` читает файлы из `/etc/modules-load.d/*.conf`, `/run/modules-load.d/*.conf` и `/usr/lib/modules-load.d/*.conf` в указанном порядке. Файлы `/usr/lib/modules-load.d/*.conf` обычно создаются пакетами драйверов.

### Черный список и блокировка модулей

Блокировка модулей — ключевая задача харденинга и предотвращения загрузки конфликтующих драйверов.

**Через modprobe.d (userspace-уровень):**

```bash
# /etc/modprobe.d/blacklist-local.conf
# Слабая блокировка: модуль не загружается автоматически (через алиасы/udev),
# но может быть загружен вручную через insmod/modprobe.
blacklist pcspkr
blacklist firewire-core
blacklist thunderbolt

# Сильная блокировка: полностью предотвращает загрузку.
# /etc/modprobe.d/disable-firewire.conf
install firewire-core /bin/true
install thunderbolt /bin/true

# Просмотр активных правил блокировки
modprobe -c | grep -E "blacklist|install"
```

**Через параметры загрузки ядра (ранний этап, до userspace):**

```bash
# В /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="... module_blacklist=pcspkr,ipv6,nouveau"

# Применение
sudo update-grub

# Проверка: модуль не загрузится даже в initramfs
```

> **Разница между `blacklist` и `install ... /bin/true`:**
> - `blacklist module` — помещает модуль в черный список modprobe. Модуль не загружается автоматически при обнаружении оборудования, но его можно загрузить явно (`modprobe module`).
> - `install module /bin/true` — перехватывает любую попытку загрузки модуля через modprobe и заменяет ее на `/bin/true`. Модуль не может быть загружен через `modprobe module`. Защищает от случайной загрузки.
> - `module_blacklist=module` (kernel cmdline) — действует на раннем этапе загрузки, до запуска userspace. Нужен, когда модуль может быть загружен в initramfs.

### Настройка параметров модулей

```bash
# Просмотр доступных параметров и их текущих значений
ls /sys/module/nf_conntrack/parameters/
# → nf_conntrack_helper  hashsize  max_connections  ...

cat /sys/module/nf_conntrack/parameters/hashsize
# → 65536

# Runtime-изменение параметра (если разрешено, perm & S_IW)
echo 262144 | sudo tee /sys/module/nf_conntrack/parameters/hashsize
# → 262144

# Постоянная настройка через /etc/modprobe.d/
# /etc/modprobe.d/nf_conntrack.conf
options nf_conntrack hashsize=262144 max_connections=1048576

# Просмотр параметров через модульные опции GRUB (для built-in модулей)
# В /etc/default/grub:
# GRUB_CMDLINE_LINUX_DEFAULT="... nf_conntrack.hashsize=262144"
# sudo update-grub
```

### Сборка и установка модулей

Сборка LKM требует установленных заголовков ядра и специального `Makefile`.

```bash
# Установка заголовков ядра (требуются для сборки)
# Debian/Ubuntu:
sudo apt install linux-headers-$(uname -r) build-essential

# RHEL/Fedora/Rocky:
sudo dnf install kernel-devel-$(uname -r) gcc make

# Arch Linux:
sudo pacman -S linux-headers

# Makefile для простого модуля:
# obj-m += my_module.o
# all:
#     make -C /lib/modules/$(uname -r)/build M=$(PWD) modules
# clean:
#     make -C /lib/modules/$(uname -r)/build M=$(PWD) clean

# Сборка
make

# Результат: my_module.ko (или .ko.zst/.ko.xz при сжатии)

# Установка и загрузка
sudo insmod my_module.ko
sudo depmod -a   # обновить таблицу зависимостей
sudo modprobe my_module   # загрузить через modprobe (умеет искать в /lib/modules/)
```

### Автоматизация через DKMS

DKMS (Dynamic Kernel Module Support) автоматически пересобирает out-of-tree модули при обновлении ядра.

```bash
# Добавление исходников модуля в дерево DKMS
sudo dkms add -m nvidia -v 550.54

# Сборка модуля для текущего и всех установленных ядер
sudo dkms build -m nvidia -v 550.54
sudo dkms autoinstall

# Установка собранного модуля
sudo dkms install -m nvidia -v 550.54 -k $(uname -r)

# Просмотр статуса: какие модули для каких ядер собраны
dkms status
# → nvidia, 550.54, 6.8.0-45-generic, x86_64: installed
# → virtualbox-host-modules, 7.0.14, 6.8.0-45-generic, x86_64: built

# Принудительная пересборка для конкретного ядра
sudo dkms remove -m nvidia -v 550.54 -k 6.8.0-40-generic --all
sudo dkms build -m nvidia -v 550.54 -k 6.8.0-40-generic
sudo dkms install -m nvidia -v 550.54 -k 6.8.0-40-generic

# Удаление модуля из DKMS
sudo dkms remove -m nvidia -v 550.54 --all
```

### Мониторинг и аудит загрузки модулей

Для диагностики и обеспечения безопасности важно отслеживать, какие модули загружаются и откуда они пришли.

```bash
# Инвентаризация: список загруженных модулей с путями к файлам на диске
for mod in $(lsmod | awk 'NR>1 {print $1}'); do
    echo "$mod: $(modinfo -F filename "$mod" 2>/dev/null || echo 'N/A (встроенный или скрытый)')"
done

# Обнаружение скрытых модулей (rootkit detection):
# Если модуль есть в lsmod, но modinfo не возвращает путь — это может быть rootkit
lsmod | awk 'NR>1 {print $1}' | while read mod; do
    path=$(modinfo -F filename "$mod" 2>/dev/null)
    [ -z "$path" ] && echo "WARNING: module '$mod' has no file path — possible rootkit"
done

# Мониторинг загрузки модулей через systemd journal
journalctl -k --since "1 hour ago" | grep -i "module.*loaded\|init_module"
# → kernel: module verification failed: signature verification failure (taint)

# Проверка: есть ли модули без подписи (для систем с Secure Boot)
for mod in $(lsmod | awk 'NR>1 {print $1}'); do
    sig=$(modinfo -F signature "$mod" 2>/dev/null)
    [ -z "$sig" ] && echo "UNSIGNED: $mod"
done
```

**Аудит через auditd:**

Правила в `/etc/audit/rules.d/modules.rules` для отслеживания всех операций с модулями:

```bash
# Аудит загрузки/выгрузки модулей через syscalls
-a always,exit -F arch=b64 -S init_module,finit_module,delete_module -k module_syscalls

# Аудит вызовов insmod/rmmod/modprobe
-w /sbin/insmod -p x -k module_load
-w /sbin/rmmod -p x -k module_unload
-w /sbin/modprobe -p x -k module_modprobe

# Конфигурационные изменения (перезапись blacklist, options)
-w /etc/modprobe.d/ -p wa -k module_config
```

Применение правил:
```bash
sudo augenrules --load    # или: sudo auditctl -R /etc/audit/rules.d/modules.rules
sudo auditctl -l | grep module
```

Просмотр событий:
```bash
sudo ausearch -k module_syscalls -ts recent
```

Подробнее о настройке аудита в [auditd](../../SystemAdministration/Logging/auditd.md).

### Диагностика и устранение неполадок

При проблемах с загрузкой модуля используйте системные логи:

```bash
# Просмотр сообщений ядра при загрузке модуля (в реальном времени)
sudo dmesg -w

# Ошибки modprobe через journalctl
journalctl -kt kernel | grep -i "module\|modprobe"

# Детальная диагностика модуля: проверка vermagic
modinfo -F vermagic module_name
# → должно совпадать с uname -r

# Проверка зависимостей
modinfo -F depends module_name
# → через запятую список требуемых модулей
```

**Типичные ошибки и решения:**

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `modprobe: FATAL: Module not found` | Модуль отсутствует в `modules.dep` | `sudo depmod -a` |
| `modprobe: FATAL: Module not found in directory /lib/modules/...` | Пакет `linux-modules` для текущего ядра не установлен | Установить `linux-modules-$(uname -r)` |
| `insmod: ERROR: could not insert module: Invalid module format` | Несоответствие `vermagic` (kernel version, compiler, SMP) | Пересобрать модуль для текущего ядра |
| `insmod: ERROR: could not insert module: Unknown symbol in module` | Отсутствует зависимая функция/символ | Загрузить зависимости через `modprobe`, а не `insmod` |
| `rmmod: ERROR: Module is in use` | На модуль ссылаются другие модули (refcount > 0) | `sudo modprobe -r module_name` (выгрузит с зависимыми) или найти пользователя через `lsmod` |
| `Operation not permitted` при загрузке | Secure Boot/Lockdown блокирует неподписанный модуль | Подписать модуль или добавить ключ в MOK |
| `modprobe: module verification failed` | Подпись невалидна, но загрузка продолжается | `modinfo -F sig_key module`, проверить цепочку подписей |
| `modprobe: ERROR: module is from the unsigned category` | Модуль подписан неподписанным ключом | Установить доверенный сертификат в MOK через `mokutil --import` |

**Проверка конфигурации сборки ядра:**

```bash
# Поддержка модулей и подписей
grep CONFIG_MODULES /boot/config-$(uname -r)
# → CONFIG_MODULES=y

grep CONFIG_MODULE_SIG /boot/config-$(uname -r)
# → CONFIG_MODULE_SIG=y

grep CONFIG_MODULE_SIG_FORCE /boot/config-$(uname -r)
# → CONFIG_MODULE_SIG_FORCE=y
```

### Интеграция с Ansible

Модуль `ansible.builtin.modprobe` обеспечивает декларативное управление модулями:

```yaml
# /etc/ansible/roles/kernel-modules/tasks/main.yml
---
- name: "Загрузить сетевые модули для Kubernetes"
  ansible.builtin.modprobe:
    name: "{{ item }}"
    state: present
  loop:
    - overlay
    - br_netfilter
    - ip_vs
    - ip_vs_rr
    - ip_vs_wrr
    - ip_vs_sh
    - nf_conntrack

- name: "Заблокировать опасные модули"
  ansible.builtin.lineinfile:
    path: /etc/modprobe.d/blacklist-dangerous.conf
    line: "blacklist {{ item }}"
    create: yes
  loop:
    - firewire-core
    - thunderbolt
    - dccp
    - rds

- name: "Настройка параметров conntrack через modprobe.d"
  ansible.builtin.lineinfile:
    path: /etc/modprobe.d/nf_conntrack.conf
    line: "options nf_conntrack hashsize={{ conntrack_hashsize }}"
    create: yes
    regexp: '^options nf_conntrack hashsize='

- name: "Создать файл автозагрузки модулей"
  ansible.builtin.copy:
    content: |
      ip_vs
      ip_vs_rr
      ip_vs_wrr
      ip_vs_sh
      nf_conntrack
    dest: /etc/modules-load.d/k8s-modules.conf
    mode: '0644'
```

### Автоматизация через DKMS

DKMS (Dynamic Kernel Module Support) незаменим для проприетарных драйверов (NVIDIA, VirtualBox, ZFS, драйверы сетевых карт).

```bash
# Сборка модуля для конкретного ядра (если не собрался автоматически)
sudo dkms build -m nvidia -v 550.54 -k 6.8.0-generic
sudo dkms install -m nvidia -v 550.54 -k 6.8.0-generic

# Просмотр статуса DKMS
dkms status
# → nvidia, 550.54, 6.8.0-45-generic, x86_64: installed
# → virtualbox-host-modules, 7.0.14, 6.8.0-45-generic, x86_64: built

# Автоматическая пересборка при обновлении ядра
sudo dkms autoinstall

# Удаление модуля
sudo dkms remove -m nvidia -v 550.54 --all
```

## Дополнительная информация

### Связанные темы

- **Тюнинг ядра:** [sysctl](./sysctl.md) — управление параметрами через `/proc/sys`.
- **Живое обновление:** [Live Patching](./live_patching.md) — исправление кода функций внутри загруженных модулей без выгрузки.
- **Процесс загрузки:** [Boot Process](./boot_process.md) — загрузка модулев на этапе `initramfs`.
- **Интерфейсы:** [Интерфейсы ядра Linux](./kernel_interfaces.md) — роль системных вызовов (`init_module`, `finit_module`, `delete_module`) в управлении LKM.
- **Виртуальные ФС:** [Виртуальная ФС /proc](../../FileSystems/virtual_fs_proc.md) (`/proc/modules`) и [Виртуальная ФС /sys](../../FileSystems/virtual_fs_sys.md) (`/sys/module/`) — интерфейсы для инспекции модулей.
- **Диагностика:** [Kernel Panic](./kernel_panic.md) — анализ влияния «загрязненных» модулей на стабильность.
- **Диагностика dmesg:** [Поиск и устранение неисправностей с dmesg](../../Diagnostics/Kernel/dmesg/troubleshooting.md) — интерпретация ошибок загрузки модулей и taint flags.
- **Безопасность:** [Харденинг ядра](../../Security/Mechanisms/Kernel/hardening.md) — подпись модулей, блокировка опасных драйверов, параметры `kernel.modules_disabled`.
- **Аудит:** [auditd](../../SystemAdministration/Logging/auditd.md) — мониторинг системных вызовов для загрузки модулей.
- **Управление железом:** [Диагностика оборудования](../../Diagnostics/Hardware/hardware_listing.md) — связь между загруженными драйверами и обнаруженным оборудованием.
- **Обзор ядра:** [Обзор ядра Linux](./overview.md) — контекст архитектуры монолитного ядра и модульности.
