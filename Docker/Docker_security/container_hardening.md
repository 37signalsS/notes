# Укрепление безопасности контейнеров (Hardening)

Данный документ описывает комплекс мер по минимизации поверхности атаки и усиления изоляции запущенных контейнеров на уровне среды выполнения (**runtime**).

## Определения

**Укрепление контейнеров (Container Hardening)** — процесс снижения рисков компрометации путем применения защитных конфигураций, ограничивающих возможности процессов внутри контейнера и их доступ к ресурсам ядра хоста.

**Принцип наименьших привилегий (Principle of Least Privilege)** — архитектурный подход, при котором процессу предоставляется минимально необходимый набор прав (Capabilities, доступ к ФС, сетевые доступы) для выполнения его функций.

**Поверхность атаки (Attack Surface)** — совокупность всех доступных точек взаимодействия (системные вызовы, открытые порты, примонтированные файлы), которые могут быть использованы злоумышленником для взлома.

## Базовые концепции

Безопасность контейнеров в Linux строится на многоуровневой изоляции, предоставляемой ядром:

1. **Namespaces (Пространства имен):** Обеспечивают логическую изоляцию ресурсов (сеть, процессы, монтирования). Особую роль в Hardening играют **User Namespaces**, позволяющие мапить UID 0 (root) контейнера на непривилегированного пользователя хоста. См. [**Изоляция контейнеров: Namespaces и Cgroups**](../../Docker/Concepts/linux_isolation.md).
2. **Cgroups v2:** Ограничивают потребление ресурсов (CPU, RAM, I/O), предотвращая DoS-атаки типа «шумный сосед» (Noisy Neighbor). Защищают от fork-бомб через `pids-limit`.
3. **Linux Capabilities:** Разделяют монолитные права `root` на мелкие привилегии. Опасные capability вроде `SYS_ADMIN`, `SYS_MODULE`, `SYS_PTRACE` исключены по умолчанию. См. [**Linux Capabilities**](../../Linux/Security/Mechanisms/Capabilities.md).
4. **LSM (Linux Security Modules):** Системы принудительного контроля доступа (MAC), такие как **AppArmor** и **SELinux**, ограничивающие действия процессов даже в случае компрометации.

### Современные тренды 2026 года

- **Sandboxed Runtimes:** Использование дополнительных уровней изоляции, таких как **gVisor** (перехват системных вызовов в userspace) или **Kata Containers** (запуск каждого контейнера в микро-VM).
- **Hardened Base Images:** Использование минималистичных образов (`Alpine`, `Distroless`, `Wolfi`), лишенных лишних утилит (`shell`, `curl`), что сокращает возможности злоумышленника для развития атаки.

## Практические сценарии

### 1. Управление привилегиями (Capabilities)

Docker по умолчанию оставляет около 14 возможностей (например, `NET_RAW`, `MKNOD`).

```bash
# Рекомендуемый подход: сбросить всё и добавить только нужное
docker run --cap-drop=ALL --cap-add=NET_BIND_SERVICE my-app
```

* **Запрет `--privileged`:** Этот флаг отключает Seccomp, AppArmor и предоставляет все Capabilities, давая полный доступ к устройствам хоста. **Запрещено в Production.**
* **Запрет повышения прав:** Флаг `no-new-privileges` блокирует получение прав через SUID/SGID бинарники.
  ```bash
  docker run --security-opt=no-new-privileges my-app
  ```

### 2. Фильтрация системных вызовов (Seccomp)

Стандартный профиль Docker блокирует около 44 опасных вызовов из 300+.

```bash
# Запуск с кастомным профилем seccomp
docker run --security-opt seccomp=/path/to/custom-profile.json my-app
```
*Подробнее о создании профилей:* [**Seccomp в Linux**](../../Linux/Security/Mechanisms/Seccomp.md).

### 3. Файловая система и тома

Большинство атак требует записи файлов. Режим `read-only` блокирует эти действия.

```bash
docker run \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid \
  my-app
```

**Управление доступом к томам:**
При использовании **bind mounts** файлы, созданные root-контейнером, принадлежат root-хосту.
* **Рекомендация:** Используйте **Docker Volumes** вместо bind mounts. Docker сам управляет правами доступа в своей директории, и при использовании `userns-remap` маппинг UID происходит прозрачно.
* Если bind mount необходим, монтируйте его в режиме `ro` (read-only):
  ```bash
  docker run -v /host/data:/app/data:ro my-app
  ```

### 4. Ограничение ресурсов (Cgroups)

```bash
docker run \
  --memory="512m" \
  --cpus="0.5" \
  --pids-limit 100 \
  --ulimit nofile=1024:1024 \
  my-app
```

## Дополнительная информация

### Аудит и проверка конфигурации

Для проверки текущих настроек безопасности запущенного контейнера используйте:
```bash
docker inspect <container_id> --format='{{json .HostConfig.SecurityOpt}}'
```

**Смотрите также:**

- **[Безопасность в Dockerfile](../Dockerfile/Docker_best_practices/security.md)** — практики на этапе сборки образа.
- **[Защита хоста и демона](./host_daemon_hardening.md)** — Rootless режим и userns-remap.
- **[Механизмы безопасности Linux](../../Linux/Security/Linux_Security_Mechanisms_Overview.md)** — детальный разбор Seccomp, AppArmor и SELinux.

**Инструменты:**
* **[Docker Bench for Security](https://github.com/docker/docker-bench-security)** — проверка по CIS Benchmark.
* **[Trivy](./vulnerability_scanning.md)** — сканирование образов на уязвимости (CVE).
