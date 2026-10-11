# Пользовательские профили безопасности (AppArmor, SELinux, seccomp)

**Актуально для:** Docker Engine 29.x, AppArmor 4.x/5.x, SELinux (RHEL 9/Fedora/RHEL 10), seccomp (libseccomp 2.6+). Теория LSM и ручных профилей — SSoT в [AppArmor](../../Linux/Security/Mechanisms/AppArmor.md) и [Seccomp](../../Linux/Security/Mechanisms/Seccomp.md); capabilities — в [Capabilities](../../Linux/Security/Mechanisms/Capabilities.md). Данный файл — Docker-специфичная практика: написание, загрузка и отладка профилей для контейнеров.

## Определения

**LSM (Linux Security Module)** — фреймворк мандатного контроля доступа (MAC) в ядре: AppArmor, SELinux, Smack. Работает поверх capabilities: даже процесс с `CAP_SYS_ADMIN` блокируется LSM, если политика запрещает действие.

**docker-default** — профиль AppArmor, который Docker автоматически назначает каждому контейнеру (если не указан другой). Блокирует монтирование, ptrace, запись в `/proc` и др.

**container_t** — SELinux-тип, назначаемый процессам контейнера. Изоляция через labels: контейнер не может читать файлы хоста без нужного контекста.

**seccomp-профиль** — JSON-фильтр системных вызовов: `defaultAction` для всех syscall'ов + список исключений. Docker по умолчанию блокирует ~44 опасных syscall'а (mount, kexec, ptrace, reboot и др.), включая `AF_ALG` и `socketcall` (CVE-2026-31431).

**audit2allow / audit2seccomp** — утилиты генерации политик из auditd-логов: первая создаёт SELinux-модуль, вторая — seccomp-профиль.

## Предварительные требования

**Пакеты (Debian/Ubuntu):**
```bash
sudo apt-get install -y apparmor-utils libseccomp-tools strace auditd
# Для SELinux:
sudo apt-get install -y policycoreutils-python-utils selinux-utils
```

**Пакеты (RHEL/Fedora):**
```bash
sudo dnf install -y apparmor-utils libseccomp-tools strace audit
# Для SELinux:
sudo dnf install -y policycoreutils-python-utils policycoreutils
```

**Ядро и рантайм:**
- Linux 5.4+ с включёнными LSM (проверка: `cat /sys/kernel/security/lsm`).
- Docker Engine 29.x с демоном, запущенным с привилегиями `root` (требуется для загрузки AppArmor/SELinux-политик).
- AppArmor 4.x/5.x: на Ubuntu 24.04/26.04, Debian 12+ по умолчанию; профили `docker-default` загружаются автоматически.
- SELinux: enforcing/permissive в `/etc/selinux/config`; пакет `container-selinux` установлен.
- libseccomp 2.6+ для корректной работы с новыми syscall'ами (landlock, mseal и др.).

**Проверка окружения:**
```bash
# LSM, загруженные в ядро:
cat /sys/kernel/security/lsm
# → capability userland apparmor

# AppArmor:
sudo aa-status | grep docker
# → docker-default (enforced)

# SELinux:
sestatus
# → Current mode: enforcing

# seccomp:
docker info --format '{{.SecurityOptions}}'
# → seccomp,apparmor,no-new-privileges
```

## Базовые концепции

### Три уровня защиты и их границы

| Уровень | Что ограничивает | Docker-флаг | Отключается ли |
| :--- | :--- | :--- | :--- |
| **Capabilities** | Привилегии процесса (root → набор прав) | `--cap-drop` / `--cap-add` | Да, `--privileged` возвращает все |
| **seccomp** | Доступные syscall'ы | `--security-opt seccomp=` | Да, `--privileged` или `unconfined` |
| **LSM (AppArmor/SELinux)** | Доступ к файлам/сетям/операциям по политике | `--security-opt apparmor=` / `label=` | `--privileged` снимает ограничения |

Ключевой принцип: уровни **независимы и дополняют друг друга**. `--cap-drop=ALL` не заменяет seccomp (процесс всё ещё может вызывать разрешённые syscall'и), а seccomp не заменяет LSM (разрешённый syscall всё равно проверяется политикой доступа).

### Почему нужны пользовательские профили

`docker-default` и seccomp-default — универсальные: они блокируют очевидно опасное, но разрешают всё остальное. Пользовательский профиль сужает до конкретного приложения: nginx не нужен `ptrace`, БД не нужен `mount`, а batch-приложению — сеть. Это реализация принципа наименьших привилегий на уровне ядра.

## Практические сценарии

### Сценарий 1: пользовательский профиль AppArmor

**Шаг 1 — написать профиль** (Docker-стиль, абстракции `@{docker_*}` доступны при загруженном docker-default):

```
# /etc/apparmor.d/docker-nginx
#include <tunables/global>

profile docker-nginx flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>

  # Сеть: только исходящие HTTP/HTTPS
  network inet stream,
  network inet6 stream,

  # ФС: чтение конфигов и контента, запись только в логи/кэш
  /etc/nginx/** r,
  /usr/share/nginx/** r,
  /var/log/nginx/** rw,
  /var/cache/nginx/** rw,

  # Запрет монтирования и отладки
  deny mount,
  deny ptrace,
  deny /proc/sys/** rw,
}
```

**Шаг 2 — загрузить и применить:**

```bash
sudo apparmor_parser -r /etc/apparmor.d/docker-nginx
# Проверка загрузки:
sudo aa-status | grep docker-nginx
# → docker-nginx

docker run --security-opt apparmor=docker-nginx -d nginx
# Профиль должен быть загружен ДО старта контейнера, иначе dockerd откажет
```

**Шаг 3 — отладка:** нарушения пишутся в `dmesg`/`/var/log/syslog` (`apparmor="DENIED"`); режим логирования без блокировки — `flags=(complain)` вместо `enforce`.

Теория и абстракции — в [AppArmor](../../Linux/Security/Mechanisms/AppArmor.md).

### Сценарий 2: пользовательская политика SELinux

**Шаг 1 — собрать denials:**

```bash
sudo ausearch -m avc -ts recent | grep container_t
# → type=AVC msg=... denied={ name_write } ... scontext=system_u:system_r:container_t:s0:c123
```

**Шаг 2 — сгенерировать и загрузить модуль:**

```bash
sudo ausearch -m avc -ts recent | audit2allow -M mycontainer
# → mycontainer.te, mycontainer.pp
sudo semodule -i mycontainer.pp
```

**Шаг 3 — применить к контейнеру:**

```bash
# Контейнеры автоматически получают тип container_t; 
# для отключения MAC (НЕ рекомендуется — снимает изоляцию):
docker run --security-opt label=disable ...
# Для релейблирования томов при монтировании:
docker run -v /data:/data:Z ...
```

**Проверка контекста:**

```bash
ls -Z /var/lib/docker/containers/
# → system_u:object_r:container_file_t:s0:c123,c456 ...
```

### Сценарий 3: пользовательский seccomp-профиль

**Шаг 1 — определить нужные syscall'ы.** Запустить контейнер под `strace` (или использовать auditd + `audit2seccomp`):

```bash
strace -f -c -o syscalls.log docker run --rm my-app
# → список syscall'ов, реально используемых приложением
```

**Важно:** Docker Engine 29.x по умолчанию блокирует `AF_ALG` и `socketcall` (CVE-2026-31431, "Copy Fail") в дополнение к ~44 стандартным syscall'ам. При генерации профиля через `audit2seccomp` убедитесь, что эти вызовы НЕ попали в allowlist. Если приложению требуется доступ к AF_ALG — используйте профиль `seccomp/v0.2.1` из `moby/profiles` только для конкретного контейнера с явным `--security-opt seccomp=seccomp/v0.2.1.json`.

**Шаг 2 — написать профиль:**

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "defaultErrnoRet": 1,
  "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_X86", "SCMP_ARCH_X32"],
  "syscalls": [
    {
      "names": ["accept4", "arch_prctl", "bind", "brk", "clock_gettime",
                "close", "connect", "epoll_create1", "epoll_ctl", "epoll_wait",
                "exit_group", "fstat", "getdents64", "getpid", "getsockname",
                "getsockopt", "ioctl", "listen", "lseek", "madvise", "mmap",
                "mprotect", "munmap", "newfstatat", "openat", "pread64",
                "pwrite64", "read", "readlink", "recvfrom", "rt_sigaction",
                "rt_sigprocmask", "sendto", "setsockopt", "set_tid_address",
                "socket", "write"],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

**Шаг 3 — применить:**

```bash
docker run --security-opt seccomp=custom.json my-app
# При ошибке EPERM в логах приложения — syscall не в whitelist: 
# добавить в "names" и перезапустить
```

**Генерация из auditd:** `ausearch -sc -i | audit2seccomp > profile.json` — создаёт профиль из наблюдавшихся syscall'ов. Ручные профили и CIL-вариант — в [Seccomp](../../Linux/Security/Mechanisms/Seccomp.md).

### Сценарий 4: комбинированная конфигурация production-контейнера

```bash
docker run -d \
  --security-opt no-new-privileges \
  --security-opt apparmor=docker-nginx \
  --security-opt seccomp=custom.json \
  --cap-drop=ALL --cap-add=NET_BIND_SERVICE \
  --read-only --tmpfs /tmp:rw,noexec,nosuid \
  --user 10001:10001 \
  -p 8080:80 nginx
```

Проверка применённых профилей:

```bash
docker inspect <container> --format '{{.AppArmorProfile}} {{.HostConfig.SecurityOpt}}'
# → docker-nginx [no-new-privileges seccomp=custom.json]
```

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `docker: Error response from daemon: profile not found` | Профиль AppArmor не загружен | `sudo apparmor_parser -r /etc/apparmor.d/<profile>`; проверить `aa-status` |
| Контейнер падает с `permission denied` | Профиль слишком строгий (файл/syscall не разрешён) | AppArmor: `dmesg \| grep DENIED`, перевести профиль в `complain`; seccomp: `EPERM` в логах приложения — добавить syscall в whitelist |
| SELinux: контейнер не читает том | Метка файла не соответствует `container_file_t` | Перемонтировать с `:Z` (релейблинг) или `:z` (shared context) |
| `--security-opt label=disable` не работает | SELinux отключён на хосте | `sestatus`; включить `SELINUX=enforcing` в `/etc/selinux/config` |
| seccomp-профиль отклонён при старте | Невалидный JSON или неизвестный syscall | `docker run --security-opt seccomp=profile.json` вернёт ошибку парсинга; проверить имена syscall'ов через `ausyscall --dump` |
| Профиль не блокирует ожидаемое действие | Действие разрешено абстракцией (`#include <abstractions/base>`) | Уточнить правила после include; проверить `aa-status` на наличие профиля в enforce-режиме |

## Лучшие практики

1. **Начинайте с complain-режима** (AppArmor) или с полного seccomp-allowlist из `strace` — затем сужайте. Профиль, написанный «с нуля», почти всегда ломает приложение.
2. **Генерируйте из наблюдений, а не из документации.** `strace`/`auditd` + `audit2allow`/`audit2seccomp` дают реальный набор syscall'ов; ручной список — источник ошибок.
3. **Один профиль — одно приложение.** Профиль для nginx не подходит для БД; не используйте «универсальный» профиль для всех контейнеров.
4. **Не отключайте LSM** (`label=disable`, `apparmor=unconfined`) без крайней необходимости — это снимает последний уровень изоляции.
5. **Тестируйте профили в CI.** Запуск контейнера с профилем в тестовом окружении ловит регрессии до production.
6. **Комбинируйте уровни.** capabilities + seccomp + LSM + read-only FS — каждый уровень перекрывает обход предыдущего.
7. **Версионируйте профили** вместе с приложением: профиль в репозитории, загрузка через конфигурацию хоста (Ansible/Chef), а не вручную.
8. **Используйте `no-new-privileges` по умолчанию.** Этот флаг запрещает повышение привилегий через setuid/setgid внутри контейнера и требуется для корректной работы seccomp с `no_new_privs` в ядре.
9. **Не полагайтесь только на `--cap-drop=ALL`.** Capabilities не заменяют seccomp и LSM: даже без `CAP_SYS_ADMIN` процесс может вызвать разрешённый syscall, который seccomp или LSM должен блокировать.
10. **Мониторьте denials через SIEM.** AppArmor (`audit="DENIED"`) и SELinux (`avc: denied`) должны попадать в centralized logging (ELK, Loki, Splunk) с алертами на подозрительные повторяющиеся нарушения.
11. **Для BuildKit используйте изолированный builder.** CVE-2026-61711: кастомный frontend может отключить Seccomp/AppArmor. Builder с `docker-container` driver и отдельной политикой LSM снижает риск.
12. **Обновляйте AppArmor и libseccomp вместе с ядром.** AppArmor 5.0 (апрель 2026) ввёл новый формат политик; старые профили без обратной совместимости могут требовать перезаписи. libseccomp 2.6.1 (июль 2026) исправляет двойную запись в фильтрах и heap corruption.

## Дополнительная информация

### Ограничения и граничные случаи

- **AppArmor 4.x/5.x policy format.** AppArmor 5.0 (апрель 2026) ввёл новый синтаксис политик, несовместимый с AppArmor 3.x. Профили, написанные для Ubuntu 22.04 (AppArmor 3.x), могут требовать адаптации для Ubuntu 26.04 (AppArmor 5.0.2). Проверяйте `apparmor_parser --version` на целевом хосте.
- **Docker Desktop и WSL2.** В Docker Desktop для macOS/Windows AppArmor/SELinux не применяются (Windows использует Hyper-V, macOS — hypervisor.framework). Локальная разработка не покрывается этими профилями.
- **SELinux: контекст тома при перезагрузке.** После `:Z`/`:z` релейблинга перезагрузка хоста не восстанавливает исходные контексты; при повторном монтировании используйте `:Z` снова или фиксируйте контекст через `semanage fcontext`.
- **`--privileged` отключает все уровни.** Флаг возвращает все capabilities, снимает seccomp и LSM. Даже кастомный AppArmor-профиль игнорируется; контейнер получает полный доступ к устройствам хоста.
- **seccomp и 32-bit программы.** На архитектурах x86/x32 `socketcall(2)` — мультиплексер; seccomp не может эффективно фильтровать аргументы по `socketcall`. Для 32-bit контейнеров используйте AppArmor/SELinux или кастомный профиль с явным блокированием `socketcall`.
- **`no_new_privs` и SUID-бинарники.** Seccomp-фильтр требует `no_new_privs` (устанавливается автоматически Docker). SUID-бинарник, запущенный через `execve`, не получит новых привилегий, но seccomp останется активным — это ожидаемое поведение, а не баг.
- **AppArmor в complain-режиме в production.** Режим `complain` логирует нарушения без блокировки. Используйте только для отладки: в production enforce-режим обязателен, иначе профиль не защищает.
- **Кэш AVC в SELinux.** После загрузки модуля `audit2allow` проверьте `getenforce` и `sesearch`: кэшированные denials могут продолжаться до перезагрузки или `restorecon -R -v /`.

**Связанные документы:**

- [AppArmor: механизм](../../Linux/Security/Mechanisms/AppArmor.md) — SSoT: теория, docker-default, абстракции.
- [Seccomp: механизм](../../Linux/Security/Mechanisms/Seccomp.md) — SSoT: ручные JSON/CIL-профили, audit2seccomp, strace.
- [Capabilities](../../Linux/Security/Mechanisms/Capabilities.md) — SSoT: наборы прав, `--cap-drop`/`--cap-add`.
- [Укрепление контейнеров](./container_hardening.md) — применение профилей в контексте.
- [Укрепление хоста и демона](./host_daemon_hardening.md) — LSM на хосте.
- [CVE побегов из контейнеров](./container_escape_cves.md) — почему LSM не заменяет патчинг рантайма.
- [Buildx builder security](./buildx_builder_security.md) — CVE-2026-61711/15792: frontend, отключающий LSM.

**Внешние ресурсы:**

- [Docker security options](https://docs.docker.com/security/) — `--security-opt` и профили.
- [AppArmor wiki](https://gitlab.com/apparmor/apparmor/-/wikis) — синтаксис профилей.
- [SELinux Project](https://github.com/SELinuxProject) — политики и audit2allow.
- [libseccomp](https://github.com/seccomp/libseccomp) — API фильтрации syscall'ов.
- [moby/profiles](https://github.com/moby/profiles) — стандартные seccomp-профили Docker, включая `seccomp/v0.2.1` для CVE-2026-31431.
- [CVE-2026-31431 / "Copy Fail"](https://copy.fail) — детали эксплуатации через AF_ALG.

**Инструменты:** `apparmor_parser`, `aa-status`, `audit2allow`, `audit2seccomp`, `strace`, `ausearch`, `sestatus`, `ausyscall`.
