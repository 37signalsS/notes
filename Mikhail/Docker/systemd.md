# **Systemd в Docker: почему это анти-паттерн и как делать правильно**

---

## **Проблема: почему `systemd` не работает в Docker по умолчанию?**

**Симптомы:** вы создаете образ на базе Ubuntu/CentOS, устанавливаете `systemd` и запускаете контейнер с `CMD ["/sbin/init"]`. В результате `systemctl` зависает, сервисы не стартуют, а в логах появляются ошибки.

**Причины:**

1.  **`systemd` ожидает быть процессом с PID 1.** Он должен управлять всеми остальными процессами, собирать "зомби" и обрабатывать сигналы завершения. Docker по умолчанию сам управляет жизненным циклом основного процесса.

2.  **`systemd` требует доступа к `cgroups`.** Для управления ресурсами `systemd` активно работает с файловой системой `cgroups`. По умолчанию Docker предоставляет контейнеру ограниченное, виртуализированное представление о `cgroups` в `/sys/fs/cgroup`, которого `systemd` недостаточно.

3.  **`systemd` требует специальные `tmpfs`.** Ему необходимы смонтированные в режиме `tmpfs` директории `/run` и `/run/lock` для своей работы.

4.  **`systemd` требует повышенных привилегий.** Для выполнения своих системных задач ему необходимы права, которые Docker отбирает у контейнеров по соображениям безопасности (например, `CAP_SYS_ADMIN`).

---

## **3. Решение 1: "Docker-нативный" путь (Рекомендуется)**

Вместо того чтобы "впихивать" `systemd` в контейнер, используйте инструменты, созданные для экосистемы Docker.

### **Подход А: Разделение на несколько контейнеров с Docker Compose**

Это самый правильный и идиоматичный способ. Каждый сервис живет в своем контейнере.

```yaml
# docker-compose.yml
version: '3.8'
services:
  webapp:
    build: ./webapp
    ports:
      - "8080:80"

  database:
    image: postgres:14-alpine

  redis:
    image: redis:7-alpine
```

### **Подход Б: Использование легковесного менеджера процессов**

Если вам абсолютно необходимо запустить несколько процессов в одном контейнере (например, Nginx и PHP-FPM), используйте **`supervisord`**.

**`supervisord`** — это легковесный менеджер процессов, который отлично подходит для контейнеров. Он не требует специальных привилегий и легко настраивается.

**Пример `Dockerfile` с `supervisord`:**

```dockerfile
FROM ubuntu:22.04

# Устанавливаем supervisord и ваши сервисы
RUN apt-get update && apt-get install -y supervisor nginx

# Копируем конфигурацию для supervisord
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Говорим Docker, что supervisord теперь - главный процесс
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
```

**Пример `supervisord.conf`:**

```ini
[supervisord]
nodaemon=true

[program:nginx]
command=/usr/sbin/nginx -g "daemon off;"
autostart=true
autorestart=true

[program:my_app]
command=/path/to/your/app
autostart=true
autorestart=true
```

---

## **4. Решение 2: Запуск `systemd` силой (Не рекомендуется)**

Этот метод следует использовать только для тестирования или миграции легаси-систем, когда нет другого выбора. Он значительно снижает уровень изоляции и безопасности контейнера.

Чтобы заставить `systemd` работать, вам нужно вернуть ему все привилегии, которых его лишил Docker:

```sh
docker run -d --name systemd-container \
  --privileged \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  my-systemd-image
```

- `--privileged`: Дает контейнеру почти полный доступ к хост-системе. **Это очень небезопасно.**
- `--tmpfs`: Монтирует необходимые для `systemd` временные файловые системы.
- `-v /sys/fs/cgroup:/sys/fs/cgroup:ro`: Пробрасывает `cgroups` хоста в контейнер в режиме "только для чтения".
