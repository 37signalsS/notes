# Systemd в Docker: почему это анти-паттерн 

`systemd` не работает в Docker "из коробки" по нескольким причинам:

1.  **Ожидание PID 1:** `systemd` должен быть первым процессом в системе (PID 1) для управления дочерними процессами и сбора "зомби". В Docker эту роль выполняет основной процесс, указанный в `CMD` или `ENTRYPOINT`.
2.  **Требование доступа к `cgroups`:** Для управления ресурсами `systemd` требует полного доступа к файловой системе `cgroups` хоста. Docker по умолчанию предоставляет контейнеру лишь ограниченное, виртуализированное представление в `/sys/fs/cgroup`.
3.  **Требование `tmpfs`:** `systemd` ожидает, что директории `/run`, `/run/lock` и `/tmp` будут смонтированы как временные файловые системы (`tmpfs`).
4.  **Требование привилегий:** Для выполнения своих задач `systemd` требует расширенных прав ядра (Linux capabilities), таких как `CAP_SYS_ADMIN`, которые Docker отбирает у контейнеров по соображениям безопасности.

---

## Решения

### Легковесный менеджер процессов `supervisord`

Если вам абсолютно необходимо запустить несколько процессов в одном контейнере (например, Nginx и PHP-FPM), используйте **`supervisord`**. Он легковесный, не требует привилегий и отлично подходит для контейнеров.

**Пример `Dockerfile`:**
```dockerfile
FROM ubuntu:24.04

# Устанавливаем supervisor и ваши сервисы
RUN apt-get update && apt-get install -y supervisor nginx

# Копируем конфигурацию для supervisord
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Говорим Docker, что supervisord теперь - главный процесс
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
```

**Пример `supervisord.conf`:**
```ini
[supervisord]
nodaemon=true # Запускаем supervisor на переднем плане

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

## "Силовой" запуск `systemd`

**Внимание:** Этот метод значительно снижает уровень изоляции и безопасности. Используйте его только для тестирования или миграции легаси-систем, когда нет другого выбора.

Чтобы заставить `systemd` работать, вам нужно вернуть ему все привилегии, которых его лишил Docker:

```sh
docker run -d --name systemd-container \
  --privileged \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  my-systemd-image /sbin/init
```

- `--privileged`: Дает контейнеру почти полный доступ к хост-системе. **Это огромная дыра в безопасности.**
- `-v /sys/fs/cgroup:/sys/fs/cgroup:ro`: Пробрасывает `cgroups` хоста в контейнер.
- `/sbin/init`: Явно указывает `systemd` в качестве точки входа.
