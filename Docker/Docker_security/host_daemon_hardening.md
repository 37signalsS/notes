# Защита хоста и демона Docker (Hardening)

## Определения

**Защита хоста и демона Docker (Host and Daemon Hardening)** — настройка хостовой ОС и демона `dockerd` для минимизации поверхности атаки. Цель — не допустить компрометацию хоста через уязвимость в контейнере. Практики входят в стандарт **CIS Docker Benchmark**.

## Базовые концепции

### 1. User Namespaces (`userns-remap`)

**User namespaces** изолируют UID/GID контейнера от хоста. Процесс с UID 0 (root) в контейнере отображается на непривилегированного пользователя на хосте.

- **В контейнере:** UID 0..65535
- **На хосте:** UID 100000..165536 (пример)

### 2. Rootless Docker

**Rootless Docker** — демон и контейнеры запускаются от непривилегированного пользователя. Компрометация демона не дает root-доступ к хосту. Подробнее: **[Rootless режим в Podman](../../Podman/podman_rootless.md)** (архитектурные принципы).

| Риск | Docker (root) | Rootless Docker |
| :--- | :--- | :--- |
| **Побег из контейнера** | Эскалация до root на хосте | Ограничение до обычного пользователя |
| **Компрометация демона** | Root-операции над системой | Нет доступа к системным ресурсам |

### 3. LSM (Linux Security Modules)

Docker использует модули ядра для принудительной изоляции:

- **[Seccomp](../../Linux/Security/Mechanisms/Seccomp.md)**: Ограничивает `syscalls` контейнера (профиль по умолчанию блокирует опасные вызовы).
- **[AppArmor](../../Linux/Security/Mechanisms/AppArmor.md)** / **[SELinux](../../Linux/Security/Mechanisms/SELinux.md)**: MAC-механизмы, ограничивающие доступ к файлам и ресурсам.

### 4. Docker Socket

Проброс `/var/run/docker.sock` в контейнер = `root`-доступ к хосту. Анализ угрозы: **[Обзор безопасности Docker](./overview.md)**.

## Практические сценарии

### 1. Настройка User Namespaces (`daemon.json`)

1. Создайте пользователя и выделите ему диапазоны subuid/subgid:

    ```bash
    sudo usermod --add-subuids 100000-165536 --add-subgids 100000-165536 dockremap
    ```

2. Активируйте `userns-remap` в `/etc/docker/daemon.json`:

    ```json
    {
      "userns-remap": "default"
    }
    ```

3. Перезапустите Docker. **Особенность**: для bind-монтов может потребоваться `chown` файлов на хосте.

### 2. Установка и запуск Rootless Docker

1. Установите необходимые пакеты:

    ```bash
    sudo apt-get update && sudo apt-get install -y uidmap slirp4netns
    ```

2. Запустите установочный скрипт от имени обычного пользователя:

    ```bash
    dockerd-rootless-setuptool.sh install
    ```

3. Настройте переменные окружения для сессии:

    ```bash
    export XDG_RUNTIME_DIR=/run/user/$(id -u)
    export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
    ```

4. Проверьте: `docker info | grep Rootless` должен показать `Rootless: true`.

### 3. Использование AppArmor и SELinux

- **Проверка статуса**: `docker info | egrep -i 'apparmor|selinux'`
- **Применение профиля AppArmor**:

    ```bash
    docker run --rm --security-opt apparmor=my-custom-profile nginx
    ```

- **Работа с SELinux и томами**: При монтировании томов используйте флаг `:z` (общий доступ) или `:Z` (эксклюзивный доступ) для автоматической смены контекста безопасности.

    ```bash
    docker run -v /srv/data:/data:Z ubuntu bash
    ```

### 4. Безопасная конфигурация демона (`/etc/docker/daemon.json`)

```json
{
  "icc": false,
  "userns-remap": "default",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "no-new-privileges": true,
  "disable-legacy-registry": true
}
```

- `"icc": false"`: Запрещает сетевое взаимодействие между контейнерами по умолчанию.
- `"no-new-privileges": true"`: Запрещает процессам внутри контейнера повышать свои привилегии через `setuid` или `setgid` бинарники.

## Дополнительная информация

**Сравнение режимов:**

| Режим | Привилегии на хосте | Простота | Ограничения |
| :--- | :--- | :--- | :--- |
| **Стандартный** | `root` в контейнере = `root` на хосте | Высокая | Минимальные, **опасно** |
| **`userns-remap`** | `root` в контейнере → непривилегированный UID | Средняя | Требует `chown` для томов |
| **Rootless Docker** | Демон и контейнеры без `root` | Ниже | Ограничения сети, ядра, нет `privileged` |

**Связанные документы:** **[Укрепление безопасности контейнеров](./container_hardening.md)**, **[Podman vs Docker](../../Podman/podman_vs_docker.md)**, **[Механизмы изоляции Linux](../../Docker/Concepts/linux_isolation.md)**.
