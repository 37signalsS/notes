# Chroot — смена корневого каталога

## Определения

**Chroot (change root)** — системный вызов и одноименная утилита в Linux/Unix, позволяющая запустить процесс, для которого корневым каталогом `/` будет являться произвольно заданная директория.

**Chroot jail («тюрьма»)** — изолированное окружение, созданное с помощью `chroot`. Процесс внутри «тюрьмы» не может получить доступ к файлам за пределами нового корня штатными средствами файловой системы.

**История:** Механизм появился в 1979 году в Version 7 Unix. Это старейшая технология изоляции в Linux, ставшая концептуальным фундаментом для современных контейнеров (LXC, Docker).

**Capability `CAP_SYS_CHROOT`:** Начиная с Linux 2.2, для выполнения `chroot(2)` требуется наличие capability `CAP_SYS_CHROOT`. В большинстве дистрибутивов её имеет только root. Это ограничивает возможность использования `chroot` непривилегированными процессами, но не является механизмом безопасности — root может легко отменить ограничение.

**`openat2()` и защита от `..`:** Начиная с ядра 5.6, системный вызов `openat2()` с флагом `RESOLVE_NO_XDEV`/`RESOLVE_IN_ROOT` позволяет реализовать безопасную «песочницу» на уровне файловых дескрипторов, исключая path traversal через `..` даже в сценариях, где `chroot` может быть обойдён. Подробнее: [Kernel Interfaces](./kernel/kernel_interfaces.md).

---

## Основные концепции

### Механизм работы

При вызове `chroot(2)` ядро изменяет указатель на корневой каталог в дескрипторе процесса (`task_struct`). Все последующие операции поиска пути (path lookup), начинающиеся с `/`, будут ограничены новым поддеревом.

**Важно:** Chroot обеспечивает изоляцию **только на уровне файловой системы**. Все остальные ресурсы остаются общими с основной системой:
- **Сеть:** общие интерфейсы, IP-адреса и таблицы маршрутизации.
- **Процессы:** видны все процессы хоста (если смонтирован `/proc`).
- **Пользователи:** общая база UID/GID (ядро видит числовые ID).
- **Память:** механизмы IPC (Shared Memory, Semaphores) не изолированы.

Для полной изоляции ресурсов используются **[пространства имён (namespaces)](./namespaces.md)**.

**Детализация path lookup:**
1. Ядро получает запрос на открытие пути (например, `/etc/passwd`).
2. Оно конкатенирует `root` (новый корень chroot) с запрошенным путем.
3. Если процесс пытается открыть `../etc/passwd` из корня, ядро возвращает `..`, но не позволяет подняться выше нового корня.
4. Однако, если CWD процесса находится вне нового корня, `chdir("..")` может обойти это ограничение (см. раздел «Безопасность»).

### Сравнение механизмов смены корня

| Характеристика | chroot | pivot_root | switch_root |
| :--- | :--- | :--- | :--- |
| **Область действия** | Текущий процесс и потомки. | Весь Mount Namespace. | Текущий процесс (initramfs). |
| **Безопасность** | Root может «выпрыгнуть». | Полностью безопасно: старый корень отмонтирован. | Полностью безопасно: старый корень отмонтирован. |
| **Требования** | Любая директория. | Новая директория — точка монтирования. | Текущий корень должен быть tmpfs/ramfs. |
| **Применение** | Восстановление, сборка, FTP/DNS jails. | Контейнеризация (Docker, Podman, runc). | Переход от initramfs к реальной ФС. |

**`switch_root`:** Утилита из `busybox`/`util-linux`, используемая в initramfs. Удаляет старый корень (ramfs) и делает новый корень основным. Безопасна, так как старый корень находится в tmpfs и не содержит данных хоста.

### Сравнение: chroot vs unshare + chroot

Для повышения безопасности chroot часто комбинируют с `unshare`:

| Характеристика | chroot (простой) | unshare --mount --map-root-user + chroot |
| :--- | :--- | :--- |
| **Права** | Требует root. | Требует root (или user namespace). |
| **Изоляция** | Только ФС. | Mount Namespace + ФС. |
| **Побег** | Возможен через CWD. | Сложнее: нужно обойти mount namespace. |
| **Применение** | Быстрые задачи, rescue. | Service isolation, CI runners. |

### Безопасность и механизм «побега» (Escape)

**Chroot не является инструментом безопасности для root-пользователя.** При наличии прав `CAP_SYS_CHROOT` процесс может выйти в реальный корень системы.

**Техническая детализация Double Chroot Escape:**
Метод основан на том, что вызов `chroot()` изменяет корень, но **не изменяет текущую рабочую директорию (CWD)**, если она находится вне нового корня.
1. Процесс открывает файловый дескриптор текущего каталога (внутри тюрьмы).
2. Создает временную поддиректорию и делает в нее `chroot`. Теперь «настоящий» корень процесса находится глубоко внутри тюрьмы.
3. Однако CWD процесса всё еще указывает на старое местоположение (оригинальную тюрьму), которое теперь находится *выше* нового корня.
4. Процесс выполняет `chdir("..")` многократно. Поскольку ядро проверяет достижение корня только при сравнении пути с текущим корнем процесса, а CWD уже находится «снаружи», процесс может подняться до реального корня хоста и выполнить `chroot(".")`.

**Дополнительные векторы побега:**
- **Сетевые сокеты:** Если процесс имеет открытый сокет перед `chroot`, он может использовать его для передачи данных наружу.
- **Файловые дескрипторы:** Открытые дескрипторы (`/`, `/etc/passwd`) остаются валидными после `chroot`. Процесс может использовать `fchdir()` для навигации.
- **`/proc` и `/sys`:** Если смонтированы, через них можно получить информацию о хосте и открыть дескрипторы процессов хоста.
- **Setuid/setgid бинарники:** Внутри chroot setuid-root программы могут повышать привилегии, если chroot не настроен корректно.
- **Hardlinks и симлинки:** Hardlink на файл вне chroot сохраняется валидным. Симлинки, созданные внутри chroot, могут указывать за его пределы через абсолютные пути.

---

## Практические сценарии

### 1. Создание минимального окружения (ldd-метод)

Для запуска программы необходимо скопировать исполняемый файл и все его динамические зависимости.

```bash
# 1. Подготовка структуры
mkdir -p /opt/mini-chroot/{bin,lib,lib64}

# 2. Копирование bash и библиотек
cp /bin/bash /opt/mini-chroot/bin/
# Поиск зависимостей через ldd
ldd /bin/bash | grep -o '/lib.*\.[0-9]*' | xargs -I {} cp -v {} /opt/mini-chroot{}

# 3. Вход в окружение
sudo chroot /opt/mini-chroot /bin/bash
```

### 2. Подготовка полноценного окружения (Rescue)

Типичный сценарий для восстановления загрузчика или сброса пароля.

```bash
# 1. Монтирование основной системы
sudo mount /dev/sda1 /mnt

# 2. Проброс интерфейсов ядра (Bind Mount)
# Необходимо для работы пакетных менеджеров и взаимодействия с железом
for dir in dev dev/pts proc sys run; do
    sudo mount --bind /$dir /mnt/$dir
done

# 3. Вход
sudo chroot /mnt /bin/bash

# 4. Очистка (после выхода из chroot)
# Важно: размонтировать в обратном порядке перед удалением/отключением диска
```

### 3. Кросс-архитектурный chroot (QEMU)

Позволяет запускать окружения других архитектур (например, ARM на x86_64).

```bash
# 1. Установка эмулятора
sudo apt install qemu-user-static

# 2. Копирование эмулятора в корень будущей системы
cp /usr/bin/qemu-arm-static /mnt/arm-root/usr/bin/

# 3. Вход (ядро будет использовать binfmt_misc для вызова QEMU)
sudo chroot /mnt/arm-root /bin/bash
```

### 4. Автоматизация через debootstrap (Debian/Ubuntu)

Создание чистого базового образа системы в один шаг.
```bash
sudo debootstrap --arch amd64 bookworm /opt/debian-chroot http://deb.debian.org/debian
```

### 5. Изоляция сервисов (FTP, DNS, Web)

Chroot используется для ограничения доступа сервисов к части файловой системы. Пример: `vsftpd` с `chroot_local_user=YES`.

```bash
# 1. Подготовка структуры для FTP-сервера
mkdir -p /srv/ftp/{bin,lib,lib64,etc}

# 2. Копирование необходимых бинарников (например, для ls, или statically linked)
cp /bin/ls /srv/ftp/bin/
ldd /bin/ls | grep -o '/lib.*\.[0-9]*' | xargs -I {} cp -v {} /srv/ftp{}

# 3. Настройка vsftpd.conf
cat <<EOF | sudo tee /etc/vsftpd.conf
listen=YES
anonymous_enable=NO
local_enable=YES
chroot_local_user=YES
allow_writeable_chroot=YES
EOF

# 4. Запуск
sudo systemctl restart vsftpd
```

**SRE-контекст:** Chroot для FTP/DNS изолирует пользовательские сессии и ограничивает доступ к конфиденциальным файлам хоста. Для production-сред рекомендуется комбинировать с **[пространствами имён (namespaces)](./namespaces.md)** или использовать `systemd-nspawn` для полной изоляции.

### 6. Сборочные окружения для пакетов (pbuilder, sbuild, mock)

В DevOps/SRE chroot используется для гарантированного воспроизводимого билда пакетов без «загадочных» зависимостей хоста.

```bash
# pbuilder (Debian/Ubuntu)
sudo pbuilder create --debootstrapopts --variant=buildd --distribution bookworm

# sbuild (Debian)
sudo sbuild-createchroot bookworm /srv/chroot/bookworm-amd64-sbuild http://deb.debian.org/debian

# mock (RPM-based)
sudo mock -r epel-9-x86_64 --init
sudo mock -r epel-9-x86_64 --shell
```

**Важно:** Эти инструменты автоматически монтируют `/proc`, `/sys`, `/dev` и используют `unshare` для изоляции. Не удаляйте файлы в `/var/cache/` во время работы — кэш используется запущенными процессами.

### 7. CI/CD раннер в chroot

Изоляция билд-шагов в GitLab CI / Jenkins без виртуальных машин.

```bash
# 1. Создание базового окружения через debootstrap
sudo debootstrap --arch amd64 bookworm /opt/ci-chroot http://deb.debian.org/debian

# 2. Установка зависимостей CI-раннера
sudo chroot /opt/ci-chroot apt update
sudo chroot /opt/ci-chroot apt install -y git build-essential python3

# 3. Запуск билд-шага в chroot (внутри pipeline)
sudo chroot /opt/ci-chroot /bin/bash -c "git clone https://github.com/org/repo.git && cd repo && make build"
```

**Hardening:** Для production-CI добавьте `--private-dev`, `--private-tmp`, смонтируйте только необходимые каталоги и используйте отдельный пользователь без прав sudo.

### 8. systemd-сервис в chroot

Запуск демона в chroot через systemd unit.

```ini
# /etc/systemd/system/myapp.service
[Unit]
Description=My App in Chroot
After=network.target

[Service]
Type=simple
ExecStartPre=/bin/mkdir -p /opt/myapp-chroot/{run,var/log}
ExecStartPre=/bin/mount --bind /opt/myapp-chroot /opt/myapp-chroot
ExecStart=/usr/sbin/chroot /opt/myapp-chroot /usr/bin/myapp
Restart=on-failure
User=appuser
Group=appgroup
RootDirectory=/opt/myapp-chroot
RootDirectoryStartOnly=yes

[Install]
WantedBy=multi-user.target
```

**Примечание:** Параметр `RootDirectory=` (systemd 229+) автоматически выполняет chroot перед запуском процесса. Убедитесь, что все пути в unit относительны корня chroot или абсолютные пути внутри него.

### 9. Непривилегированный chroot (User Namespaces)

Запуск chroot без прав root через User Namespace.

```bash
# 1. Создание структуры
mkdir -p /opt/unpriv-chroot/{bin,lib,lib64}

# 2. Копирование статического бинарника
cp /usr/bin/hello-static /opt/unpriv-chroot/bin/

# 3. Запуск через unshare
unshare --user --map-root-user --mount -- chroot /opt/unpriv-chroot /bin/hello-static
```

**Ограничение:** Привилегированные операции (монтирование, изменение сети) недоступны. Используется для тестирования и изоляции приложений без root.

### 10. Сеть + chroot (Network Namespace)

Комбинация Network Namespace и chroot для полной изоляции сервиса.

```bash
# 1. Создание сетевого namespace
sudo ip netns add isolated-ns

# 2. Создание пары veth
sudo ip link add veth-host type veth peer name veth-guest
sudo ip link set veth-host netns isolated-ns
sudo ip netns exec isolated-ns ip addr add 10.200.1.1/24 dev veth-guest
sudo ip netns exec isolated-ns ip link set veth-guest up

# 3. На хосте: поднятие интерфейса
sudo ip addr add 10.200.1.2/24 dev veth-host
sudo ip link set veth-host up

# 4. Запуск процесса в namespace + chroot
sudo ip netns exec isolated-ns chroot /opt/service-chroot /usr/bin/myapp
```

**SRE-контекст:** Подходит для изоляции legacy-сервисов, которым не требуется полный контейнер, но нужна отдельная сетевая среда и доступ только к собственным файлам.

---

## Дополнительная информация

### Продвинутые инструменты

- **`schroot`**: Позволяет обычным пользователям входить в chroot-окружения с автоматическим монтированием `/proc`, `/home` и управлением сессиями.
- **`fakechroot`**: Библиотека, подменяющая системные вызовы работы с файлами. Позволяет имитировать chroot без прав root (используется вместе с `fakeroot`).
- **`bubblewrap` (`bwrap`)**: Современный инструмент для непривилегированной изоляции, использующий namespaces (используется во Flatpak).
- **`proot`**: Эмуляция chroot без root через `ptrace`. Медленнее, но работает в lock-даунах (LXC без привилегий, WSL).
- **`systemd-nspawn`**: «Chroot на стероидах» с полной изоляцией через namespaces и cgroups. Рекомендуется для production-сервисов вместо простого chroot. Подробнее: [Systemd-nspawn](./systemd/nspawn.md).

### Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `chroot: failed to run command ‘/bin/bash’: No such file or directory` | Отсутствуют необходимые библиотеки внутри корня. | Проверьте зависимости через `ldd` и наличие `ld-linux.so`. |
| `sudo` не работает внутри | Файловая система смонтирована с опцией `nosuid`. | Перемонтируйте с `suid`. |
| Сеть недоступна | Файл `/etc/resolv.conf` отсутствует или некорректен. | Скопируйте `/etc/resolv.conf` с хоста в chroot. |
| `Permission denied` при монтировании `/proc` | Попытка монтирования без root-прав. | Выполните chroot от root или используйте `--bind` с правильными правами. |
| Ошибки SELinux (`avc: denied`) | Контексты файлов в chroot не соответствуют политикам. | Выполните `restorecon -R /opt/chroot` или смонтируйте с `context=system_u:object_r:default_t:s0`. |
| 32-битные библиотеки на 64-битной системе | Установлен только `libc6:amd64`, а бинарник требует `i386`. | Добавьте `dpkg --add-architecture i386 && apt update` и установите зависимости. |
| Нет устройства `/dev/null` | `devtmpfs` не смонтирован внутри chroot. | Смонтируйте: `mount --bind /dev /mnt/dev` или создайте `mknod`. |
| `No PTY allocated` | Отсутствует `/dev/pts` или `/dev/ptmx`. | Смонтируйте `devpts`: `mount -t devpts devpts /mnt/dev/pts`. |
| Setuid/setgid не работает | `/` смонтирован с `nosuid` или `chmod u-s` на бинарник. | Уберите `nosuid`, проверьте права на бинарник. |
| `/proc` показывает PID хоста | `/proc` смонтирован из хоста. | Это нормально для простого chroot. Для изоляции используйте Mount Namespace: `unshare --mount --mount-proc /mnt/proc chroot /mnt`. |

### Best Practices

1. **Минимизируйте окружение:** Включайте в chroot только необходимые бинарники и библиотеки. Используйте `ldd` для выявления зависимостей.
2. **Только чтение (Read-only):** Монтируйте корень chroot с `ro` wherever possible. Это снижает риски компрометации.
3. **Ограничьте `/proc`:** Монтируйте с опциями `hidepid=2` для скрытия PID других процессов хоста.
4. **Отсутствие устройств:** Не включайте `/dev` в chroot, если сервис не требует прямого доступа к железу. Используйте bind-монтирование только необходимых узлов.
5. **Удалите setuid-бинарники:** В chroot для сервисов удалите или отключите setuid/setgid, если это возможно.
6. **Аудит:** Логируйте входы в chroot через `auditd` или journald. Настройте `loginctl` для отслеживания сессий.
7. **Очистка:** После работы в rescue-chroot всегда размонтируйте каталоги в обратном порядке перед отключением диска.
8. **Автоматизация:** Используйте `debootstrap`/`pbuilder`/`mock` вместо ручного копирования библиотек — это исключает человеческие ошибки.
9. **Проверяйте целостность:** Используйте `debsums` (Debian) или `rpm -Va` (RPM) для проверки файлов внутри chroot после сборки.
10. **Change Management:** Любое изменение внутри chroot должно быть задокументировано и воспроизводимо (Ansible playbook, Dockerfile или debootstrap config).

### Граничные случаи и ограничения

- **Открытые дескрипторы до chroot:** Файловые дескрипторы, открытые процессом *до* вызова `chroot()`, остаются валидными и указывают на реальные файлы хоста. Процесс может использовать `fchdir()` для навигации «наружу».
- **Hardlink на файлы вне chroot:** Hardlink сохраняет связь с исходным inode, даже если исходный файл находится вне нового корня. Это позволяет читать/писать файлы хоста изнутри «тюрьмы».
- **Setuid/setgid внутри chroot:** Если внутри chroot присутствуют setuid/setgid-бинарники и chroot не настроен с отключением `nosuid`, они будут работать. Однако root внутри chroot имеет UID 0 хоста, что повышает риски при компрометации.
- **Вложенный chroot:** Возможен, но каждый уровень добавляет сложность. Если внутренний chroot скомпрометирован, злоумышленник получает доступ к промежуточному уровню, а не сразу к хосту.
- **Удаление корня chroot:** Если удалить директорию, используемую как chroot, пока в ней работают процессы, они продолжат функционировать (inode остается занят). Однако новые процессы войти не смогут.
- **Mount Propagation:** Если chroot выполнен без изолированного Mount Namespace, события монтирования хоста (например, `mount --bind /host/secret /mnt/chroot/tmp`) автоматически прокидываются внутрь chroot.
- **/proc и PID Namespace:** Если `/proc` смонтирован из хоста, внутри chroot видны все PID хоста. Для изоляции PID требуется отдельный PID Namespace (`unshare --pid --mount-proc /mnt/proc chroot /mnt`).
- **SELinux enforcing:** На RHEL/Fedora с включенным SELinux файлы внутри chroot могут иметь некорректные контексты. Используйте `restorecon -R /path/to/chroot` или монтирование с опцией `context=`.
- **/dev и devtmpfs:** Если `devtmpfs` не проброшен, внутри chroot отсутствуют узлы устройств. Создавайте минимальные узлы через `mknod` или bind-монтируйте `/dev`.
- **Read-only rootfs:** Chroot на корневой раздел, смонтированный как `ro`, работает только для чтения. Для записи требуется отдельный tmpfs или bind-монтирование writable-директорий.

### Связанные темы

- **[Пространства имён (namespaces)](./namespaces.md)** — механизм глубокой изоляции (включая Mount Namespace).
- **[Пространства имён монтирования](../Virtualization/mount_namespaces.md)** — детали propagation, pivot_root и New Mount API.
- **[Systemd-nspawn](./systemd/nspawn.md)** — «chroot на стероидах» с использованием namespaces и cgroups.
- **[Восстановление пароля root](../SystemAdministration/linux_password_recovery.md)** — применение chroot в аварийных ситуациях.
- **[Восстановление системы при сбоях загрузки](../Diagnostics/Troubleshooting/boot_failure_recovery.md)** — стратегии LiveCD и chroot.
- **[Изоляция в Linux: Namespaces и Cgroups](../../Docker/Concepts/linux_isolation.md)** — контекст контейнеризации.
