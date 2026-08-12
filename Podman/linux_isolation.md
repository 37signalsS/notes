# Изоляция в Podman

## Определения

**Изоляция Podman** — это комплексный механизм обеспечения безопасности, использующий примитивы ядра Linux для создания изолированных сред выполнения процессов. В отличие от Docker, Podman реализует модель **daemonless** и **rootless**, что вносит существенные изменения в способы применения пространств имен (namespaces) и контрольных групп (cgroups). Начиная с Podman 6.0 для работы обязательна поддержка **Cgroups v2** (унифицированной иерархии): поддержка cgroups v1 полностью удалена.

**OCI Runtime (Среда выполнения)** — низкоуровневая утилита (например, `crun` или `runc`), которая непосредственно взаимодействует с ядром для настройки изоляции. Podman по умолчанию использует **`crun`**, так как он написан на C, обладает меньшим потреблением памяти и лучшей поддержкой cgroups v2. `runc` остается доступной альтернативой для проверки совместимости.

**conmon (Container Monitor)** — легковесная утилита, которая сопровождает жизненный цикл контейнера. Она отвечает за сбор логов, мониторинг процесса контейнера и удержание открытых дескрипторов после того, как CLI-процесс Podman завершится.

---

## Основные концепции

### Пространства имен (Namespaces) в Podman

Podman изолирует контейнеры с помощью следующих пространств имен. Значения по умолчанию задаются в `containers.conf` (секция `[containers]`):

- **User Namespace (Критично для Rootless):** Позволяет мапировать UID 0 (root) внутри контейнера на UID обычного пользователя на хосте. Это предотвращает "побег" из контейнера с правами суперпользователя.
    - **Rootless:** приватное User Namespace создается всегда и безусловно (иначе rootless-режим невозможен).
    - **Rootful:** по умолчанию контейнеры используют host User Namespace (`userns="host"` в `containers.conf`), приватное пространство включается флагом `--userns=private` / `--userns=auto` / `--userns=keep-id`.
- **Network Namespace:** Изолирует сетевой стек.
    - **Rootless:** используется **`pasta`** (по умолчанию с Podman 5.0; единственный вариант в Podman 6.0, обеспечивает высокую производительность без NAT и сохраняет исходный IP отправителя). `slirp4netns` был драйвером по умолчанию до Podman 5.0, оставался альтернативой в 5.x и полностью удален в Podman 6.0.
    - **Rootful:** используется **`Netavark`** (создание мостов, маршрутизация и правила файрвола) в паре с **`Aardvark`** (встроенный DNS-резолвер). Начиная с Podman 6.0 файрвол настраивается только через **nftables** (поддержка iptables удалена), а сетевой бэкенд CNI больше не поддерживается.
- **PID Namespace:** Изолирует дерево процессов. Контейнер видит только свои процессы, начиная с PID 1. По умолчанию для каждого контейнера создается приватное PID Namespace (`pidns="private"`).
- **Mount Namespace:** Изолирует точки монтирования. Поддерживается `fuse-overlayfs` для реализации слоев в rootless-режиме без прав root.
- **UTS Namespace:** Изолирует hostname и домен узла. По умолчанию приватный (`utsns="private"`), поэтому каждый контейнер может иметь собственный hostname (по умолчанию — первые 12 символов ID контейнера). Отключение — `--uts=host`.
- **IPC Namespace:** Изолирует межпроцессное взаимодействие (разделяемую память, очереди сообщений, семафоры). По умолчанию `ipcns="shareable"` (приватное пространство без собственного `/dev/shm`), полная изоляция с отдельным `/dev/shm` — `--ipc=private`.
- **Cgroup Namespace:** Скрывает иерархию контрольных групп хоста из `/proc/self/cgroup`. На cgroups v2 по умолчанию приватный (`cgroupns="private"`), на cgroups v1 (устаревшей) — `host`.
- **TIME / Timezone:** отдельное Time Namespace (`CLONE_NEWTIME`) Podman по умолчанию не создает, однако часовой пояс внутри контейнера настраивается независимо от хоста через флаг `--tz=local` (или значение IANA-зоны) и опцию `tz` в `containers.conf`.

### Контрольные группы (Cgroups v2)

Podman полностью оптимизирован для **Cgroup v2** (унифицированная иерархия). Начиная с Podman 6.0 хост с cgroups v1 не поддерживается вовсе — все контроллеры работают через единое дерево `/sys/fs/cgroup`.

В отличие от Docker, который может управлять группами напрямую, Podman по умолчанию делегирует управление **`systemd`** (менеджер `systemd`), а в rootless-режиме — через `systemd --user`. Альтернативный менеджер `cgroupfs` доступен, но не рекомендован, так как ломает интеграцию с systemd и мешает корректному учету ресурсов.

**Преимущества интеграции с systemd:**
- Совместное использование ресурсов контейнерами и системными сервисами без конфликтов (контейнеры попадают в `system.slice` / `user.slice`).
- Использование `systemctl` и `systemd-cgtop` для анализа потребления.
- Корректное распределение весов CPU и лимитов памяти на уровне сессии пользователя (для rootless — через делегирование cgroup подконтрольных `systemd --user`).
- Возможность проверки менеджера и версии: `podman info --format '{{.Host.CgroupManager}}'` и `podman info --format '{{.Host.CgroupsVersion}}'`.

### Дополнительные уровни защиты

1. **SELinux:** Podman автоматически назначает уникальные MCS-метки контейнерам (например, `container_t`, `container_file_t`). Это предотвращает доступ одного контейнера к файлам другого, даже если оба запущены от одного UID. Для томов используются суффиксы монтирования `:Z` (переконтекстная маркировка, общая для контейнеров) и `:z` (индивидуальная маркировка каталога).
2. **AppArmor:** Используется в дистрибутивах на базе Debian/Ubuntu для ограничения возможностей процессов через профили безопасности (по умолчанию применяется профиль `containers-default`).
3. **Seccomp (Secure Computing Mode):** Фильтрация системных вызовов. По умолчанию Podman применяет профиль из `/usr/share/containers/seccomp.json` (переопределяется файлом `/etc/containers/seccomp.json`), который запрещает более 30 системных вызовов независимо от выданных Capabilities (например, `swapon`, `swapoff`, `kexec_load`, `userfaultfd`, `vm86`). Некоторые вызовы блокируются условно — только при отсутствии определенной Capability: так, `mount` доступен профилем лишь с `CAP_SYS_ADMIN`, который по умолчанию не выдается. `ptrace` также разрешен только с `CAP_SYS_PTRACE`.
4. **Capabilities:** Linux-привилегии разбиты на мелкие части. Текущий набор по умолчанию (containers-common): `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `FSETID`, `KILL`, `NET_BIND_SERVICE`, `SETFCAP`, `SETGID`, `SETPCAP`, `SETUID`, `SYS_CHROOT`. При этом по умолчанию **не выдаются** опасные `SYS_ADMIN`, `SYS_MODULE`, `NET_ADMIN`, `SYS_TIME`, `MKNOD`, `AUDIT_WRITE`, а также `NET_RAW` (исключен из списка по умолчанию в актуальных версиях — для `ping` его нужно добавлять вручную через `--cap-add=NET_RAW`).
5. **Защита псевдо-файловых систем:** Podman маскирует чувствительные пути (`/proc/kcore`, `/proc/keys`, `/sys/firmware` и др. — список `maskedPaths`), а `/proc/sys`, `/proc/bus`, `/proc/fs` монтируются в режиме только для чтения (`readonlyPaths`). Это закрывает распространенные утечки информации о хосте.

---

## Практические сценарии

### 1. Вход в пространство имен пользователя (troubleshooting)

Если в rootless-режиме возникают ошибки доступа к файлам на хосте (Permission Denied), используйте `podman unshare`. Эта команда запускает shell в том же User Namespace, в котором работают контейнеры.

```bash
# Проверка текущего маппинга UID
podman unshare cat /proc/self/uid_map
# → 0       1000          1    (Root в контейнере == UID 1000 на хосте)
# → 1     100000      65536    (Остальные UID — из диапазона /etc/subuid)

# Исправление прав на директорию для контейнера
podman unshare chown -R 0:0 ./my-app-data
```

### 2. Смена среды выполнения (OCI Runtime)

Вы можете переключиться между `crun` (быстрее) и `runc` (стандарт de-facto) для проверки совместимости.

```bash
# Запуск с использованием runc
podman run --runtime /usr/bin/runc -it alpine sh

# Проверка текущего рантайма по умолчанию
podman info --format '{{.Runtime.Name}}'
# → crun
```

### 3. Настройка сетевой изоляции (Pasta)

В Podman 5.0+ `pasta` — драйвер сети по умолчанию для rootless-контейнеров, а в Podman 6.0 — единственный (slirp4netns удален). Pasta не использует NAT, копирует IP-адреса с основного интерфейса хоста и поэтому не имеет накладных расходов на трансляцию пакетов.

```bash
# Явное использование pasta (по умолчанию в 5.0+)
podman run --network=pasta nginx

# Передача опций pasta через запятую: маппинг шлюза хоста
# (доступ из контейнера к сервисам на localhost хоста)
podman run --network=pasta:--map-gw nginx

# Принудительный выбор интерфейса хоста, с которого копируются IP
podman run --network=pasta:-i,wlp2s0 nginx
```

**Примечание:** при rootless-сети из контейнера хост доступен по имени `host.containers.internal` (169.254.1.2). Запретить доступ к хосту можно опцией pasta `--map-guest-addr none`.

### 4. Ограничение системных вызовов (Seccomp)

Если приложению нужен специфический системный вызов, заблокированный по умолчанию, можно добавить свой профиль или отключить фильтрацию.

```bash
# Запуск с кастомным профилем seccomp
podman run --security-opt seccomp=/path/to/my-profile.json my-app

# Отключение seccomp для отладки (небезопасно!)
podman run --security-opt seccomp=unconfined my-app

# Проверка, что seccomp включен на хосте
podman info --format '{{.Host.Security.SECCOMPEnabled}}'
# → true
```

### 5. Управление Capabilities (минимальный набор прав)

Частый источник ошибок `operation not permitted` — отсутствие нужной Capability. Правильный подход — запускать контейнер с минимальным набором и добавлять только необходимое.

```bash
# Просмотр фактического набора capabilities внутри контейнера
podman exec -it <container> capsh --print

# Запуск вообще без capabilities
podman run --cap-drop=all my-app

# Запуск без всего + добавление только нужного
podman run --cap-drop=all --cap-add=NET_BIND_SERVICE --cap-add=CHOWN nginx

# Для ping внутри контейнера (NET_RAW не входит в defaults)
podman run --cap-add=NET_RAW alpine ping 8.8.8.8
```

### 6. Сохранение UID/GID при монтировании томов (--userns=keep-id)

При rootless-запуске UID внутри контейнера (например, 0) не совпадает с UID владельца каталога на хосте (например, 1000), что приводит к `Permission denied`. Режим `keep-id` мапирует текущего пользователя хоста на тот же UID/GID внутри контейнера.

```bash
# Файлы, создаваемые контейнером, будут принадлежать текущему пользователю хоста
podman run --userns=keep-id -v /home/user/project:/app user-image

# В rootful-режиме — аналогично, для запуска от root
sudo podman run --userns=keep-id -v /home/user/project:/app user-image
```

### 7. Диагностика уровня безопасности (podman info)

Быстрая проверка текущего состояния изоляции и настроенных механизмов защиты.

```bash
# Активные security-опции (seccomp, apparmor, label)
podman info --format '{{.SecurityOptions}}'
# → [seccomp=profileName apparmor=containers-default label=...]

# Rootless или rootful
podman info --format '{{.Host.Security.Rootless}}'
# → true

# Версия cgroups и менеджер
podman info --format '{{.Host.CgroupsVersion}} {{.Host.CgroupManager}}'
# → cgroupsv2 systemd

# Сетевой бэкенд и rootless-драйвер
podman info --format '{{.Host.NetworkBackend}}'
# → netavark
podman info --format '{{.Host.Pasta.Executable}}'
# → /usr/bin/pasta
```

---

## Дополнительная информация

### Связанные разделы

- **[Базовые механизмы изоляции в Linux](../Docker/Concepts/linux_isolation.md)** — общая теория Namespaces и Cgroups.
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — роль `conmon` и жизненный цикл процесса.
- **[Rootless режим в Podman](./podman_rootless.md)** — глубокое погружение в маппинг пользователей и подводные камни.

### Диагностика проблем изоляции

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `operation not permitted` | Заблокирован системный вызов (seccomp) или отсутствует Capability | Проверьте набор через `capsh --print`; добавьте `--cap-add` или `--security-opt seccomp=unconfined` для отладки |
| `permission denied` (на томах) | Ошибка маппинга UID/GID или SELinux | Используйте `podman unshare chown`, добавьте `:Z` к монтированию или `--userns=keep-id` |
| Контейнер не видит сеть | Отсутствует `pasta` или проблемы сетевым бэкендом | Установите пакет `passt`; проверьте `podman info --format '{{.Host.NetworkBackend}}'` |
| `unknown network mode` (slirp4netns / cni) | В Podman 6.0 драйверы `slirp4netns` и `cni` удалены | Замените на `pasta` (rootless) или `bridge`/`netavark` (rootful) |
| Ошибки Cgroups v1 | Хост работает на cgroups v1 (не поддерживается с Podman 6.0) | Переведите систему на cgroups v2 (единая иерархия `/sys/fs/cgroup`) |

**Совет:** Для анализа всех активных пространств имен в системе используйте утилиту `lsns`. Для анализа cgroups — `systemd-cgtop`.
