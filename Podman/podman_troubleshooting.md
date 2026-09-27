# Podman: Troubleshooting (систематический гайд)

## Определения

**Troubleshooting** — систематический подход к диагностике и устранению проблем в контейнерной среде Podman.

**Runbook** — пошаговая инструкция для диагностики и устранения типичных инцидентов.

**Root cause analysis (RCA)** — анализ первопричины проблемы для предотвращения повторения.

---

## Теоретический блок

### Методология troubleshooting

```
1. Определить симптом
      ↓
2. Собрать информацию (логи, статус, конфигурация)
      ↓
3. Изолировать проблему (контейнер, сеть, хранилище, хост)
      ↓
4. Найти root cause
      ↓
5. Устранить и проверить
      ↓
6. Задокументировать (runbook)
```

### Категории проблем

| Категория | Симптомы | Инструменты |
|---|---|---|
| **Запуск контейнера** | `Error creating container`, exit code != 0 | `podman logs`, `podman inspect` |
| **Сеть** | Нет доступа между контейнерами, DNS не работает | `podman network`, `podman port`, `nslookup` |
| **Хранилище** | `no space left`, тома не монтируются | `podman system df`, `df -h`, `podman volume` |
| **Производительность** | Медленный I/O, высокий CPU | `podman stats`, `top`, `iostat` |
| **Rootless** | `permission denied`, `cannot set namespace` | `podman unshare`, `/etc/subuid` |
| **Безопасность** | `denied by policy`, SELinux блокирует | `audit2allow`, `podman inspect` |

---

## Практический блок

### 1. Диагностика запуска контейнера

#### Контейнер падает сразу после запуска

```bash
# Проверить статус
podman ps -a | grep my-app

# Посмотреть логи
podman logs my-app

# Проверить exit code
podman inspect my-app --format '{{.State.ExitCode}}'

# Запустить с interact для отладки
podman run -it --rm my-app sh

# Проверить CMD/ENTRYPOINT
podman inspect my-app --format '{{.Config.Cmd}}'
podman inspect my-app --format '{{.Config.Entrypoint}}'

# Проверить переменные окружения
podman inspect my-app --format '{{.Config.Env}}'

# Проверить рабочую директорию
podman inspect my-app --format '{{.Config.WorkingDir}}'
```

#### Частые exit codes

| Exit Code | Причина | Решение |
|---|---|---|
| 0 | Успешное завершение | Проверить CMD/ENTRYPOINT |
| 1 | Ошибка приложения | Проверить логи |
| 125 | Ошибка контейнерного движка | Проверить `podman info` |
| 126 | Команда не может выполняться | Проверить права доступа |
| 127 | Команда не найдена | Проверить PATH, CMD |
| 137 | OOM Killed | Увеличить `--memory` |
| 139 | Segfault | Проблема в приложении |
| 143 | SIGTERM | Контейнер остановлен |

### 2. Проблемы с сетью

#### Контейнер не имеет доступа к сети

```bash
# Проверить сеть контейнера
podman inspect my-app --format '{{.NetworkSettings.Networks}}'

# Проверить DNS
podman exec my-app nslookup google.com

# Проверить маршрутизацию
podman exec my-app ip route

# Проверить сетевые интерфейсы
podman exec my-app ip addr

# Перезапустить сеть
podman network disconnect podman my-app
podman network connect podman my-app
```

#### DNS не работает

```bash
# Проверить DNS-серверы
podman exec my-app cat /etc/resolv.conf

# Запустить с кастомным DNS
podman run --rm --dns=8.8.8.8 alpine nslookup google.com

# Проверить DNS-сервис aardvark-dns
podman network inspect podman | grep -A 5 DNS
```

#### Порт не пробрасывается

```bash
# Проверить проброс портов
podman port my-app

# Проверить, слушает ли контейнер порт
podman exec my-app ss -tlnp

# Проверить, слушает ли хост порт
ss -tlnp | grep 8080

# Проверить firewall
sudo iptables -L -n | grep 8080
sudo firewall-cmd --list-ports
```

### 3. Проблемы с хранилищем

#### No space left on device

```bash
# Проверить использование диска
podman system df
df -h /var/lib/containers/storage

# Очистить неиспользуемые ресурсы
podman system prune -af

# Очистить конкретные образы
podman rmi -a

# Очистить тома
podman volume prune

# Проверить overlay storage
podman system info | grep -A 10 "store"
```

#### Том не монтируется

```bash
# Проверить, существует ли том
podman volume ls
podman volume inspect my-volume

# Проверить права доступа на хосте
ls -la /path/to/host/dir

# Проверить права в контейнере
podman exec my-app ls -la /mount/point

# Запустить с правами root для отладки
podman run --rm -v /path/to/host/dir:/mount -it alpine sh
```

#### Permission denied на том

```bash
# Проверить UID/GID в контейнере
podman exec my-app id

# Запустить с конкретным UID
podman run --rm -u 1000:1000 -v /data:/data alpine ls -la /data

# Исправить права на хосте
sudo chown -R 1000:1000 /data

# Использовать SELinux labels
podman run --rm -v /data:/data:z alpine sh  # :z = shared label
podman run --rm -v /data:/data:Z alpine sh  # :Z = private label
```

### 4. Rootless проблемы

```bash
# Проверить subuid/subgid
cat /etc/subuid
cat /etc/subgid

# Настроить subuid/subgid
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER

# Проверить user namespace
podman unshare cat /proc/self/uid_map

# Проверить, не запущено ли от root
whoami
id

# Очистить state rootless
podman system reset --force

# Проверить XDG_RUNTIME_DIR
echo $XDG_RUNTIME_DIR
ls -la $XDG_RUNTIME_DIR
```

#### "cannot set namespace" or "unable to create namespace"

```bash
# Проверить kernel support
cat /proc/sys/user/max_user_namespaces

# Увеличить лимит (временно)
sudo sysctl -w user.max_user_namespaces=28633

# Постоянно
echo "user.max_user_namespaces=28633" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### 5. Проблемы с образами

#### Образ не скачивается

```bash
# Проверить доступ к реестру
podman login docker.io

# Проверить сеть
podman pull docker.io/library/alpine:latest

# Проверить DNS
nslookup registry-1.docker.io

# Использовать зеркало
sudo tee /etc/containers/registries.conf.d/mirror.conf <<EOF
[[registry]]
location = "docker.io"
[[registry.mirror]]
location = "mirror.gcr.io"
EOF
```

#### Ошибка "manifest unknown"

```bash
# Проверить, существует ли тег
skopeo list-tags docker.io/library/my-app

# Проверить манифест
skopeo inspect docker.io/library/my-app:latest

# Использовать конкретный тег
podman pull docker.io/library/my-app:1.2.3

# Очистить кэш
podman system prune -af
```

### 6. Проблемы с производительностью

```bash
# Мониторинг ресурсов в реальном времени
podman stats

# Детальная статистика
podman stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}"

# Проверить cgroup v2
stat -fc %T /sys/fs/cgroup
# Ожидаемый результат: cgroup2fs

# Проверить лимиты ресурсов
podman inspect my-app --format '{{.HostConfig.Memory}}'
podman inspect my-app --format '{{.HostConfig.CpuQuota}}'

# Ограничить ресурсы
podman update --cpus=1.5 --memory=1g my-app
```

### 7. Проблемы с systemd

```bash
# Проверить статус сервиса
systemctl status podman-my-app

# Посмотреть логи через journalctl
journalctl -u podman-my-app -f

# Перезапустить сервис
sudo systemctl restart podman-my-app

# Проверить файл сервиса
cat /etc/systemd/system/podman-my-app.service

# Проверить зависимости
systemctl list-dependencies podman-my-app
```

#### Quadlet проблемы

```bash
# П�ерегенерировать systemd файлы
podman generate systemd --new --name my-app > /etc/systemd/system/my-app.service

# Перезагрузить systemd
sudo systemctl daemon-reload

# Проверить quadlet генерацию
podman quadlet --output /etc/containers/systemd my-app.container
```

### 8. Диагностические команды

```bash
# Информация о системе
podman info
podman info --format json | jq .

# Проверка хранилища
podman system df -v

# Список всех контейнеров (включая остановленные)
podman ps -a --format "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"

# Inspect контейнера
podman inspect my-app --format json | jq .

# Проверка сетей
podman network ls
podman network inspect podman

# Проверка томов
podman volume ls
podman volume inspect my-volume

# Проверка событий
podman events --filter container=my-app --since 1h

# Проверка process
podman top my-app

# Проверка файловых изменений
podman diff my-app
```

### 9. Сбор информации для поддержки

```bash
# Собрать все диагностические данные
podman info > /tmp/podman-info.txt
podman ps -a >> /tmp/podman-info.txt
podman images >> /tmp/podman-info.txt
podman network ls >> /tmp/podman-info.txt
podman volume ls >> /tmp/podman-info.txt
journalctl -u "podman*" --no-pager >> /tmp/podman-info.txt
dmesg | tail -100 >> /tmp/podman-info.txt

# Экспорт в JSON
podman system info --format json > /tmp/podman-system-info.json
podman ps -a --format json > /tmp/podman-containers.json
```

---

## Runbook: Типичные инциденты

### Инцидент 1: Контейнер OOM Killed

**Симптомы:** Контейнер завершается с exit code 137

```bash
# 1. Проверить exit code
podman inspect my-app --format '{{.State.ExitCode}}'

# 2. Проверить использование памяти
podman stats my-app

# 3. Проверить лимит
podman inspect my-app --format '{{.HostConfig.Memory}}'

# 4. Увеличить лимит
podman update --memory=2g my-app

# 5. Или пересоздать с новым лимитом
podman rm my-app
podman run -d --memory=2g --name my-app my-app:latest
```

### Инцидент 2: Порт уже занят

**Симптомы:** `Error: address already in use`

```bash
# 1. Найти процесс, занимающий порт
sudo ss -tlnp | grep :8080

# 2. Убить процесс
sudo kill -9 <PID>

# 3. Или использовать другой порт
podman run -d -p 8081:80 my-app:latest
```

### Инцидент 3: SELinux блокирует доступ

**Симптомы:** `Permission denied` при доступе к томам

```bash
# 1. Проверить SELinux
getenforce

# 2. Посмотреть audit логи
sudo ausearch -m AVC -ts recent

# 3. Сгенерировать политику
sudo audit2allow -a -M podman_local

# 4. Применить политику
sudo semodule -i podman_local.pp

# 5. Или использовать :z/:Z labels
podman run -v /data:/data:z my-app:latest
```

### Инцидент 4: Rootless не работает

**Симптомы:** `unable to create namespace`, `permission denied`

```bash
# 1. Проверить subuid/subgid
cat /etc/subuid | grep $USER
cat /etc/subgid | grep $USER

# 2. Настроить если нет
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER

# 3. Проверить kernel параметры
cat /proc/sys/user/max_user_namespaces

# 4. Увеличить если нужно
sudo sysctl -w user.max_user_namespaces=28633

# 5. Перезапустить Podman
podman system reset --force
```

### Инцидент 5: Disk full

**Симптомы:** `no space left on device`

```bash
# 1. Проверить использование
podman system df
df -h

# 2. Очистить Podman ресурсы
podman system prune -af
podman volume prune

# 3. Очистить systemd journal
sudo journalctl --vacuum-size=1G

# 4. Найти большие файлы
sudo du -sh /var/lib/containers/* | sort -rh | head -5

# 5. Очистить overlay storage
sudo rm -rf /var/lib/containers/storage/overlay/*
```

---

## Дополнительная информация

### Полезные алиасы

```bash
# ~/.bashrc или ~/.zshrc
alias pc='podman container'
alias pi='podman image'
alias pp='podman pod'
alias pv='podman volume'
alias pn='podman network'
alias plog='podman logs -f'
alias pstats='podman stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"'
```

### Полезные скрипты

```bash
#!/bin/bash
# podman-healthcheck.sh - проверка всех контейнеров

echo "=== Podman Health Check ==="
echo "Дата: $(date)"
echo ""

echo "=== Контейнеры ==="
podman ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=== Ресурсы ==="
podman stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"

echo ""
echo "=== Использование диска ==="
podman system df

echo ""
echo "=== Ошибки в логах (последние 10 минут) ==="
for container in $(podman ps -q); do
    name=$(podman inspect --format '{{.Name}}' $container)
    errors=$(podman logs --since 10m $container 2>&1 | grep -i error | wc -l)
    if [ $errors -gt 0 ]; then
        echo "[$name] $errors ошибок за последние 10 минут"
    fi
done
```

### Ссылки

- **[Podman commands](./podman_basic_commands.md)** — CLI команды
- **[Rootless](./podman_rootless.md)** — rootless режим
- **[Linux Isolation](./linux_isolation.md)** — namespaces, cgroups
- **[Docker Troubleshooting](../../Docker/Docker_troubleshooting/docker_debug.md)** — troubleshooting Docker
- **[Kubernetes Troubleshooting](../../Kubernetes/Troubleshooting/troubleshooting_overview.md)** — troubleshooting K8s
